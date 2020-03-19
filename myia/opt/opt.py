"""Graph optimization routines."""

from collections import deque, defaultdict
from weakref import WeakKeyDictionary

from ..info import About
from ..ir import Apply, Graph, manage, sexp_to_node
from ..operations import Primitive
from ..utils import OrderedSet, tracer
from ..utils.unify import Unification, Var


class PatternSubstitutionOptimization:
    """An optimization that replaces one pattern by another.

    Args:
        pattern: An s-expression, represented as a nested tuple, that
            represents an expression to match. Terms in the s-expression
            may be Var instances or constants.
        replacement:
            * An s-expression, represented as a nested tuple, to
              instantiate to replace the pattern. Vars in the pattern can
              be reused in the replacement.
            * OR a function which will be called when the pattern is
              matched, with the node and the equivalence dictionary as
              arguments.
        name: The name of the optimization.
        multigraph: Whether the pattern can span multiple graphs or not.
            A pattern can span multiple graphs if, for example, the root
            of the pattern is in a closure, and some of the leaves are in
            the parent function of that closure.

    Attributes:
        pattern: The pattern, converted to Myia's IR.
        replacement: The replacement, converted to Myia's IR.
        name: The name of the optimization.

    """

    def __init__(self,
                 pattern,
                 replacement,
                 *,
                 condition=None,
                 name=None,
                 multigraph=True,
                 interest=False):
        """Initialize va PatternSubstitutionOptimization."""
        g: Var = Var('RootG')
        self.sexp = pattern
        self.pattern = sexp_to_node(pattern, g, multigraph)
        if callable(replacement):
            self.replacement = replacement
        else:
            self.sexp_replacement = replacement
            self.replacement = sexp_to_node(replacement, g)
        self.unif = Unification()
        self.condition = condition
        self.name = name
        if interest is False:
            if (self.pattern.is_apply() and
                    self.pattern.inputs[0].is_constant(Primitive)):
                interest = self.pattern.inputs[0].value
            else:
                # Maybe warn in this case?
                interest = None
        self.interest = interest

    def __call__(self, resources, node):
        """Return a replacement for the node, if the pattern matches.

        The replacement will be instantiated in the graph of the root of the
        pattern, except for matched nodes in the pattern, which are kept
        unchanged in the replacement.

        Returns:
            * None if the pattern does not match.
            * A subgraph for the reification of the replacement, with
              variables filled in, if the pattern matches.

        """
        equiv = self.unif.unify(node, self.pattern)
        if equiv is not None:
            if callable(self.replacement):
                return self.replacement(resources, node, equiv)
            elif self.condition is None or self.condition(equiv):
                return self.unif.reify(self.replacement, equiv)
        else:
            return None

    def __str__(self):
        return f'<PatternSubstitutionOptimization {self.name}>'

    __repr__ = __str__


def pattern_replacer(*pattern, interest=False):
    """Create a PatternSubstitutionOptimization using this function."""
    if len(pattern) == 2 and pattern[0] == 'just':
        pattern = pattern[1]

    def deco(f):
        return PatternSubstitutionOptimization(pattern, f, name=f.__name__,
                                               interest=interest)
    return deco


class NodeMap:
    """Mapping of node to optimizer.

    This helps global optimizers select the relevant optimizers to
    apply for each node.

    Optimizers that are mapped to None are considered relevant for all
    nodes.

    Other than None, only primitives are currently supported as interests.

    """

    def __init__(self):
        """Create a NodeMap."""
        self._d = dict()

    def register(self, interests, opt=None):
        """Register an optimizer for some interests."""
        def do_register(opt):
            ints = interests
            if ints is None:
                self._d.setdefault(None, []).append(opt)
                return
            if not isinstance(ints, tuple):
                ints = (ints,)
            for interest in ints:
                assert (isinstance(interest, Primitive) or
                        (interest in (Graph, Apply)))
                self._d.setdefault(interest, []).append(opt)

        # There could be the option to return do_register also.
        do_register(opt)

    def get(self, node):
        """Get a list of optimizers that could apply for a node."""
        res = []
        res.extend(self._d.get(None, []))
        if node.is_apply():
            if node.inputs[0].is_constant():
                res.extend(self._d.get(node.inputs[0].value, []))
            if node.inputs[0].is_constant_graph():
                res.extend(self._d.get(Graph, []))
            if node.inputs[0].is_apply():
                res.extend(self._d.get(Apply, []))
        return res


class LocalPassOptimizer:
    """Apply a set of local optimizations in bfs order."""

    def __init__(self, node_map, resources=None):
        """Initialize a LocalPassOptimizer."""
        self.node_map = node_map
        self.resources = resources

    def __call__(self, graph):
        """Apply optimizations on given graphs in node order.

        This will visit the nodes from the output to the inputs in a
        bfs manner while avoiding parts of the graph that are dropped
        due to optimizations.
        """
        if self.resources is not None:
            mng = self.resources.manager
            mng.add_graph(graph)
        else:
            mng = manage(graph)

        seen = set([graph])
        todo = deque()
        changes = False
        todo.append(graph.output)

        while len(todo) > 0:
            n = todo.popleft()
            if n in seen or n not in mng.all_nodes:
                continue
            seen.add(n)

            new, chg = self.apply_opt(mng, n)

            changes |= chg

            if new.is_constant(Graph):
                if new.value not in seen:
                    todo.appendleft(new.value.output)
                    seen.add(new.value)
            else:
                todo.extendleft(reversed(new.inputs))

            if chg:
                # Since there was changes, re-schedule the parent node(s)
                uses = OrderedSet(u[0] for u in mng.uses[new])
                seen.difference_update(uses)
                todo.extendleft(uses)

        return changes

    def apply_opt(self, mng, n):
        """Apply optimizations passes according to the node map."""
        loop = True
        changes = False
        while loop:
            loop = False
            for transformer in self.node_map.get(n):
                args = dict(
                    opt=transformer,
                    node=n,
                    manager=mng,
                    profile=False,
                )
                with tracer('opt', **args) as tr:
                    tr.set_results(success=False, **args)
                    with About(n.debug, 'opt', transformer.name):
                        new = transformer(self.resources, n)
                    if new is not None and new is not n:
                        tracer().emit_match(**args, new_node=new)
                    if new is True:
                        changes = True
                        continue
                    if new and new is not n:
                        mng.replace(n, new)
                        tracer().emit_success(**args, new_node=new)
                        tr.set_results(success=True, **args)
                        n = new
                        loop = True
                        changes = True
                        break

        return n, changes

class _RegistryEntry(OrderedSet):
    def __init__(self):
        super().__init__([])
        self.recording = False
        self.new = []

    def add(self, v):
        super().add(v)
        if self.recording:
            self.new.append(v)

    def remove(self, v):
        if self.recording:
            try:
                self.new.remove(v)
            except ValueError:
                pass
        super().remove(v)

    def start_recording(self):
        assert self.recording is False
        self.recording = True
        self.new = []

    def stop_recording(self):
        self.recording = False
        self.new = []


class ApplyMap:
    """
    Keep a live map of apply values to nodes.
    """

    def __init__(self, manager):
        self.registry = defaultdict(_RegistryEntry)
        self.manager = manager
        self._recording = False
        self._new = []

        for node in manager.all_nodes:
            self._on_add_node(None, node)

        evts = manager.events
        evts.add_node.register(self._on_add_node)
        evts.drop_node.register(self._on_drop_node)

    def detach(self):
        evts = self.manager.events
        evts.add_node.remove(self._on_add_node)
        evts.drop_node.remove(self._on_drop_node)
        self.registry = None
        self.manager = None

    def start_recording(self):
        assert self._recording is False
        self._recording = True
        self._new = []

    def stop_recording(self):
        self._recording = False
        self._new = []

    def _all_node_iter(self):
        """Iterator to visit all the nodes in a changing manager."""
        self.start_recording()
        nodes = list(self.manager.all_nodes)
        for node in nodes:
            if node in self.manager.all_nodes:
                yield node

        while True:
            new_nodes = self._new
            self._new = []
            if len(new_nodes) == 0:
                break
            for node in new_nodes:
                if node in self.manager.all_nodes:
                    yield node
        self.stop_recording()

    def get_nodes(self, interest):
        yield from self._all_node_iter()

    """
        if interest is None:
            pass
        else:
            if not isinstance(interest, tuple):
                interest = (interest,)
            for int in interest:
                nodes = self.registry[int]
                nodes.start_recording()
                for node in list(nodes):
                    if node in self.manager.all_nodes:
                        yield node
            stop = False
            while not stop:
                stop = True
                for int in interest:
                    nodes = self.registry[int]
                    new = list(nodes.new)
                    nodes.new = []
                    if len(new) != 0:
                        stop = False
                        for node in new:
                            if node in self.manager.all_nodes:
                                yield node
            for int in interest:
                self.registry[int].stop_recording()
    """

    def _on_add_node(self, event, node):
        if self._recording:
            self._new.append(node)
        if node.is_apply():
            self.registry[Apply].add(node)
            if node.inputs[0].is_constant_graph():
                self.registry[Graph].add(node)
            elif node.inputs[0].is_constant():
                self.registry[node.inputs[0].value].add(node)

    def _on_drop_node(self, event, node):
        if self._recording:
            try:
                self._new.remove(node)
            except ValueError:
                pass
        if node.is_apply():
            self.registry[Apply].remove(node)
            if node.inputs[0].is_constant_graph():
                self.registry[Graph].remove(node)
            elif node.inputs[0].is_constant():
                self.registry[node.inputs[0].value].remove(node)


class SweepPassOptimizer:
    def __init__(self, opt_list, resources=None):
        self.opt_list = opt_list
        self.resources = resources

    def __call__(self, graph):
        if self.resources is not None:
            mng = self.resources.manager
            mng.add_graph(graph)
        else:
            mng = manage(graph)

        amap = ApplyMap(mng)
        changes = False

        for opt in self.opt_list:
            changes |= self.opt_pass(opt, mng, amap)

        amap.detach()
        return changes

    def opt_pass(self, opt, mng, amap):
        changes = False
        interest = getattr(opt, 'interest', None)
        for node in amap.get_nodes(interest):
            args = dict(
                opt=opt,
                node=node,
                manager=mng,
                profile=False,
            )
            with tracer('opt', **args) as tr:
                tr.set_results(success=False, **args)
                with About(node.debug, 'opt', opt.name):
                    new = opt(self.resources, node)
                if new is True:
                    changes = True
                elif new is not None and new is not node:
                    tracer().emit_match(**args, new_node=new)
                    mng.replace(node, new)
                    tracer().emit_success(**args, new_node=new)
                    tr.set_results(success=True, **args)
                    changes = True
                    #self.process_revisits(mng, amap)
        return changes


class GraphTransform:
    """Represents a graph transform.

    The transform of a graph is unique and it is stored in graph.transforms.
    Here are examples of graph transforms:

    * A graph's gradient.
    * A copy of the graph, except the output is called.
    * A copy of the graph, except it returns the ith element of the output.
    """

    def __init__(self, compute):
        """Initialize a GraphTransform."""
        self.cache = WeakKeyDictionary()
        self.compute = compute

    def __call__(self, graph, *args):
        """Return the transformed graph.

        Computes the transform if it isn't already available.
        """
        if graph not in self.cache:
            self.cache[graph] = {}
        cache = self.cache[graph]
        if args not in cache:
            cache[args] = self.compute(graph, *args)
        return cache[args]


__all__ = [
    'GraphTransform',
    'LocalPassOptimizer',
    'NodeMap',
    'PatternSubstitutionOptimization',
    'pattern_replacer',
    'SweepPassOptimizer',
]
