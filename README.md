# Thallus

A **computable knowledge graph**: a homoiconic, bitemporal, typed graph substrate
with a reactive evaluator. Data, types, and operations are all the same kind of
thing — a node. It is meant as the foundation for a "graph of one's life"; a
project/task manager, a CRM, an automation engine — each is just one program
written in it.

> A *thallus* is a body — lichen, fungus, alga — that is **not** differentiated
> into root, stem, and leaf: undifferentiated tissue where no part is privileged.
> That is the first principle here — *everything is a node; no privileged kinds.*

See [`DESIGN.md`](DESIGN.md) for the full rationale, the prior-art synthesis
(Lisp, RDF/Datomic, Unison, Smalltalk), and the build status.

## The model in three lines

- A **node** is `(identity, value)`. Entities are pure identity; literals carry a value.
- A **connection** is a **triple** `(subject, role, object)` — and the *role is itself a node*.
- A node's value is a literal, or computed by **applying** an operation to operand nodes.
  Operations and types are nodes too, so the graph can compute over its own logic.

Everything else — types, categories, user-defined and recursive operations,
queries — is ordinary graph content interpreted by one `apply` rule.

## Quick taste

```python
from thallus import Engine, stdlib, roles

e = Engine()
ops = stdlib.install(e)

# A reactive computation: total = a + (b * a)
a, b = e.literal(10), e.literal(3)
total = e.application(ops["add"], a, e.application(ops["mul"], b, a))
e.value(total)            # 40

a.set_value(20)           # edit one fact ...
e.value(total)            # 80  (only the affected nodes recompute, lazily)

# An entity is identity + relational edges; gather summarizes it.
name  = e.node().set(roles.LABEL, "name")    # roles are nodes with display names
phone = e.node().set(roles.LABEL, "phone")
alice = e.node().set(name, e.literal("Alice")).set(phone, e.literal("555"))
e.value(e.application(ops["gather"], alice))  # {"name": "Alice", "phone": "555"}
```

## What works today

Bitemporal fact store (valid-time + transaction-time, time-travel queries) ·
the `apply` kernel · types as validating operations (gradual, runtime) ·
user-defined and **recursive** operations (lazy `if`, arithmetic, frame-scoped
cycle detection) · duplicate **detection** via structural fingerprints
(nodes stay editable; nothing auto-merges) · **read-tracking reactivity**
(precise, transitive, lazy recompute) · **effects/IO** as recorded observations
(pure evaluation, freshness/TTL, graceful failure) · graph-native **queries**
(property nodes = reactive derived sets) · `merge` · edge direction · SQLite
persistence · a stable named schema · a Person/Task vertical slice.

Pure Python standard library, zero runtime dependencies.

## Develop

```bash
uv sync
uv run pytest        # the kernel test suite
uv run ruff check src/thallus tests examples
```

```python
from thallus import Engine, stdlib
# see examples/todo_app.py for a narrated end-to-end demo
```

Stack: Python 3.10+, standard library only for the kernel; `pytest` + `ruff` for
dev. This is the executable specification — clarity over speed — to be ported to
a performant runtime once the model is settled.

## Status & scope

This is a **prototype**: an executable specification meant to prove the model is
correct and expressive, not that it is fast or production-ready. Performance,
scale, multi-user, and an end-user authoring UX are deliberately deferred (see
the non-goals in [`DESIGN.md`](DESIGN.md)). A hierarchy-first "life-graph" app is
being built *on top of* this substrate, in a separate layer that is not part of
this package.

## License

Copyright © 2026 Felix Ubl. Released under the
[GNU General Public License v3.0 or later](LICENSE) (GPL-3.0-or-later) — a
copyleft license: software that builds on `thallus` and is distributed must in
turn be released under the GPL.
