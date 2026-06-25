"""Property nodes: derived (intensional) sets, and their reactivity."""

from __future__ import annotations

from thallus import Engine, Id, roles, stdlib


def _is_int_predicate(engine: Engine) -> Id:
    def fn(ctx):
        value = ctx.evaluate(ctx.operands[0])
        return isinstance(value, int) and not isinstance(value, bool)

    return engine.define_primitive("is_int", fn)


def test_is_member_checks_the_predicate():
    e = Engine()
    integers = e.define_property(
        "Integers", _is_int_predicate(e), over=[roles.VALUE]
    )
    assert e.is_member(integers, e.literal(5)) is True
    assert e.is_member(integers, e.literal("x")) is False


def test_is_member_reacts_to_value_changes():
    e = Engine()
    is_false = e.define_primitive("is_false", lambda ctx: ctx.evaluate(ctx.operands[0]) is False)
    falsey = e.define_property("Falsey", is_false, over=[roles.VALUE])
    n = e.literal(False)
    assert e.is_member(falsey, n) is True
    n.set_value(True)  # re-checking must see the new value, not a stale cache
    assert e.is_member(falsey, n) is False


def test_members_enumerates_derived_set():
    e = Engine()
    ops = stdlib.install(e)
    integers = e.define_property(
        "Integers", _is_int_predicate(e), over=[roles.VALUE]
    )
    x, z = e.literal(5), e.literal(7)
    e.literal("hello")  # not an integer
    members = e.application(ops["members"], integers)
    assert e.value(members) == {x.id, z.id}


def test_membership_reacts_to_value_changes_and_new_nodes():
    e = Engine()
    ops = stdlib.install(e)
    integers = e.define_property(
        "Integers", _is_int_predicate(e), over=[roles.VALUE]
    )
    x, z = e.literal(5), e.literal(7)
    members = e.application(ops["members"], integers)
    assert e.value(members) == {x.id, z.id}

    x.set_value("now a string")  # leaves the set (value change)
    assert e.value(members) == {z.id}

    w = e.literal(42)  # a brand-new node ENTERS the set (pattern reactivity)
    assert e.value(members) == {z.id, w.id}


def test_extensional_and_intensional_members_combine():
    e = Engine()
    ops = stdlib.install(e)
    integers = e.define_property(
        "Integers", _is_int_predicate(e), over=[roles.VALUE]
    )
    z = e.literal(7)  # intensional
    manual = e.literal("not-an-int")
    e.store.put(integers.id, roles.MEMBER, manual.id)  # extensional
    members = e.application(ops["members"], integers)
    assert e.value(members) == {z.id, manual.id}


def test_relational_property_as_a_graph_predicate():
    # "Adults" = age >= 18, written as a GRAPH operation (a lambda), not Python.
    # is_adult(p) = not(get(p, age) < 18)
    e = Engine()
    ops = stdlib.install(e)
    age = e.node().set(roles.LABEL, "age")
    p = e.node()
    body = e.application(
        ops["not"],
        e.application(ops["lt"], e.application(ops["get"], p, age), e.literal(18)),
    )
    is_adult = e.define_lambda([p], body, name="is_adult")
    adults = e.define_property("Adults", is_adult)

    alice = e.node().set(age, 30)  # age stored as a scalar object
    kid = e.node().set(age, 10)
    members = e.application(ops["members"], adults)

    assert e.value(members) == {alice.id}
    kid.set(age, 20)  # kid grows up -> enters the set
    assert e.value(members) == {alice.id, kid.id}


def test_narrowed_property_reacts_only_to_its_roles():
    # A property declared `over=[age]` is scanned over age-bearing nodes only and
    # is invalidated only by writes touching `age` — not unrelated writes.
    e = Engine()
    ops = stdlib.install(e)
    age = e.node().set(roles.LABEL, "age")
    phone = e.node().set(roles.LABEL, "phone")
    p = e.node()
    body = e.application(
        ops["not"],
        e.application(ops["lt"], e.application(ops["get"], p, age), e.literal(18)),
    )
    adults = e.define_property("Adults", e.define_lambda([p], body), over=[age])
    alice = e.node().set(age, 30)
    members = e.application(ops["members"], adults)
    assert e.value(members) == {alice.id}
    assert members.id in e._current

    e.node().set(phone, "555-1234")  # unrelated write -> must NOT invalidate
    assert members.id in e._current

    carol = e.node().set(age, 40)  # touches `age` -> must invalidate
    assert members.id not in e._current
    assert e.value(members) == {alice.id, carol.id}


def test_value_of_dereferences_a_node_reference():
    # "Big" = nodes whose value exceeds 10, accessed via value_of on the candidate.
    e = Engine()
    ops = stdlib.install(e)
    p = e.node()
    body = e.application(ops["lt"], e.literal(10), e.application(ops["value_of"], p))
    is_big = e.define_lambda([p], body)
    big = e.define_property("Big", is_big, over=[roles.VALUE])

    a, b = e.literal(20), e.literal(5)
    members = e.application(ops["members"], big)
    assert e.value(members) == {a.id}
    b.set_value(99)  # b becomes big -> enters the set
    assert e.value(members) == {a.id, b.id}
