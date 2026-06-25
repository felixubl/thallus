"""A worked example: a small people/tasks app built entirely in Thallus.

Run from the repo root:  python examples/todo_app.py

It writes a persistent graph to a temp file and narrates what the substrate does
that an ordinary database or library would not: derived reactive queries,
bitemporal time-travel, directed relationships, duplicate detect+merge, and
durability — all over the same graph of nodes.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from thallus import Engine, FactStore, stdlib  # noqa: E402


def section(title: str) -> None:
    print(f"\n== {title} ==")


def main() -> None:
    db_path = os.path.join(tempfile.mkdtemp(), "life.db")
    engine = Engine(FactStore(db_path))
    ops = stdlib.install(engine)

    # Vocabulary: roles are nodes; assigned_to is directed with a named inverse.
    name = engine.define_role("name")
    email = engine.define_role("email")
    title = engine.define_role("title")
    done = engine.define_role("done")
    assignee_of = engine.define_role("assignee_of")
    assigned_to = engine.define_role("assigned_to", inverse=assignee_of)

    def titles(ids) -> list[str]:
        return sorted(engine.store.one(i, title.id) for i in ids)

    # People are entities: identity plus relational edges.
    alice = engine.node().set(name, "Alice").set(email, "alice@example.com")
    bob = engine.node().set(name, "Bob").set(email, "bob@example.com")

    def task(text: str, who) -> object:
        return engine.node().set(title, text).set(assigned_to, who).set(done, False)

    write_report = task("Write report", alice)
    task("Fix bug", alice)
    task("Review PR", bob)

    section("Entity summary (gather over an entity's edges)")
    print("Alice:", engine.value(engine.application(ops["gather"], alice)))

    # A query is a node: "OpenTasks" = tasks whose `done` is false. The predicate
    # is a graph lambda; `over=[done]` narrows the scan to tasks.
    t = engine.node()
    is_open = engine.define_lambda(
        [t], engine.application(ops["not"], engine.application(ops["get"], t, done))
    )
    open_tasks = engine.define_property("OpenTasks", is_open, over=[done])
    open_query = engine.application(ops["members"], open_tasks)

    section("Derived, reactive query")
    print("Open tasks:", titles(engine.value(open_query)))
    before = engine.store.latest_tx()
    write_report.set(done, True)  # completing a task...
    print("After completing 'Write report':", titles(engine.value(open_query)))
    print("  (same query node — it recomputed itself)")

    section("Time travel (bitemporal)")
    print("Was 'Write report' done before?",
          engine.store.one(write_report.id, done.id, as_of_tx=before))
    print("Is it done now?            ", engine.store.one(write_report.id, done.id))

    section("Directed relationship (assigned_to / assignee_of)")
    alice_tasks = engine.application(ops["related"], alice, assignee_of)
    print("Alice's tasks:", titles(engine.value(alice_tasks)))

    section("Duplicate detection + merge")
    alice_dup = engine.node().set(name, "Alice").set(email, "alice@example.com")
    task("Pay invoice", alice_dup)  # accidentally assigned to the duplicate
    print("Duplicate detected?", engine.fingerprint(alice) == engine.fingerprint(alice_dup))
    engine.merge(alice, alice_dup)
    print("Alice's tasks after merge:", titles(engine.value(alice_tasks)))

    section("Persistence (reopen the file)")
    reopened = Engine(FactStore(db_path))
    reops = stdlib.install(reopened)
    members = reopened.value(reopened.application(reops["members"], open_tasks.id))
    print("Open tasks after reopen:",
          sorted(reopened.store.one(i, title.id) for i in members))

    print(f"\nGraph persisted at: {db_path}")


if __name__ == "__main__":
    main()
