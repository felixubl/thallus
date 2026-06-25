"""Fact objects and their canonical serialization.

A fact's object is a ``Value``: either a reference to another node (an ``Id``,
which makes the fact an edge) or a literal scalar (which makes it an attribute).
Canonicalization gives a deterministic byte form used for content-addressing.
"""

from __future__ import annotations

import json

from .ids import Id, content_id

__all__ = ["Value", "to_canonical", "content_id_of"]

Value = Id | str | int | float | bool | bytes | None


def to_canonical(value: object) -> object:
    """Return a deterministic JSON-able form of ``value`` (and nested structures)."""
    if isinstance(value, Id):
        return {"$id": str(value)}
    if isinstance(value, bytes):
        return {"$bytes": value.hex()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [to_canonical(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_canonical(v) for k, v in sorted(value.items())}
    raise TypeError(f"not a canonicalizable value: {value!r}")


def content_id_of(structure: object) -> Id:
    """Return the content-addressed id of an arbitrary canonicalizable structure."""
    data = json.dumps(
        to_canonical(structure), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return content_id(data)
