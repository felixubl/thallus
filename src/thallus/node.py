"""A thin, stateless handle over a node id and its store.

``Node`` holds no state of its own — it is sugar for reading and writing facts
about one id. An ``Id`` stored as a fact's object is always a reference, so it is
lifted back into a ``Node``; scalars are returned as-is.
"""

from __future__ import annotations

from . import roles
from .ids import Id, new_entity_id
from .store import FactStore
from .values import Value

__all__ = ["Node"]


def _ref(role: "Node | Id") -> Id:
    return role.id if isinstance(role, Node) else role


def _store_value(value: "Node | Value") -> Value:
    return value.id if isinstance(value, Node) else value


class Node:
    def __init__(self, store: FactStore, id: Id) -> None:
        self._store = store
        self._id = id

    @classmethod
    def new(cls, store: FactStore) -> "Node":
        return cls(store, new_entity_id())

    @property
    def id(self) -> Id:
        return self._id

    def set(self, role: "Node | Id", value: "Node | Value") -> "Node":
        self._store.set(self._id, _ref(role), _store_value(value))
        return self

    def add(self, role: "Node | Id", value: "Node | Value") -> "Node":
        self._store.add(self._id, _ref(role), _store_value(value))
        return self

    def set_value(self, value: "Node | Value") -> "Node":
        """Make this node a literal with the given value."""
        return self.set(roles.VALUE, value)

    def apply(self, operation: "Node | Id", *operands: "Node | Id") -> "Node":
        """Make this node a computed application of ``operation`` over ``operands``.

        Operand order is preserved via an ``INDEX`` fact reifying each operand
        edge, so operands stay first-class edges while still being ordered.
        """
        self.set(roles.OPERATION, operation)
        for i, operand in enumerate(operands):
            tx = self._store.add(self._id, roles.OPERAND, _store_value(operand))
            self._store.put(tx.facts[0].fact_id, roles.INDEX, i)
        return self

    def get(self, role: "Node | Id") -> "Node | Value":
        return self._lift(self._store.one(self._id, _ref(role)))

    def get_all(self, role: "Node | Id") -> set["Node | Value"]:
        return {self._lift(v) for v in self._store.objects(self._id, _ref(role))}

    def _lift(self, value: Value) -> "Node | Value":
        return Node(self._store, value) if isinstance(value, Id) else value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Node) and other._id == self._id

    def __hash__(self) -> int:
        return hash(self._id)

    def __repr__(self) -> str:
        return f"Node({self._id})"
