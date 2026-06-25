"""Edge direction on roles: symmetric, inverse, and directed traversal."""

from __future__ import annotations

from thallus import Engine, stdlib


def test_symmetric_role_traverses_both_ways():
    e = Engine()
    ops = stdlib.install(e)
    married = e.define_role("married", symmetric=True)
    alice, bob = e.node(), e.node()
    e.store.put(alice.id, married.id, bob.id)  # asserted only one way

    assert e.value(e.application(ops["related"], alice, married)) == {bob.id}
    assert e.value(e.application(ops["related"], bob, married)) == {alice.id}


def test_directed_role_with_inverse():
    e = Engine()
    ops = stdlib.install(e)
    managed_by = e.define_role("managed_by")
    manages = e.define_role("manages", inverse=managed_by)
    alice, bob = e.node(), e.node()
    e.store.put(alice.id, manages.id, bob.id)  # alice manages bob

    assert e.value(e.application(ops["related"], alice, manages)) == {bob.id}
    assert e.value(e.application(ops["related"], bob, managed_by)) == {alice.id}
    # directed: bob does not "manage" anyone just by being managed
    assert e.value(e.application(ops["related"], bob, manages)) == set()


def test_related_reacts_to_reverse_edges():
    e = Engine()
    ops = stdlib.install(e)
    married = e.define_role("married", symmetric=True)
    alice, bob, carol = e.node(), e.node(), e.node()
    e.store.put(alice.id, married.id, bob.id)

    query = e.application(ops["related"], alice, married)
    assert e.value(query) == {bob.id}

    e.store.put(carol.id, married.id, alice.id)  # a NEW reverse edge to alice
    assert e.value(query) == {bob.id, carol.id}  # picked up via role dependency
