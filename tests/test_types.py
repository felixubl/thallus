"""Tests for types as nodes (M3): a type is a validating operation."""

from __future__ import annotations

from thallus import Engine, roles, stdlib


def test_root_type_is_its_own_type():
    e = Engine()
    assert e.type_of(roles.ROOT_TYPE) == roles.ROOT_TYPE


def test_value_type_validation():
    e = Engine()
    t = stdlib.install_types(e)
    assert e.check(e.literal(True), t["Boolean"]) is True
    assert e.check(e.literal("hi"), t["Boolean"]) is False
    assert e.check(e.literal("hi"), t["Text"]) is True


def test_integer_excludes_bool():
    e = Engine()
    t = stdlib.install_types(e)
    assert e.check(e.literal(5), t["Integer"]) is True
    assert e.check(e.literal(True), t["Integer"]) is False  # bool is not Integer


def test_untyped_node_is_gradually_valid():
    e = Engine()
    stdlib.install_types(e)
    assert e.validate(e.literal(5)) is True  # no declared type -> valid


def test_validate_against_declared_type():
    e = Engine()
    t = stdlib.install_types(e)
    good = e.literal(5).set(roles.TYPE, t["Integer"])
    bad = e.literal("x").set(roles.TYPE, t["Integer"])
    assert e.validate(good) is True
    assert e.validate(bad) is False  # reported, not forbidden (freedom)


def test_structural_entity_type():
    e = Engine()
    t = stdlib.install_types(e)
    name_role = e.node().id
    email_role = e.node().id
    person = e.define_type("Person", t["structural"])
    e.store.put(person, roles.REQUIRES, name_role)
    e.store.put(person, roles.REQUIRES, email_role)

    alice = e.node().set(name_role, "Alice")
    assert e.check(alice, person) is False  # missing required email
    alice.set(email_role, "alice@example.com")
    assert e.check(alice, person) is True
