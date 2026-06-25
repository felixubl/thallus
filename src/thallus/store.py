"""The append-only, bitemporal fact store — the single source of truth.

Backed by SQLite: in-memory by default (``FactStore()``), or durable when given a
file path (``FactStore("graph.db")``). Facts are append-only and indexed by
``(subject, role)``, so reads are indexed lookups rather than full scans.

All state lives here as facts. Reads resolve a point in both time axes: a
``valid_at`` instant (default: now) and an ``as_of_tx`` transaction (default: the
latest). Resolution semantics: for each distinct object ever asserted for
``(subject, role)``, consider the facts visible at ``as_of_tx`` whose valid
interval contains ``valid_at``, take the one with the highest ``tx_id``, and
include the object iff that fact is a ``PUT`` — "last writer at this valid point
wins" on both axes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from .facts import Change, ChangeKind, Delete, Fact, Put
from .ids import Id, new_entity_id
from .values import Value

__all__ = ["FactStore", "Transaction", "AmbiguousValueError", "utcnow"]


class AmbiguousValueError(Exception):
    """Raised when a single value is requested but several are valid."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _encode_object(value: Value) -> tuple[str, str]:
    """Encode a fact object as (kind, text) for storage."""
    if isinstance(value, Id):
        return ("id", str(value))
    if isinstance(value, bool):  # before int: bool is a subclass of int
        return ("bool", "1" if value else "0")
    if isinstance(value, int):
        return ("int", str(value))
    if isinstance(value, float):
        return ("float", repr(value))
    if isinstance(value, str):
        return ("str", value)
    if isinstance(value, bytes):
        return ("bytes", value.hex())
    if value is None:
        return ("none", "")
    raise TypeError(f"not a storable value: {value!r}")


def _decode_object(kind: str, text: str) -> Value:
    if kind == "id":
        return _decode_id(text)
    if kind == "bool":
        return text == "1"
    if kind == "int":
        return int(text)
    if kind == "float":
        return float(text)
    if kind == "str":
        return text
    if kind == "bytes":
        return bytes.fromhex(text)
    return None


def _decode_id(text: str) -> Id:
    scheme, key = text.split(":", 1)
    return Id(scheme, key)


def _decode_dt(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


@dataclass(frozen=True, slots=True)
class Transaction:
    tx_id: int
    recorded_at: datetime
    facts: tuple[Fact, ...] = ()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id     TEXT NOT NULL,
    subject     TEXT NOT NULL,
    role        TEXT NOT NULL,
    object_kind TEXT NOT NULL,
    object      TEXT NOT NULL,
    valid_from  TEXT NOT NULL,
    valid_to    TEXT,
    kind        TEXT NOT NULL,
    tx_id       INTEGER NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subject_role ON facts(subject, role);
CREATE INDEX IF NOT EXISTS idx_role_object ON facts(role, object_kind, object);
CREATE INDEX IF NOT EXISTS idx_subject ON facts(subject);
"""


class FactStore:
    def __init__(self, path: str | None = None) -> None:
        # check_same_thread=False lets a threaded server (e.g. the web layer)
        # share one store; callers must serialize access themselves (a lock).
        self._conn = sqlite3.connect(path or ":memory:", check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        row = self._conn.execute("SELECT MAX(tx_id) FROM facts").fetchone()
        self._tx: int = row[0] or 0  # restore the transaction frontier on reopen
        self._listeners: list[Callable[[set[Id], set[Id]], None]] = []
        self.read_observer: Callable[[Id], None] | None = None

    def subscribe(self, listener: "Callable[[set[Id], set[Id]], None]") -> None:
        """Register a callback invoked after each transaction with the changed
        subjects and the changed roles."""
        self._listeners.append(listener)

    def transact(
        self, changes: Iterable[Change], *, recorded_at: datetime | None = None
    ) -> Transaction:
        """Append a batch of changes as one durable, immutable transaction."""
        changes = list(changes)
        self._tx += 1
        recorded = recorded_at or utcnow()
        created: list[Fact] = []
        rows = []
        for change in changes:
            fact_id = new_entity_id()
            valid_from = change.valid_from or recorded
            valid_to = change.valid_to
            kind = ChangeKind.PUT if isinstance(change, Put) else ChangeKind.DELETE
            obj_kind, obj_text = _encode_object(change.object)
            rows.append(
                (
                    str(fact_id),
                    str(change.subject),
                    str(change.role),
                    obj_kind,
                    obj_text,
                    valid_from.isoformat(),
                    valid_to.isoformat() if valid_to else None,
                    kind.value,
                    self._tx,
                    recorded.isoformat(),
                )
            )
            created.append(
                Fact(
                    fact_id=fact_id,
                    subject=change.subject,
                    role=change.role,
                    object=change.object,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    kind=kind,
                    tx_id=self._tx,
                    recorded_at=recorded,
                )
            )
        self._conn.executemany(
            "INSERT INTO facts(fact_id,subject,role,object_kind,object,"
            "valid_from,valid_to,kind,tx_id,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self._conn.commit()
        transaction = Transaction(self._tx, recorded, tuple(created))
        if self._listeners:
            changed_subjects = {change.subject for change in changes}
            changed_roles = {change.role for change in changes}
            for listener in self._listeners:
                listener(changed_subjects, changed_roles)
        return transaction

    def put(
        self,
        subject: Id,
        role: Id,
        object: Value,
        *,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        recorded_at: datetime | None = None,
    ) -> Transaction:
        return self.transact(
            [Put(subject, role, object, valid_from, valid_to)], recorded_at=recorded_at
        )

    def delete(
        self,
        subject: Id,
        role: Id,
        object: Value,
        *,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        recorded_at: datetime | None = None,
    ) -> Transaction:
        return self.transact(
            [Delete(subject, role, object, valid_from, valid_to)],
            recorded_at=recorded_at,
        )

    def set(self, subject: Id, role: Id, object: Value) -> Transaction:
        """Single-valued replace from now: retract current objects, assert the new one."""
        current = self.objects(subject, role)
        changes: list[Change] = [
            Delete(subject, role, o) for o in current if o != object
        ]
        changes.append(Put(subject, role, object))
        return self.transact(changes)

    def add(self, subject: Id, role: Id, object: Value) -> Transaction:
        """Multi-valued assert from now."""
        return self.put(subject, role, object)

    def _resolve(
        self,
        subject: Id,
        role: Id,
        valid_at: datetime | None,
        as_of_tx: int | None,
    ) -> dict[Value, Fact]:
        """Return the winning fact per object for ``(subject, role)`` at a time point."""
        if self.read_observer is not None:
            self.read_observer(subject)
        valid = valid_at or utcnow()
        sql = (
            "SELECT fact_id,object_kind,object,valid_from,valid_to,kind,tx_id,"
            "recorded_at FROM facts WHERE subject=? AND role=?"
        )
        params: list = [str(subject), str(role)]
        if as_of_tx is not None:
            sql += " AND tx_id<=?"
            params.append(as_of_tx)
        latest: dict[Value, Fact] = {}
        for row in self._conn.execute(sql, params):
            valid_from = datetime.fromisoformat(row[3])
            valid_to = _decode_dt(row[4])
            if not (valid_from <= valid and (valid_to is None or valid < valid_to)):
                continue
            obj = _decode_object(row[1], row[2])
            tx_id = row[6]
            seen = latest.get(obj)
            if seen is None or tx_id > seen.tx_id:
                latest[obj] = Fact(
                    fact_id=_decode_id(row[0]),
                    subject=subject,
                    role=role,
                    object=obj,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    kind=ChangeKind(row[5]),
                    tx_id=tx_id,
                    recorded_at=datetime.fromisoformat(row[7]),
                )
        return latest

    def objects(
        self,
        subject: Id,
        role: Id,
        *,
        valid_at: datetime | None = None,
        as_of_tx: int | None = None,
    ) -> set[Value]:
        return {
            obj
            for obj, fact in self._resolve(subject, role, valid_at, as_of_tx).items()
            if fact.kind is ChangeKind.PUT
        }

    def facts(
        self,
        subject: Id,
        role: Id,
        *,
        valid_at: datetime | None = None,
        as_of_tx: int | None = None,
    ) -> list[Fact]:
        """The winning (currently-valid) facts for ``(subject, role)``, with their ids."""
        return [
            fact
            for fact in self._resolve(subject, role, valid_at, as_of_tx).values()
            if fact.kind is ChangeKind.PUT
        ]

    def one(
        self,
        subject: Id,
        role: Id,
        *,
        valid_at: datetime | None = None,
        as_of_tx: int | None = None,
    ) -> Value | None:
        objs = self.objects(subject, role, valid_at=valid_at, as_of_tx=as_of_tx)
        if not objs:
            return None
        if len(objs) > 1:
            raise AmbiguousValueError(
                f"{len(objs)} values valid for ({subject}, {role})"
            )
        return next(iter(objs))

    def subjects(
        self,
        role: Id,
        object: Value,
        *,
        valid_at: datetime | None = None,
        as_of_tx: int | None = None,
    ) -> set[Id]:
        """Reverse lookup: subjects for which ``object`` is currently valid under ``role``."""
        obj_kind, obj_text = _encode_object(object)
        rows = self._conn.execute(
            "SELECT DISTINCT subject FROM facts WHERE role=? AND object_kind=? AND object=?",
            (str(role), obj_kind, obj_text),
        )
        candidates = {_decode_id(r[0]) for r in rows}
        return {
            s
            for s in candidates
            if object in self.objects(s, role, valid_at=valid_at, as_of_tx=as_of_tx)
        }

    def out_facts(
        self,
        subject: Id,
        *,
        valid_at: datetime | None = None,
        as_of_tx: int | None = None,
    ) -> list[Fact]:
        """All currently-valid outgoing facts of ``subject`` across every role."""
        rows = self._conn.execute(
            "SELECT DISTINCT role FROM facts WHERE subject=?", (str(subject),)
        )
        result: list[Fact] = []
        for (role_text,) in rows:
            result.extend(
                self.facts(
                    subject, _decode_id(role_text), valid_at=valid_at, as_of_tx=as_of_tx
                )
            )
        return result

    def all_facts(self) -> tuple[Fact, ...]:
        rows = self._conn.execute(
            "SELECT fact_id,subject,role,object_kind,object,valid_from,valid_to,"
            "kind,tx_id,recorded_at FROM facts ORDER BY seq"
        )
        return tuple(
            Fact(
                fact_id=_decode_id(r[0]),
                subject=_decode_id(r[1]),
                role=_decode_id(r[2]),
                object=_decode_object(r[3], r[4]),
                valid_from=datetime.fromisoformat(r[5]),
                valid_to=_decode_dt(r[6]),
                kind=ChangeKind(r[7]),
                tx_id=r[8],
                recorded_at=datetime.fromisoformat(r[9]),
            )
            for r in rows
        )

    def history(self, subject: Id) -> list[Fact]:
        """Every fact ever recorded about ``subject``, in transaction order.

        The raw bitemporal log — asserts and retractions alike, including ones no
        longer valid. Unlike ``out_facts`` this does not resolve to the currently
        winning set; it is the basis for time-travel and audit views.
        """
        rows = self._conn.execute(
            "SELECT fact_id,subject,role,object_kind,object,valid_from,valid_to,"
            "kind,tx_id,recorded_at FROM facts WHERE subject=? ORDER BY seq",
            (str(subject),),
        )
        return [
            Fact(
                fact_id=_decode_id(r[0]),
                subject=_decode_id(r[1]),
                role=_decode_id(r[2]),
                object=_decode_object(r[3], r[4]),
                valid_from=datetime.fromisoformat(r[5]),
                valid_to=_decode_dt(r[6]),
                kind=ChangeKind(r[7]),
                tx_id=r[8],
                recorded_at=datetime.fromisoformat(r[9]),
            )
            for r in rows
        ]

    def all_subjects(self) -> set[Id]:
        """Every node that is the subject of at least one fact."""
        return {
            _decode_id(r[0])
            for r in self._conn.execute("SELECT DISTINCT subject FROM facts")
        }

    def referents(
        self,
        object: Value,
        *,
        valid_at: datetime | None = None,
        as_of_tx: int | None = None,
    ) -> list[Fact]:
        """Currently-valid facts whose object is ``object`` (its incoming edges)."""
        obj_kind, obj_text = _encode_object(object)
        pairs = {
            (r[0], r[1])
            for r in self._conn.execute(
                "SELECT DISTINCT subject, role FROM facts "
                "WHERE object_kind=? AND object=?",
                (obj_kind, obj_text),
            )
        }
        result: list[Fact] = []
        for subject, role in pairs:
            for fact in self.facts(
                _decode_id(subject), _decode_id(role), valid_at=valid_at, as_of_tx=as_of_tx
            ):
                if fact.object == object:
                    result.append(fact)
        return result

    def subjects_with_role(self, role: Id) -> set[Id]:
        """Every subject that has at least one fact under ``role`` (indexed)."""
        return {
            _decode_id(r[0])
            for r in self._conn.execute(
                "SELECT DISTINCT subject FROM facts WHERE role=?", (str(role),)
            )
        }

    def latest_tx(self) -> int:
        """The most recent transaction id (the current transaction-time frontier)."""
        return self._tx
