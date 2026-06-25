"""Tests for the apply kernel and the standard operations (M2)."""

from __future__ import annotations

import pytest

from thallus import CycleError, Engine, UndefinedValueError, roles, stdlib


def test_literal_value():
    e = Engine()
    assert e.value(e.literal(5)) == 5
    assert e.value(e.literal(False)) is False


@pytest.mark.parametrize(
    ("op", "a", "b", "expected"),
    [
        ("and", True, True, True),
        ("and", True, False, False),
        ("or", False, False, False),
        ("or", True, False, True),
    ],
)
def test_logic_over_literals(op, a, b, expected):
    e = Engine()
    ops = stdlib.install(e)
    app = e.application(ops[op], e.literal(a), e.literal(b))
    assert e.value(app) is expected


def test_not():
    e = Engine()
    ops = stdlib.install(e)
    leaf = e.literal(True)
    app = e.application(ops["not"], leaf)
    assert e.value(app) is False


def test_operation_is_swappable_data():
    e = Engine()
    ops = stdlib.install(e)
    app = e.application(ops["and"], e.literal(True), e.literal(False))
    assert e.value(app) is False
    app.set(roles.OPERATION, ops["or"])  # swap the logic by editing a fact
    assert e.value(app) is True


def test_gather_summarizes_entity_attributes():
    e = Engine()
    ops = stdlib.install(e)
    name = e.node().set(roles.LABEL, "name")  # role nodes (the attribute kinds)
    phone = e.node().set(roles.LABEL, "phone")
    alice = e.node()
    alice.set(name, e.literal("Alice"))  # (alice, name, "Alice") edges
    alice.set(phone, e.literal("555-1234"))
    summary = e.application(ops["gather"], alice)
    assert e.value(summary) == {"name": "Alice", "phone": "555-1234"}


def test_collect_builds_list():
    e = Engine()
    ops = stdlib.install(e)
    cat = e.application(ops["collect"], e.literal("555-1"), e.literal("555-2"))
    assert set(e.value(cat)) == {"555-1", "555-2"}


def test_cycle_detection():
    e = Engine()
    ops = stdlib.install(e)
    x = e.node()
    x.apply(ops["not"], x)  # x = not x
    with pytest.raises(CycleError):
        e.value(x)


def test_undefined_value():
    e = Engine()
    with pytest.raises(UndefinedValueError):
        e.value(e.node())


def test_operations_are_content_addressed():
    e1, e2 = Engine(), Engine()
    and1 = e1.define_primitive("and", lambda ctx: all(ctx.values()))
    and2 = e2.define_primitive("and", lambda ctx: all(ctx.values()))
    or1 = e1.define_primitive("or", lambda ctx: any(ctx.values()))
    assert and1 == and2  # same definition -> same identity
    assert and1.scheme == "cas"
    assert and1 != or1


def test_evaluation_is_bitemporal():
    e = Engine()
    ops = stdlib.install(e)
    leaf = e.node()
    app = e.application(ops["not"], leaf)  # structure created first
    t_true = e.store.set(leaf.id, roles.VALUE, True)
    e.store.set(leaf.id, roles.VALUE, False)
    assert e.value(app, as_of_tx=t_true.tx_id) is False  # not True, as believed then
    assert e.value(app) is True  # not False, as believed now
