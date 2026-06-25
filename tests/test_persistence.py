"""Durability: a graph survives being closed and reopened from disk."""

from __future__ import annotations

from thallus import Engine, FactStore, new_entity_id, roles, stdlib


def test_facts_persist_across_reopen(tmp_path):
    path = str(tmp_path / "graph.db")
    subject = new_entity_id()

    store = FactStore(path)
    store.put(subject, roles.VALUE, 42)
    store.add(subject, roles.LABEL, "answer")
    last_tx = store.latest_tx()

    reopened = FactStore(path)  # a fresh handle on the same file
    assert reopened.one(subject, roles.VALUE) == 42
    assert reopened.objects(subject, roles.LABEL) == {"answer"}
    assert reopened.latest_tx() == last_tx  # transaction frontier restored


def test_bitemporal_history_persists(tmp_path):
    path = str(tmp_path / "graph.db")
    subject = new_entity_id()

    store = FactStore(path)
    t1 = store.set(subject, roles.VALUE, "old")
    store.set(subject, roles.VALUE, "new")

    reopened = FactStore(path)
    assert reopened.one(subject, roles.VALUE) == "new"
    assert reopened.one(subject, roles.VALUE, as_of_tx=t1.tx_id) == "old"


def test_computed_graph_persists_and_recomputes(tmp_path):
    path = str(tmp_path / "graph.db")

    engine = Engine(FactStore(path))
    ops = stdlib.install(engine)
    a, b = engine.literal(10), engine.literal(3)
    total = engine.application(ops["add"], a, b)
    assert engine.value(total) == 13
    total_id = total.id

    # Reopen: data + structure come from disk; host primitives are re-registered
    # (their implementations are code, not data), and the same names hash to the
    # same operation nodes, so the persisted application still resolves.
    reopened = Engine(FactStore(path))
    stdlib.install(reopened)
    assert reopened.value(total_id) == 13
