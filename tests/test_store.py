"""Tests for the bitemporal fact store kernel (M1)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from thallus import (
    AmbiguousValueError,
    Delete,
    FactStore,
    Node,
    Put,
    content_id_of,
    new_entity_id,
    roles,
)


def dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def test_put_and_read_current():
    s = FactStore()
    alice = new_entity_id()
    s.put(alice, roles.LABEL, "Alice")
    assert s.objects(alice, roles.LABEL) == {"Alice"}
    assert s.one(alice, roles.LABEL) == "Alice"


def test_multi_valued_role():
    s = FactStore()
    alice = new_entity_id()
    phone = new_entity_id()
    s.add(alice, phone, "555-1")
    s.add(alice, phone, "555-2")
    assert s.objects(alice, phone) == {"555-1", "555-2"}
    with pytest.raises(AmbiguousValueError):
        s.one(alice, phone)


def test_single_valued_replace_and_transaction_time_travel():
    s = FactStore()
    alice = new_entity_id()
    age = new_entity_id()
    t1 = s.set(alice, age, 30)
    s.set(alice, age, 31)
    assert s.one(alice, age) == 31
    assert s.one(alice, age, as_of_tx=t1.tx_id) == 30


def test_valid_time_travel():
    s = FactStore()
    alice = new_entity_id()
    addr = new_entity_id()
    s.put(alice, addr, "A", valid_from=dt(2020))
    s.transact(
        [
            Delete(alice, addr, "A", valid_from=dt(2023)),
            Put(alice, addr, "B", valid_from=dt(2023)),
        ]
    )
    assert s.objects(alice, addr, valid_at=dt(2021)) == {"A"}
    assert s.objects(alice, addr, valid_at=dt(2024)) == {"B"}


def test_bitemporal_axes_are_independent():
    s = FactStore()
    alice = new_entity_id()
    addr = new_entity_id()
    t1 = s.put(alice, addr, "A", valid_from=dt(2020))
    t2 = s.transact(
        [
            Delete(alice, addr, "A", valid_from=dt(2023)),
            Put(alice, addr, "B", valid_from=dt(2023)),
        ]
    )
    # In 2024, what did we believe before vs after recording the move?
    assert s.objects(alice, addr, valid_at=dt(2024), as_of_tx=t1.tx_id) == {"A"}
    assert s.objects(alice, addr, valid_at=dt(2024), as_of_tx=t2.tx_id) == {"B"}


def test_delete_is_not_destructive():
    s = FactStore()
    cat = new_entity_id()
    phone = new_entity_id()
    t1 = s.put(cat, roles.MEMBER, phone)
    s.delete(cat, roles.MEMBER, phone)
    assert s.objects(cat, roles.MEMBER) == set()
    assert s.objects(cat, roles.MEMBER, as_of_tx=t1.tx_id) == {phone}


def test_reverse_lookup():
    s = FactStore()
    cat = new_entity_id()
    x = new_entity_id()
    y = new_entity_id()
    s.put(cat, roles.MEMBER, x)
    s.put(cat, roles.MEMBER, y)
    assert s.subjects(roles.MEMBER, x) == {cat}


def test_content_id_is_deterministic_and_structural():
    arg = new_entity_id()
    a = content_id_of({"op": "and", "args": [arg]})
    b = content_id_of({"args": [arg], "op": "and"})  # key order irrelevant
    c = content_id_of({"op": "or", "args": [arg]})
    assert a == b
    assert a.scheme == "cas"
    assert a != c


def test_node_handle_round_trips_references():
    s = FactStore()
    alice = Node.new(s)
    phone = Node.new(s)
    knows = new_entity_id()
    alice.set(roles.LABEL, "Alice")
    alice.add(knows, phone)
    assert alice.get(roles.LABEL) == "Alice"
    assert alice.get_all(knows) == {phone}
