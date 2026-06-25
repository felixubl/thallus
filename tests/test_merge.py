"""Merging duplicate nodes (the resolution side of duplicate detection)."""

from __future__ import annotations

import pytest

from thallus import Engine, roles


def test_merge_repoints_references_and_migrates_attributes():
    e = Engine()
    knows = e.node()
    phone = e.node()
    a = e.node().set_value("Alice")
    b = e.node().set_value("Alice")
    b.set(phone, "555")  # b carries an attribute
    carol = e.node()
    e.store.put(carol.id, knows.id, b.id)  # carol -> b

    e.merge(a, b)

    assert e.store.one(carol.id, knows.id) == a.id  # reference repointed to a
    assert e.store.one(a.id, phone.id) == "555"  # b's attribute migrated to a
    assert e.store.out_facts(b.id) == []  # b retired (no outgoing facts)
    assert e.store.referents(b.id) == []  # nothing points to b anymore


def test_merge_preserves_pre_merge_belief():
    e = Engine()
    knows = e.node()
    a = e.node()
    b = e.node()
    carol = e.node()
    t = e.store.put(carol.id, knows.id, b.id)  # carol knew b at this transaction

    e.merge(a, b)

    assert e.store.one(carol.id, knows.id) == a.id  # now: carol knows a
    assert e.store.one(carol.id, knows.id, as_of_tx=t.tx_id) == b.id  # then: knew b


def test_merge_a_detected_duplicate():
    e = Engine()
    a = e.node().set_value("555")
    b = e.node().set_value("555")
    assert e.fingerprint(a) == e.fingerprint(b)  # detected as duplicates

    e.merge(a, b)
    assert e.store.one(a.id, roles.VALUE) == "555"
    assert e.store.out_facts(b.id) == []


def test_cannot_merge_into_self():
    e = Engine()
    a = e.node()
    with pytest.raises(ValueError):
        e.merge(a, a)
