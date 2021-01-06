"""Definitions for the primitive `proxy_handle`."""

from .. import lib, xtype
from ..lib import standard_prim
from . import primitives as P

from myia.abstract.data import AbstractCast


@standard_prim(P.cast_handle)
async def infer_cast_handle(
    self, engine, h: lib.AbstractHandle, t: lib.AbstractType
):
    """Infer the return type of primitive `cast_handle`."""
    # XXX: possibly add some more checks for the types here.
    return lib.AbstractHandle(t.element)


__operation_defaults__ = {
    "name": "cast_handle",
    "registered_name": "cast_handle",
    "mapping": P.cast_handle,
    "python_implementation": None,
}


__primitive_defaults__ = {
    "name": "cast_handle",
    "registered_name": "cast_handle",
    "type": "inference",
    "python_implementation": None,
    "inferrer_constructor": infer_cast_handle,
    "grad_transform": None,
}
