"""Definitions for the primitive `universe_getitem`."""

from .. import lib, xtype
from ..lib import broaden, standard_prim, StandardInferrer
from . import primitives as P
from myia.abstract.data import AbstractCast
from .macro_user_switch import getrepl


def pyimpl_universe_getitem(universe, handle):
    """Implement `universe_getitem`."""
    return universe.get(handle)


@standard_prim(P.universe_getitem)
class _UniverseGetitemInferrer(StandardInferrer):
    def __init__(self):
        super().__init__(P.universe_getitem, self.__infer)

    async def reroute(self, engine, outref, argrefs):
        if len(argrefs) != 2:
            # We let infer deal with this
            return None

        h_t = await argrefs[1].get()
        if not isinstance(h_t, lib.AbstractHandle):
            # We let infer deal with this
            return None

        if isinstance(h_t.element, AbstractCast):
            o_t = h_t.element.old
            g = outref.node.graph
            node = g.apply(
                P.universe_getitem,
                argrefs[0].node,
                g.apply(P.cast_handle, argrefs[1].node, o_t),
            )
            return engine.ref(
                getrepl(g, node, o_t, h_t.element.element), outref.context
            )

        return None

    @staticmethod
    async def __infer(
        self, engine, universe: xtype.UniverseType, handle: lib.AbstractHandle
    ):
        """Infer the return type of primitive `universe_getitem`."""
        return broaden(handle.element)


__operation_defaults__ = {
    "name": "universe_getitem",
    "registered_name": "universe_getitem",
    "mapping": P.universe_getitem,
    "python_implementation": pyimpl_universe_getitem,
}


__primitive_defaults__ = {
    "name": "universe_getitem",
    "registered_name": "universe_getitem",
    "type": "backend",
    "python_implementation": pyimpl_universe_getitem,
    "inferrer_constructor": _UniverseGetitemInferrer,
    "grad_transform": None,
}
