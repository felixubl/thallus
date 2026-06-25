"""Node identity.

Every node is referenced by an ``Id`` behind a single abstraction, so the
identity *strategy* can vary without changing references. Two schemes exist from
the start:

- ``ent`` — opaque, stable identity for mutable data nodes (a Person whose phone
  number changes is still the same node).
- ``cas`` — content-addressed identity for immutable code/structure (an operation
  is identified by the hash of its definition; editing it yields a new node).
- ``builtin`` — stable, human-readable identity for kernel vocabulary (roles,
  bootstrap types).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

__all__ = ["Id", "new_entity_id", "builtin_id", "content_id"]


@dataclass(frozen=True, slots=True)
class Id:
    scheme: str
    key: str

    def __str__(self) -> str:
        return f"{self.scheme}:{self.key}"


def new_entity_id() -> Id:
    """Return a fresh opaque identity for a mutable data node."""
    return Id("ent", uuid.uuid4().hex)


def builtin_id(name: str) -> Id:
    """Return the stable identity of a kernel vocabulary node."""
    return Id("builtin", name)


def content_id(data: bytes) -> Id:
    """Return a content-addressed identity for the given canonical bytes."""
    return Id("cas", hashlib.sha256(data).hexdigest())
