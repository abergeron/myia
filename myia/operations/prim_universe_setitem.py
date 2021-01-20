"""Definitions for the primitive `universe_setitem`."""

from .. import lib, xtype
from ..lib import (
    ANYTHING,
    TYPE,
    VALUE,
    AbstractScalar,
    standard_prim,
    StandardInferrer,
)
from . import primitives as P
from myia.abstract.data import AbstractCast
from .macro_user_switch import getrepl


def pyimpl_universe_setitem(universe, handle, value):
    """Implement `universe_setitem`."""
    return universe.set(handle, value)


@standard_prim(P.universe_setitem)
class _UniverseSetitemInferrer(StandardInferrer):
    def __init__(self):
        super().__init__(P.universe_setitem, self.__infer)

    async def reroute(self, engine, outref, argrefs):
        if len(argrefs) != 3:
            # We let infer deal with this
            return None

        h_t = await argrefs[1].get()
        if not isinstance(h_t, lib.AbstractHandle):
            # We let infer deal with this
            return None

        if isinstance(h_t.element, AbstractCast):
            v_t = h_t.element.old
            g = outref.node.graph
            return engine.ref(
                g.apply(
                    P.universe_setitem,
                    argrefs[0].node,
                    g.apply(P.cast_handle, argrefs[1].node, v_t,),
                    argrefs[2].node,
                ),
                outref.context,
            )

        return None

    @staticmethod
    async def __infer(
        self,
        engine,
        universe: xtype.UniverseType,
        handle: lib.AbstractHandle,
        value,
    ):
        """Infer the return type of primitive `universe_setitem`."""
        engine.abstract_merge(handle.element, value)
        return AbstractScalar({VALUE: ANYTHING, TYPE: xtype.UniverseType})


__operation_defaults__ = {
    "name": "universe_setitem",
    "registered_name": "universe_setitem",
    "mapping": P.universe_setitem,
    "python_implementation": pyimpl_universe_setitem,
}


__primitive_defaults__ = {
    "name": "universe_setitem",
    "registered_name": "universe_setitem",
    "type": "backend",
    "python_implementation": pyimpl_universe_setitem,
    "inferrer_constructor": _UniverseSetitemInferrer,
    "grad_transform": None,
}
