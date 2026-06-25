"""Stable, durable schema identities (roles/properties/named nodes)."""

from __future__ import annotations

from thallus import Engine, FactStore, stdlib


def test_define_role_is_stable_and_idempotent():
    e = Engine()
    a = e.define_role("married", symmetric=True)
    b = e.define_role("married")  # re-running returns the same node
    assert a.id == b.id


def test_named_node_is_stable():
    e = Engine()
    assert e.named("inbox").id == e.named("inbox").id


def test_schema_survives_reopen(tmp_path):
    path = str(tmp_path / "g.db")

    e1 = Engine(FactStore(path))
    ops1 = stdlib.install(e1)
    done = e1.define_role("done")
    t = e1.node()
    is_open = e1.define_lambda(
        [t], e1.application(ops1["not"], e1.application(ops1["get"], t, done))
    )
    e1.define_property("OpenTasks", is_open, over=[done])
    task = e1.node().set(done, False)
    task_id = task.id

    # Fresh process/engine on the same file resolves the SAME schema nodes.
    e2 = Engine(FactStore(path))
    ops2 = stdlib.install(e2)
    open_tasks = e2.define_property("OpenTasks", None)  # idempotent: returns existing
    members = e2.value(e2.application(ops2["members"], open_tasks.id))
    assert task_id in members  # the persisted open task is found via stable schema
