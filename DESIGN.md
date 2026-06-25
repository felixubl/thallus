# Thallus — A Computable Knowledge Graph

> **Thallus** — the Python implementation of this substrate. See §12.

## 0. What this is, in one paragraph

Thallus is a **homoiconic, bitemporal, typed graph substrate with an embedded
reactive evaluator**. In it, *data, types, and operations are all the same kind
of thing — a node*. A node carries a single value that is either a literal or
computed from its connected nodes. Because operations are themselves nodes, the
graph can store, compose, version, and reason about its own logic. Because facts
are timestamped and immutable, the graph remembers its whole history. Because
values recompute reactively, it behaves like a spreadsheet over an arbitrarily
large graph. It is not "a database" and not "a language" — it is both at once.
A life-management app, a project tracker, a CRM, an automation engine: each is
simply a *program written in Thallus*, not a separate product.

## 1. Goals and non-goals

**Goals.** A single uniform substrate where everything is a node; logic is data
(homoiconic) and user-definable; types are nodes that confer behavior; values are
reactive; the graph is temporal and queryable; and the model is *metacircular*
(it describes itself in its own terms).

**Non-goals for the prototype** (deliberately deferred, not forgotten):
performance and scale, distribution/multi-user, a visual/end-user authoring UX,
and static type soundness. The prototype exists to prove the *model is correct
and expressive*, not that it is fast or friendly. Those come after the kernel is
validated and ported.

## 2. Principles

These are the invariants every design decision is checked against.

- **Everything is a node.** No privileged kinds, no leaf-vs-node hierarchy. Any
  hierarchy is something a user *builds*, never something the substrate imposes.
- **Nodes are dumb; intelligence emerges from composition.** A node alone is
  just a value. Smart behavior is always an aggregation of dumb nodes.
- **A node has exactly one value**, either hardcoded (a literal) or computed.
  How it is computed is irrelevant to what it *is*.
- **Code is data (homoiconic).** Operations and types are ordinary nodes, so
  they can be created, swapped, queried, versioned, and even computed by other
  nodes.
- **Freedom over guardrails.** The substrate permits "wrong" or nonsensical
  graphs, the way a spreadsheet lets you write an absurd formula. Validation is
  *opt-in behavior conferred by a type*, never a restriction baked into the core.
- **Minimal kernel, maximal derivation.** The irreducible core is as small as
  possible; everything else is ordinary graph content expressed using the core.

## 3. Prior art, and why this is still worth building

No single existing system is Thallus, but four mature systems each solve one of its
dimensions, and one product chases an adjacent vision. The strategy is to *stand
on these*, not reinvent them.

- **Membrane** (membrane.io) — closest *product/vision*. Its pitch is literally
  "everything is a node and every node is typed," a unified graph over external
  APIs and your own data, with a durable runtime, timers, composable
  node-abstractions, and a write-ahead log that makes all history replayable.
  Differences: logic is written in TypeScript (**not** homoiconic — code is not
  graph data), types/operations are not user-composed nodes, and it is a closed
  hosted platform. Trial it; it may cover a large fraction of the use cases today.
- **TypeDB** — closest *data model*. A strongly-typed hypergraph with
  inheritance, polymorphism, a symbolic reasoner, and a type-theoretic query
  language. This is the "types are first-class and confer behavior" layer, built
  and decidable. Not homoiconic, not reactive.
- **Unison** — closest *code model*. Code is content-addressed (identified by the
  hash of its AST) and stored in a database, with an algebraic-effects system
  for IO. This is exactly the "operations are immutable, versioned data" layer.
- **Datomic / XTDB** — closest *temporal substrate*. Immutable bitemporal facts
  (triples + time), "database as a value," Datalog queries. This is the history
  layer done right.

The unfilled gap is the **combination**: a homoiconic, typed, temporal graph
where data, types, and operations are all one kind of node, with reactive
recomputation, aimed at end users. That synthesis does not exist as one system —
which is the reason to build, and also the reason to borrow heavily.

## 4. The kernel — the irreducible primitives

The art is making this set as small as possible. Everything in §5 is *derived*
from these.

1. **Node.** An identity plus one value slot. The only kind of thing.
2. **Fact (triple).** `(subject, role, object)` where the role is itself a node.
   Facts are immutable, append-only, and **timestamped** (bitemporal: a
   system *transaction time* and a user-assignable *valid time*). A fact is
   itself addressable (RDF-star style), so relationships can carry their own
   data and be talked about. This is the only kind of structure; it replaces ad
   hoc "connections."
3. **Apply — the one evaluation rule.** A node whose value is not a literal is
   computed by *applying* the value of its `operation`-role neighbor to the
   values of its `operand`/`parameter`-role neighbors. This is the single
   irreducible computational axiom (Lisp's `apply`). It cannot be pushed down
   into nodes without infinite regress.
4. **Primitive operations.** A small, finite set of host-implemented functions:
   arithmetic, equality/comparison, a conditional (`if`), list/dict
   construction, and graph traversal/query. The "machine instructions."
5. **Primitive roles.** A handful of built-in roles: `type`, `operation`,
   `operand`/`parameter`, `body`, `member`, `label`. Users define more (roles
   are nodes).
6. **Bootstrap nodes.** A root `Type` node that is its own type, and the
   `Operation` type. Self-reference accepted by fiat — the turtle-stopper,
   exactly as `type` is its own type in Python.

Two axioms are accepted as irreducible: **the `apply` rule** and **the
self-typed root**. Everything else is graph content.

## 5. The derived layer (ordinary graph content)

- **Literals.** A node whose value is a datum (number, string, bytes, a host
  function for primitive ops).
- **Composite / user-defined operations = lambdas.** A node typed `Operation`
  whose structure is a set of `parameter` nodes plus a `body` expression
  subgraph referencing those parameters. Applying it binds arguments to
  parameters and evaluates the body. This is the lambda calculus in graph form —
  proven minimal and complete. Code nodes are content-addressed (§8).
- **Types = validating operations.** A type is a node whose value is a predicate
  operation: given a node, return whether it is a valid instance (and optionally,
  behavior its instances inherit). Type-checking is therefore *function
  application*. This unifies "type," "operation," and "schema/class" into one
  concept.
- **Entities (Person, Task, Meeting).** A type whose validation specifies
  required roles. An instance is a node with those facts. A Person's "dict view"
  is a `gather` operation applied over the person's typed attribute edges — the
  leaves stay dumb literals; only the view is computed.
- **Categories / sets.** A node; membership is a `member`-role fact; queries are
  traversal primitive operations ("all members of *Phone Numbers*", "everyone
  `assigned_to` this task").
- **Effects.** An `Effectful` type carrying a *freshness policy* attribute (e.g.
  a "every 15 min" node). The policy governs the *reactive recompute layer*, not
  the operand list — this is where the earlier "interval node" belongs.

## 6. Evaluation and runtime model

- **Lazy.** Values resolve on demand.
- **Memoized + dependency-tracked.** A computed value is cached; when an upstream
  fact changes, dependents are invalidated and recomputed. This is incremental /
  reactive computation (cf. Salsa, Adapton, differential dataflow, UI signals).
  It is what makes "a spreadsheet over a huge graph" tractable.
- **Pure vs effectful split.** Pure nodes are deterministic functions of inputs
  and freely memoizable. Effectful nodes (API reads) are *not* — they carry a
  freshness policy and an explicit error/stale state, so "the value when the API
  is down" is a first-class outcome, not a crash.
- **Cycles and recursion.** A *data-dependency* cycle (a value that needs itself)
  is an error, detected during evaluation. *Intended recursion* via `apply` is
  allowed; the system is Turing-complete, so non-termination is expressible and
  not statically prevented — an accepted consequence of user-defined operations.
- **Temporal reads.** A value is a function of *(graph, time)*. You can evaluate
  "as of" any point, because facts are immutable and timestamped.

## 7. Type-system stance

Gradual, structural, runtime-checked, optionally enforced. Untyped nodes are
allowed (gradual). A type is defined by the shape/constraints it validates
(structural), expressed as a predicate operation. Because that predicate is an
arbitrary operation, **type-checking is runtime and static soundness is
deliberately given up** — the expressiveness-vs-decidability tradeoff resolved in
favor of expressiveness and end-user freedom. (Dependent types would give both
at a complexity cost incompatible with the goals.) Enforcement is opt-in:
validation reports problems; it does not forbid you from building a "wrong"
graph.

## 8. Identity, persistence, temporality

- **Identity.** Stable opaque IDs, never names. A name is just a `label` fact,
  and a node may have many.
- **All nodes are editable**, including operations. Identity is a stable entity
  id, *not* a content hash — because content-addressed identity and editability
  are mutually exclusive (editing would change the hash). This revises the
  original "content-addressed code" plan.
- **Duplicate detection, not auto-dedup.** Structural sameness is exposed
  on demand via `fingerprint(node)` — alpha-equivalent for operations (parameters
  compared by position), structural for data — and `find_duplicates()`. Nothing
  is silently merged; the user is informed. A `merge` operation (unify valid-time
  history, preserve transaction-time record) is planned but not yet built.
- **Literals** (numbers, strings, bools) are the irreducible leaves at the
  bottom; everything structural is nodes and triples.
- **Persistence.** An append-only fact log *is* the source of truth (Datomic /
  Membrane's write-ahead-log model): replayable, auditable, time-travelable.
  Currently in-memory; a JSON/SQLite-backed log is the next practical step.

## 9. Hard problems and open questions

Stated honestly; these are conceptual, and more code does not dissolve them.

- **Type expressiveness vs decidability.** Arbitrary-predicate types ⇒ runtime
  validation only. Accepted, but it means no static guarantees.
- **Effects + cache invalidation** is genuinely one of the hard problems. Needs a
  disciplined pure/effectful boundary (algebraic-effects style).
- **Recursion / termination.** Distinguishing controlled recursion from runaway
  loops and from data-dependency cycles.
- **Reactivity at scale.** Incremental recomputation over a large, effectful
  graph is active research.
- **Bitemporal modeling** adds real conceptual weight; worth it for a life graph,
  but not free.
- **Authoring UX — the final boss.** A homoiconic typed temporal graph that
  non-programmers can wield is undefeated territory (HyperCard, Max/MSP, Smalltalk
  were powerful and still niche). How users author operations — visual, textual,
  or both — is unresolved and may matter more than the kernel.
- **Security** of user-defined effectful operations (sandboxing, capabilities).

## 10. Implementation plan — Python kernel prototype first

**Why this path.** The chosen route is to validate the meta-model in Python
(fast iteration, lowest risk), then port the proven kernel to a performant
runtime. The prototype is the *executable specification and test oracle*, not the
production engine.

**Stack.** Python 3.12+, `uv`, `pytest`. Keep dependencies minimal — plain
`dataclasses` for the kernel; reach for `pydantic`/`polars`/`networkx` only if a
concrete need appears. Correctness and clarity over speed.

**Module layout (as built — flat, not nested).**

```
src/thallus/
  ids.py       # Id: entity / content-addressed / builtin identities
  values.py    # Value (fact object) + canonical serialization for hashing
  facts.py     # Fact (bitemporal triple), Put/Delete changes
  store.py     # append-only bitemporal fact store; as-of reads; change notifications
  roles.py     # built-in roles + bootstrap type ids
  node.py      # Node: a stateless handle over (store, id)
  eval.py      # Engine: apply kernel, types, lambdas, fingerprint, reactivity, effects
  stdlib.py    # logic / arithmetic / if / gather / collect + value & structural types
tests/         # one suite per concern (store, eval, types, lambda, recursion, …)
```

**Build status — milestones shipped + enrichment complete (Python, ~1900 LoC kernel,
84 tests in the kernel suite).**

- **M1 — done.** Bitemporal fact store with labeled triples and roles (both time
  axes from the first commit, so no temporal retrofit).
- **M2 — done.** The `apply` kernel; primitive operations; bootstrap nodes;
  logic/`gather`/`collect` as graph content.
- **M3 — done.** Types-as-nodes (validating operations); gradual runtime checking;
  self-typed root.
- **M4 — done.** Composite/recursive user operations (lambda: parameters + body).
  *Identity is editable, not content-addressed* (see §8); structural sameness is
  a separate `fingerprint`.
- **M5 — done.** Reactive layer via **read-tracking**: each value records the
  facts it read; a change invalidates exactly its readers (transitively),
  recompute is lazy/pull. Plus a sound pinned/historical memo cache.
- **M6 — folded into M1.** Bitemporality (assert/retract, valid-time + tx-time,
  as-of queries) was built from the start.
- **M7 — done.** Effects record observations as bitemporal facts (pure eval);
  `refresh` runs an effect, freshness/TTL via `is_stale`/`due_effects`, failures
  keep the last good value and record an error.
- **M8 — done.** The Person/Task vertical slice (§11) runs with zero kernel
  changes.
- **Also built:** lazy `if` + arithmetic/comparison, frame-scoped cycle detection
  with a depth bound (recursion), and `fingerprint`/`find_duplicates`.

**Enrichment — also shipped (no longer "remaining"):** SQLite persistence (durable,
indexed), graph-native queries (property nodes = reactive derived sets), the `merge`
operation, edge direction on roles (symmetric/inverse + traversal), and a stable
named schema. A hierarchy-first "life-graph" **app** is being built *on top of* this
substrate as a separate layer (not part of this package): the substrate stays a pure,
dependency-free library, and any application lives downstream of it.

**Port path.** With the kernel validated, a performant version (greenfield Rust,
or Clojure + XTDB to inherit homoiconicity and bitemporality) can reimplement the
*same kernel*, using this Python prototype as the conformance test suite.

## 11. The pressure test (vertical slice)

The success criterion for the kernel: this must be expressible with **zero kernel
changes**. If it needs a new primitive, the kernel is wrong.

- **Person** — nodes with `name`/`email`/`phone` attribute facts; a `gather`
  view producing a dict.
- **Task** — a boolean `done` value; an `assigned_to` fact to a Person; a
  `depends_on` fact to other Tasks.
- **Meeting** — a time, `attendee` facts to People.
- **Category** — a "Phone Numbers" node; phone leaves are `member`s; a query
  lists them.
- **Derived query** — "open tasks assigned to me," via traversal operations.
- **Effectful node** — a weather reading with a 15-minute freshness policy and a
  defined value-when-unavailable.

## 12. Naming

**Thallus** — a *thallus* is a plant/fungal/algal body that is **not** differentiated
into root, stem, and leaf: undifferentiated tissue in which no part is privileged.
That is the substrate's first principle — *everything is a node; no privileged kinds.*
The name is the package; the model is language-agnostic and could be reimplemented
elsewhere unchanged.
