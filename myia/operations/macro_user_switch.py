"""Implementation of the 'user_switch' operation."""

from collections import defaultdict
from functools import reduce
from itertools import product
from ovld import ovld

from myia.abstract.data import AbstractWrapper, AbstractValue, AbstractCast
from .. import lib
from ..lib import (
    ANYTHING,
    CloneRemapper,
    Constant,
    Graph,
    GraphCloner,
    MyiaTypeError,
    force_pending,
    macro,
    union_simplify,
)
from ..xtype import Bool
from . import primitives as P


class _CastRemapper(CloneRemapper):
    def __init__(
        self,
        graphs,
        inlines,
        manager,
        relation,
        graph_relation,
        clone_constants,
        graph_repl,
        fv_replacements,
    ):
        """Initialize the GraphCloner."""
        super().__init__(
            graphs=graphs,
            inlines=inlines,
            manager=manager,
            relation=relation,
            graph_repl=graph_repl,
            graph_relation=graph_relation,
            clone_constants=clone_constants,
        )
        self.fv_replacements = fv_replacements

    def gen_fv(self, g, ng, fv):
        """Remap the free variables we want to remap."""
        if fv in self.fv_replacements:
            new = self.fv_replacements[fv]
            self.remap_node((g, fv), g, fv, ng, new, link=False)


@ovld.dispatch(initial_state=lambda: dict())
def constains_union(self, x):
    __call__ = self.resolve(x)
    cache = self.state

    try:
        res = cache.get(x, None)
    except TypeError:
        return __call__(x)

    if res is None:
        cache[x] = set()
        cache[x] = __call__(x)
        return cache[x]

    return res


@ovld # noqa: F811
def contains_union(self, x: lib.AbstractUnion):
    return set([x])


@ovld # noqa: F811
def contains_union(self, x: AbstractWrapper):
    return set.union(*[self(c) for c in x.children()])


@ovld # noqa: F811
def contains_union(self, x: AbstractValue):
    return set()


@lib.abstract_clone.variant
def _get_type(self, x: lib.AbstractUnion, *, u, opt):
    if x is u:
        yield None
        return opt
    else:
        return (yield lib.AbstractUnion)(self(x.options, u=u, opt=opt))


@ovld.dispatch(initial_state=lambda: {'cache': dict()})
def getrepl(self, node, typ, ntyp):
    cache = self.cache
    try:
        return cache[node]
    except KeyError:
        call = self.resolve(node, typ, ntyp)
        rval = call(node, typ, ntyp)
        cache[node] = rval
        return rval


@ovld
def getrepl(self, node, typ: object, ntyp):
    return node


@ovld
def getrepl(self, node, typ: AbstractWrapper, ntyp):
    # We should never get here
    assert False


@ovld
def getrepl(self, node, typ: lib.AbstractUnion, ntyp):
    if typ is not ntyp:
        g = node.graph
        return g.apply(P.unsafe_static_cast, node, ntyp)
    else:
        return node


@ovld
def getrepl(self, node, typ: lib.AbstractTuple, ntyp):
    g = node.graph
    rval = node
    for i, (e, n) in enumerate(zip(typ.elements, ntyp.elements)):
        elem = g.apply(P.tuple_getitem, node, i)
        res = self(elem, e, n)
        if elem is not res:
            rval = g.apply(P.tuple_setitem, rval, i, res)
    return rval


@ovld
def getrepl(self, node, typ: lib.AbstractHandle, ntyp):
    g = node.graph
    ntyp2 = lib.AbstractHandle(AbstractCast(ntyp.element), values=ntyp.values)
    return g.apply(P.unsafe_static_cast, node, ntyp2)


async def make_trials(engine, ref, repl, relevant):
    """Return a collection of alternative subtrees to test type combinations.

    The subtree for ref.node is explored, and for every Union encountered we
    create a subtree for each combination of options. For example, if
    :code:`x :: Union(i64, None)`, :code:`y :: Union(i64, None)`,
    :code:`z :: i64` and :code:`ref.node = x * y * z`, make_trials
    returns the following::

        {
          {(x, i64),  (y, i64)}:  cast(x, i64) * cast(y, i64) * z
          {(x, None), (y, i64)}:  cast(x, None) * cast(y, i64) * z
          {(x, i64),  (y, None)}: cast(x, i64) * cast(y, None) * z
          {(x, None), (y, None)}: cast(x, None) * cast(y, None) * z
        }

    This is not cheap, and exponential in the number of distinct unions
    encountered, but in practice, conditions of if statements should not
    contain a whole lot of these and it should probably be fine.

    Returns:
        A :code:`{{(node, type), ...}: replacement_node}` dictionary, where
        replacement_node is a node that corresponds to ref.node, but uses
        `unsafe_static_cast(node, type)` for each `(node, type)` pair in the
        set, for each occurrence of `node` in the subtree.

    """

    def prod(options, finalize):
        # This performs the cartesian product of the options. The nodes are
        # merged using the finalize function.
        res = {}
        for entry in product(*options):
            s = set()
            for s2, n in entry:
                s |= s2
            nodes = [n for _, n in entry]
            res[frozenset(s)] = finalize(nodes)
        return res

    node = ref.node
    g = node.graph

    if ref.node in relevant:
        typ = await ref.get()

        res = contains_union(typ)
        if len(res) != 0:
            rval = dict()
            for u in res:
                for opt in (await force_pending(u.options)):
                    ntyp = _get_type(typ, u=u, opt=opt)
                    rval[frozenset({(node, ntyp)})] = getrepl(node, typ, ntyp)
            return rval

    if ref.node.is_apply():
        # Return the cartesian product of the entries for each argument.
        arg_results = [
            (
                await make_trials(engine, engine.ref(arg, ref.context), repl,
                                  relevant)
            ).items()
            for arg in ref.node.inputs
        ]

        def _finalize(nodes):
            if nodes == ref.node.inputs:
                # Avoid unnecessary cloning
                return node
            else:
                return g.apply(*nodes)

        return prod(arg_results, _finalize)

    elif ref.node.is_constant_graph():
        # Do the cartesian product for all the free variables, then make a
        # clone of the graph for each possibility, using _CastRemapper to point
        # to the casted free variables. (This is needed to support expressions
        # like `if x is None and y is None: ...`, because the second clause is
        # a closure).
        g = ref.node.value
        if g.parent is None:
            return {frozenset(): ref.node}
        else:
            fvs = list(g.free_variables_total)
            trials = []
            while fvs:
                fv = fvs.pop()
                if isinstance(fv, Graph):
                    fvs += fv.free_variables_total
                    continue
                trial = await make_trials(
                    engine, engine.ref(fv, ref.context), repl, relevant
                )
                trials.append(trial.items())
            res = {}
            for entry in prod(trials, lambda _: None):
                fv_repl = dict()
                for node, opt in entry:
                    typ = await engine.ref(node, ref.context).get()
                    fv_repl[node] = getrepl(node, typ, opt)
                # NOTE: total=True may be overkill here, but the alternative is
                # to collect siblings of g that g may refer to, which is what's
                # done in the wrap function below.
                cl = GraphCloner(
                    g,
                    total=True,
                    remapper_class=_CastRemapper.partial(
                        fv_replacements=fv_repl
                    ),
                )
                engine.mng.add_graph(cl[g])
                res[entry] = Constant(cl[g])
            return res

    else:
        # This is not a union or an application, there is only one possibility.
        return {frozenset(): ref.node}


async def execute_trials(engine, cond_trials, g, condref, tbref, fbref):
    """Handle code like `user_switch(hastype(x, typ), tb, fb)`.

    cond_trials must be in the format returned by `make_trials`.

    We want to evaluate tb in a context where x has type typ and fb
    in a context where it doesn't.
    """

    async def wrap(branch_ref, branch_types):
        # We transform branch_graph into a new graph which refers to a cast
        # version of x. We also transform all of the children of x's graph
        # so that closures called in the branch also refer to the cast
        # version of x.
        branch_graph = branch_ref.node.value
        nomod = True

        rval = branch_graph.make_new(relation="copy")
        children = set()
        fv_repl = {}
        for node, typ in branch_types.items():
            if branch_graph not in node.graph.scope:
                continue
            nomod = False
            children.update(node.graph.children)
            cast = rval.apply(P.unsafe_static_cast, node, typ)
            fv_repl[node] = cast

        if nomod:
            return branch_graph

        cl = GraphCloner(
            *children,
            total=False,
            graph_repl={branch_graph: rval},
            remapper_class=_CastRemapper.partial(fv_replacements=fv_repl)
        )
        assert rval is cl[branch_graph]
        engine.mng.add_graph(rval)
        return rval

    cond = condref.node
    ctx = condref.context

    groups = {True: defaultdict(list), False: defaultdict(list)}

    replaceable_condition = True
    for keys, cond_trial in cond_trials.items():
        if len(set(node for node, opt in keys)) != len(keys):
            continue
        result = await engine.ref(cond_trial, ctx).get()
        assert result.xtype() is Bool
        value = result.xvalue()
        if value is ANYTHING:
            replaceable_condition = False
            bucket = [True, False]
        else:
            bucket = [value]
        for node, opt in keys:
            for value in bucket:
                groups[value][node].append(opt)

    typemap = {}
    for key, mapping in groups.items():
        typemap[key] = {
            node: union_simplify(opts) for node, opts in mapping.items()
        }

    if not groups[True]:
        return fbref
    elif not groups[False]:
        return tbref
    else:
        if replaceable_condition:
            # If each type combination gives us a definite True or False
            # for the condition, we don't need to keep the original
            # condition.
            type_filter_parts = []
            for node, types in groups[True].items():
                parts = [g.apply(P.hastype, node, t) for t in types]
                new_cond = reduce(lambda x, y: g.apply(P.bool_or, x, y), parts)
                type_filter_parts.append(new_cond)
            type_filter = reduce(
                lambda x, y: g.apply(P.bool_and, x, y), type_filter_parts
            )
            new_cond = type_filter
        else:
            new_cond = cond
        new_tb = await wrap(tbref, typemap[True])
        new_fb = await wrap(fbref, typemap[False])
        return g.apply(P.switch, new_cond, new_tb, new_fb)


@macro
async def user_switch(info, condref, tbref, fbref):
    """Implement the switch functionality generated by the parser.

    If user_switch finds a Union in the condition, it will infer the value of
    the condition for each type in the union. If the condition is necessarily
    true or false for some types, the type of the variable for the
    corresponding conditional branch will be set to these types.
    """
    engine = info.engine
    g = info.graph

    for branch_ref in [tbref, fbref]:
        if not branch_ref.node.is_constant_graph():
            raise MyiaTypeError(
                "Both branches of user_switch must be constant graphs."
            )

    orig_cond = cond = condref.node

    condt = await condref.get()
    if not engine.check_predicate(Bool, condt):
        to_bool = engine.resources.convert(bool)
        cond = (cond.graph or g).apply(to_bool, cond)

    if orig_cond.graph is not None and cond.is_apply():
        new_condref = engine.ref(cond, condref.context)
        relevant = (tbref.node.value.free_variables_total.keys() |
                    fbref.node.value.free_variables_total.keys())
        cond_trials = await make_trials(engine, new_condref, {}, relevant)
        if len(cond_trials) > 1:
            return await execute_trials(
                engine, cond_trials, g, new_condref, tbref, fbref
            )

    _, _, tb, fb = info.outref.node.inputs
    return g.apply(P.switch, cond, tb, fb)


__operation_defaults__ = {
    "name": "user_switch",
    "registered_name": "user_switch",
    "mapping": user_switch,
    "python_implementation": None,
}
