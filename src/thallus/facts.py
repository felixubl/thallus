"""The atomic unit of the graph: an immutable, bitemporal fact.

A fact states ``(subject, role, object)`` over a *valid-time* interval, recorded
in a *transaction* (transaction-time). Facts are never mutated or removed; change
is expressed by asserting further facts, including ``DELETE`` facts that end the
validity of a triple over an interval. The two time axes are independent: valid
time is when something is true in the world, transaction time is when we recorded
believing it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from .ids import Id
from .values import Value

__all__ = ["ChangeKind", "Fact", "Put", "Delete", "Change"]


class ChangeKind(enum.Enum):
    PUT = "put"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class Fact:
    """A stored, immutable assertion. Addressable via ``fact_id`` (reification)."""

    fact_id: Id
    subject: Id
    role: Id
    object: Value
    valid_from: datetime
    valid_to: datetime | None  # None == open (forever)
    kind: ChangeKind
    tx_id: int
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class Put:
    """Assert that ``(subject, role, object)`` holds over a valid-time interval."""

    subject: Id
    role: Id
    object: Value
    valid_from: datetime | None = None  # None == transaction's recorded_at
    valid_to: datetime | None = None  # None == forever


@dataclass(frozen=True, slots=True)
class Delete:
    """End the validity of ``(subject, role, object)`` over a valid-time interval."""

    subject: Id
    role: Id
    object: Value
    valid_from: datetime | None = None
    valid_to: datetime | None = None


Change = Put | Delete
