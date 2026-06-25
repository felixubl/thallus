"""Duplicate detection via fingerprints (nodes stay editable; nothing auto-merges)."""

from __future__ import annotations

from thallus import Engine, stdlib


def test_lambdas_are_editable_distinct_identities():
    e = Engine()
    ops = stdlib.install(e)
    a1, b1 = e.node(), e.node()
    f1 = e.define_lambda([a1, b1], e.application(ops["and"], a1, b1))
    a2, b2 = e.node(), e.node()
    f2 = e.define_lambda([a2, b2], e.application(ops["and"], a2, b2))
    assert f1 != f2  # not auto-deduplicated; each is its own editable node


def test_fingerprint_detects_duplicate_lambdas():
    e = Engine()
    ops = stdlib.install(e)
    a1, b1 = e.node(), e.node()
    f1 = e.define_lambda([a1, b1], e.application(ops["and"], a1, b1))
    a2, b2 = e.node(), e.node()
    f2 = e.define_lambda([a2, b2], e.application(ops["and"], a2, b2))
    assert e.fingerprint(f1) == e.fingerprint(f2)  # same logic, flagged as dup


def test_fingerprint_respects_structure_and_parameter_order():
    e = Engine()
    ops = stdlib.install(e)
    a, b = e.node(), e.node()
    conj = e.define_lambda([a, b], e.application(ops["and"], a, b))
    disj = e.define_lambda([a, b], e.application(ops["or"], a, b))
    swapped = e.define_lambda([b, a], e.application(ops["and"], a, b))
    assert e.fingerprint(conj) != e.fingerprint(disj)
    assert e.fingerprint(conj) != e.fingerprint(swapped)


def test_fingerprint_detects_duplicate_data_values():
    e = Engine()
    a = e.node().set_value("555")
    b = e.node().set_value("555")
    c = e.node().set_value("999")
    assert a != b
    assert e.fingerprint(a) == e.fingerprint(b)
    assert e.fingerprint(a) != e.fingerprint(c)


def test_fingerprint_detects_duplicate_entities():
    e = Engine()
    name, email = e.node().id, e.node().id
    p1 = e.node().set(name, "Alice").set(email, "a@x.com")
    p2 = e.node().set(name, "Alice").set(email, "a@x.com")
    p3 = e.node().set(name, "Bob").set(email, "b@x.com")
    assert e.fingerprint(p1) == e.fingerprint(p2)
    assert e.fingerprint(p1) != e.fingerprint(p3)


def test_find_duplicates_groups_them():
    e = Engine()
    a = e.node().set_value("555")
    b = e.node().set_value("555")
    groups = e.find_duplicates()
    assert any({a.id, b.id} <= set(g) for g in groups)
