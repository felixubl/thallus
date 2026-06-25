"""Tests for snapshot-consistent memoization (M5)."""

from __future__ import annotations

from thallus import Engine, roles, stdlib


def test_shared_subexpression_evaluated_once():
    e = Engine()
    calls: list[int] = []

    def counted(ctx):
        calls.append(1)
        return True

    counted_op = e.define_primitive("counted_true", counted)
    leaf = e.application(counted_op)  # the shared, side-effecting subexpression
    ops = stdlib.install(e)
    parent = e.application(ops["and"], leaf, leaf)

    assert e.value(parent) is True
    assert len(calls) == 1  # memoized: computed once despite two references


def test_cache_returns_correct_value_repeatedly():
    e = Engine()
    ops = stdlib.install(e)
    app = e.application(ops["and"], e.literal(True), e.literal(True))
    assert e.value(app) is True
    assert e.value(app) is True


def test_historical_version_is_stable():
    e = Engine()
    leaf = e.node()
    t1 = e.store.set(leaf.id, roles.VALUE, 1)
    e.store.set(leaf.id, roles.VALUE, 2)
    assert e.value(leaf, as_of_tx=t1.tx_id) == 1
    assert e.value(leaf) == 2
    assert e.value(leaf, as_of_tx=t1.tx_id) == 1  # cached, and immutable


def test_current_view_reflects_new_writes():
    e = Engine()
    leaf = e.node()
    e.store.set(leaf.id, roles.VALUE, 1)
    assert e.value(leaf) == 1
    e.store.set(leaf.id, roles.VALUE, 2)
    assert e.value(leaf) == 2  # invalidated on change -> recomputed


def test_invalidation_is_selective():
    e = Engine()
    ops = stdlib.install(e)
    la = e.node().set_value(True)
    lb = e.node().set_value(True)
    app_a = e.application(ops["not"], la)
    app_b = e.application(ops["not"], lb)
    e.value(app_a)
    e.value(app_b)
    assert app_a.id in e._current and app_b.id in e._current

    la.set_value(False)  # change only A's input
    assert app_a.id not in e._current  # dependent of A invalidated
    assert app_b.id in e._current  # B untouched -> cached value reused
    assert e.value(app_a) is True


def test_invalidation_is_transitive():
    e = Engine()
    ops = stdlib.install(e)
    leaf = e.node().set_value(True)
    inner = e.application(ops["not"], leaf)
    outer = e.application(ops["not"], inner)
    assert e.value(outer) is True
    assert inner.id in e._current and outer.id in e._current

    leaf.set_value(False)
    assert inner.id not in e._current
    assert outer.id not in e._current  # propagated up the dependency chain
    assert e.value(outer) is False


def test_gather_reacts_to_indirect_dependencies():
    # gather over an entity depends on facts that are NOT its operands:
    # the entity's edges, the role nodes, and the value nodes it points to.
    e = Engine()
    ops = stdlib.install(e)
    phone = e.node().set(roles.LABEL, "phone")
    num = e.node().set_value("555")
    alice = e.node().set(phone, num)
    summary = e.application(ops["gather"], alice)
    assert e.value(summary) == {"phone": "555"}

    num.set_value("556")  # a value node Alice points to (not an operand of gather)
    assert e.value(summary) == {"phone": "556"}

    phone.set(roles.LABEL, "telephone")  # the role node's name
    assert e.value(summary) == {"telephone": "556"}

    email = e.node().set(roles.LABEL, "email")
    alice.set(email, e.literal("a@x.com"))  # a new attribute edge on the entity
    assert e.value(summary) == {"telephone": "556", "email": "a@x.com"}
