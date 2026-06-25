"""The apply kernel — the single, irreducible evaluation rule.

A node's value is resolved as follows: if it is bound in the current environment
(a parameter), return that binding; if it has an ``OPERATION`` fact, its value is
that operation applied to its ordered ``OPERAND`` nodes; otherwise, if it has a
``VALUE`` fact, that literal is the value; otherwise it is undefined. This one
rule is the whole computational core.

Operations are content-addressed nodes of two kinds:

- *primitive* — a host function in the engine registry, keyed by operation id.
- *composite (lambda)* — a node with ordered ``PARAMETER`` nodes and a ``BODY``
  expression. Applying it binds parameters to argument values in a fresh
  environment and evaluates the body. This is the lambda calculus in graph form.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping

from . import roles
from .facts import Delete, Put
from .ids import Id, new_entity_id
from .node import Node
from .store import FactStore, utcnow
from .values import content_id_of, to_canonical

# This is a tree-walking interpreter, so deep recursion uses host stack frames.
# Raise the host limit well above our own depth bound so we report a clean error.
sys.setrecursionlimit(20_000)

#: Maximum composite-application nesting before bailing out (halting is undecidable).
MAX_RECURSION_DEPTH = 500

__all__ = [
    "Engine",
    "EvalContext",
    "EvalError",
    "CycleError",
    "ArityError",
    "RecursionLimitError",
    "UndefinedValueError",
    "Primitive",
]


class EvalError(Exception):
    """Base class for evaluation errors."""


class CycleError(EvalError):
    """Raised when a node's value depends, transitively, on itself (a data cycle)."""


class ArityError(EvalError):
    """Raised when an operation is applied to the wrong number of operands."""


class RecursionLimitError(EvalError):
    """Raised when composite-application nesting exceeds MAX_RECURSION_DEPTH."""


class UndefinedValueError(EvalError):
    """Raised when a node has neither an operation nor a literal value."""


Primitive = Callable[["EvalContext"], object]
Env = Mapping[Id, object]


@dataclass(slots=True)
class EvalContext:
    """What a primitive operation receives: its operands plus the means to read them."""

    engine: "Engine"
    store: FactStore
    valid_at: datetime | None
    as_of_tx: int | None
    operands: tuple[Id, ...]
    _visiting: frozenset[Id]
    _env: Env
    _current: bool
    _depth: int

    def evaluate(self, node: Id) -> object:
        return self.engine._eval(
            node,
            self.valid_at,
            self.as_of_tx,
            self._visiting,
            self._env,
            self._current,
            self._depth,
        )

    def values(self) -> list[object]:
        return [self.evaluate(operand) for operand in self.operands]

    def reference(self, operand: Id) -> Id:
        """The node an operand denotes, without dereferencing to a value.

        A by-reference parameter resolves to its bound node; any other operand is
        the node itself. Used by traversal operations that need identity, not value.
        """
        bound = self._env.get(operand)
        return bound if isinstance(bound, Id) else operand

    def label(self, node: Id) -> object:
        return self.store.one(
            node, roles.LABEL, valid_at=self.valid_at, as_of_tx=self.as_of_tx
        )

    def apply(
        self, operation: Id, operands: "list[Id]", *, by_reference: bool = False
    ) -> object:
        """Apply an operation to explicit operand nodes within this context.

        With ``by_reference``, a composite operation's parameters are bound to the
        operand *nodes themselves* (references), not their values — used for
        predicates that need to read a candidate's edges.
        """
        return self.engine.apply_operation(
            operation,
            operands,
            valid_at=self.valid_at,
            as_of_tx=self.as_of_tx,
            _visiting=self._visiting,
            _env=self._env,
            _current=self._current,
            _depth=self._depth,
            _by_reference=by_reference,
        )

    def all_subjects(self) -> set[Id]:
        """Every node in the graph, registering a scan (pattern) dependency.

        A computation that scans the whole graph depends not on specific nodes
        but on the *set of nodes existing* — so any later write may change its
        result. Recording the scan lets the engine invalidate it on any change.
        """
        self.engine._note_scan("*")
        return self.store.all_subjects()

    def scan_role(self, role: Id) -> set[Id]:
        """Nodes with a fact under ``role``, registering a dependency on that role.

        Narrower than ``all_subjects``: only writes touching ``role`` re-trigger
        the scanning computation.
        """
        self.engine._note_scan(str(role))
        return self.store.subjects_with_role(role)


class Engine:
    def __init__(self, store: FactStore | None = None) -> None:
        self.store = store if store is not None else FactStore()
        self._primitives: dict[Id, Primitive] = {}
        self._effects: dict[Id, Callable[[], object]] = {}
        self._cache: dict[tuple[Id, datetime, int], object] = {}  # pinned/historical
        self._current: dict[Id, object] = {}  # live view
        self._deps: dict[Id, set[Id]] = {}  # node -> subjects its value read
        self._readers: dict[Id, set[Id]] = {}  # subject -> nodes that read it
        self._dep_stack: list[set[Id]] = []  # active read-capture frames
        # Scan/pattern dependencies: a node that scanned the graph depends on the
        # set of nodes existing; "*" means "any write may change my result".
        self._pattern_deps: dict[Id, set[str]] = {}
        self._pattern_readers: dict[str, set[Id]] = {}
        self._pat_stack: list[set[str]] = []
        self._bootstrap()
        self.store.subscribe(self._invalidate)
        self.store.read_observer = self._note_read

    def clear_cache(self) -> None:
        self._cache.clear()
        self._current.clear()
        self._deps.clear()
        self._readers.clear()
        self._pattern_deps.clear()
        self._pattern_readers.clear()

    def _note_read(self, subject: Id) -> None:
        if self._dep_stack:
            self._dep_stack[-1].add(subject)

    def _note_scan(self, pattern: str) -> None:
        if self._pat_stack:
            self._pat_stack[-1].add(pattern)

    def _contribute(self, node: Id) -> None:
        # A node's dependencies flow up to whatever is currently computing, so a
        # value reused from cache still propagates its dependencies to its parent.
        if self._dep_stack:
            self._dep_stack[-1] |= self._deps.get(node, {node})
            self._pat_stack[-1] |= self._pattern_deps.get(node, set())

    def _invalidate(self, changed_subjects: set[Id], changed_roles: set[Id]) -> None:
        """Drop every live-view value affected by a transaction.

        Subject-level: direct readers of changed subjects (captured transitively,
        so no separate cascade is needed). Pattern-level: scan queries — universal
        scans ("*") on any write, and role-narrowed scans only when a role they
        range over is touched.
        """
        affected: set[Id] = set()
        for subject in changed_subjects:
            affected |= self._readers.get(subject, set())
        affected |= self._pattern_readers.get("*", set())
        for role in changed_roles:
            affected |= self._pattern_readers.get(str(role), set())
        for node in affected:
            self._current.pop(node, None)
            for subject in self._deps.pop(node, ()):
                readers = self._readers.get(subject)
                if readers is not None:
                    readers.discard(node)
            for pattern in self._pattern_deps.pop(node, ()):
                pattern_readers = self._pattern_readers.get(pattern)
                if pattern_readers is not None:
                    pattern_readers.discard(node)

    def _bootstrap(self) -> None:
        """Assert the self-describing kernel vocabulary (the turtle-stopper)."""
        self.store.set(roles.ROOT_TYPE, roles.TYPE, roles.ROOT_TYPE)
        self.store.set(roles.OPERATION_TYPE, roles.TYPE, roles.ROOT_TYPE)

    # -- construction helpers ------------------------------------------------

    def node(self) -> Node:
        return Node(self.store, new_entity_id())

    def literal(self, value: "Node | object") -> Node:
        return self.node().set_value(value)

    def application(self, operation: "Node | Id", *operands: "Node | Id") -> Node:
        return self.node().apply(operation, *operands)

    def define_primitive(self, name: str, fn: Primitive) -> Id:
        """Register a host-implemented operation as a content-addressed node."""
        op = content_id_of({"primitive": name})
        if op in self._primitives:
            return op
        self._primitives[op] = fn
        self.store.set(op, roles.TYPE, roles.OPERATION_TYPE)
        self.store.set(op, roles.LABEL, name)
        return op

    def define_lambda(
        self,
        params: "list[Node | Id]",
        body: "Node | Id",
        *,
        name: str | None = None,
        into: "Node | Id | None" = None,
    ) -> Id:
        """Define a composite operation: ordered parameters plus a body expression.

        Nodes are editable, so identity is a stable entity id (not the content
        hash). Structural sameness is exposed separately via ``fingerprint`` for
        on-demand duplicate *detection* — nothing is silently merged.

        Pass ``into`` (a pre-allocated node) to define a *recursive* operation:
        allocate the node, reference it inside ``body``, then define it here.
        """
        if into is not None:
            op = into.id if isinstance(into, Node) else into
        else:
            op = new_entity_id()
        param_ids = [p.id if isinstance(p, Node) else p for p in params]
        body_id = body.id if isinstance(body, Node) else body
        self.store.set(op, roles.TYPE, roles.OPERATION_TYPE)
        if name is not None:
            self.store.set(op, roles.LABEL, name)
        self.store.set(op, roles.BODY, body_id)
        for i, param in enumerate(param_ids):
            tx = self.store.add(op, roles.PARAMETER, param)
            self.store.put(tx.facts[0].fact_id, roles.INDEX, i)
        return op

    # -- duplicate detection -------------------------------------------------

    def fingerprint(
        self,
        node: "Node | Id",
        *,
        valid_at: datetime | None = None,
        as_of_tx: int | None = None,
    ) -> Id:
        """A content-addressed structural digest of any node.

        Two nodes with the same fingerprint are structural duplicates: same
        literal value, same set of attributes, or (for operations) the same
        logic up to parameter renaming. Detection only — identity is unchanged.
        """
        node_id = node.id if isinstance(node, Node) else node
        return content_id_of({"fp": self._fp(node_id, frozenset(), valid_at, as_of_tx)})

    def find_duplicates(
        self, *, valid_at: datetime | None = None, as_of_tx: int | None = None
    ) -> list[list[Id]]:
        """Group nodes that share a fingerprint (candidates for merging)."""
        subjects = {f.subject for f in self.store.all_facts()}
        groups: dict[Id, list[Id]] = {}
        for subject in subjects:
            fp = self.fingerprint(subject, valid_at=valid_at, as_of_tx=as_of_tx)
            groups.setdefault(fp, []).append(subject)
        return [sorted(g, key=str) for g in groups.values() if len(g) > 1]

    def _fp(
        self,
        node: Id,
        visiting: frozenset[Id],
        valid_at: datetime | None,
        as_of_tx: int | None,
    ) -> object:
        if node in visiting:
            return {"cycle": True}
        visiting = visiting | {node}
        body = self.store.one(node, roles.BODY, valid_at=valid_at, as_of_tx=as_of_tx)
        if isinstance(body, Id):
            params = self._ordered(node, roles.PARAMETER, valid_at, as_of_tx)
            binder = {p: i for i, p in enumerate(params)}
            return {
                "lambda": {
                    "arity": len(params),
                    "body": self._struct(body, binder, frozenset(), valid_at, as_of_tx),
                }
            }
        operation = self.store.one(
            node, roles.OPERATION, valid_at=valid_at, as_of_tx=as_of_tx
        )
        if isinstance(operation, Id):
            args = self._ordered(node, roles.OPERAND, valid_at, as_of_tx)
            return {
                "apply": {
                    "op": self._fp(operation, visiting, valid_at, as_of_tx),
                    "args": [self._fp(a, visiting, valid_at, as_of_tx) for a in args],
                }
            }
        pairs = [
            [
                str(fact.role),
                self._fp(fact.object, visiting, valid_at, as_of_tx)
                if isinstance(fact.object, Id)
                else {"lit": to_canonical(fact.object)},
            ]
            for fact in self.store.out_facts(node, valid_at=valid_at, as_of_tx=as_of_tx)
        ]
        pairs.sort(key=lambda p: json.dumps(p, sort_keys=True))
        return {"entity": pairs}

    def _struct(
        self,
        node: Id,
        binder: dict[Id, int],
        visiting: frozenset[Id],
        valid_at: datetime | None,
        as_of_tx: int | None,
    ) -> object:
        """Alpha-equivalent form of a code expression (parameters by position)."""
        if node in binder:
            return {"param": binder[node]}
        if node in visiting:
            return {"ref": str(node)}
        visiting = visiting | {node}
        operation = self.store.one(
            node, roles.OPERATION, valid_at=valid_at, as_of_tx=as_of_tx
        )
        if isinstance(operation, Id):
            args = self._ordered(node, roles.OPERAND, valid_at, as_of_tx)
            return {
                "apply": {
                    "op": str(operation),
                    "args": [
                        self._struct(a, binder, visiting, valid_at, as_of_tx)
                        for a in args
                    ],
                }
            }
        literal = self.store.one(
            node, roles.VALUE, valid_at=valid_at, as_of_tx=as_of_tx
        )
        if literal is not None:
            return {"lit": to_canonical(literal)}
        return {"ref": str(node)}  # external (data) reference: identity matters

    def define_type(self, name: str, validator: Id | None = None) -> Id:
        """Define a type as a content-addressed node, optionally with a validator op."""
        type_id = content_id_of({"type": name})
        if self.store.one(type_id, roles.LABEL) is not None:
            return type_id
        self.store.set(type_id, roles.TYPE, roles.ROOT_TYPE)
        self.store.set(type_id, roles.LABEL, name)
        if validator is not None:
            self.store.set(type_id, roles.VALIDATOR, validator)
        return type_id

    # -- evaluation ----------------------------------------------------------

    def value(
        self,
        node: "Node | Id",
        *,
        valid_at: datetime | None = None,
        as_of_tx: int | None = None,
    ) -> object:
        # Resolve both time axes once so the whole evaluation sees one consistent
        # snapshot, and so memo keys are concrete and immutable.
        node_id = node.id if isinstance(node, Node) else node
        current = valid_at is None and as_of_tx is None
        valid = valid_at if valid_at is not None else utcnow()
        tx = as_of_tx if as_of_tx is not None else self.store.latest_tx()
        return self._eval(node_id, valid, tx, frozenset(), {}, current, 0)

    def _eval(
        self,
        node: Id,
        valid_at: datetime,
        as_of_tx: int,
        visiting: frozenset[Id],
        env: Env,
        current: bool,
        depth: int,
    ) -> object:
        if node in env:
            return env[node]
        # Live view (current): node-keyed, invalidated when a read fact changes.
        # Pinned/historical: keyed by (node, valid_at, as_of_tx); sound forever.
        if not env:
            if current and node in self._current:
                self._contribute(node)
                return self._current[node]
            if not current and (node, valid_at, as_of_tx) in self._cache:
                return self._cache[(node, valid_at, as_of_tx)]
        if node in visiting:
            raise CycleError(f"node {node} depends on itself")

        track = current and not env
        if track:
            self._dep_stack.append({node})
            self._pat_stack.append(set())
        try:
            operation = self.store.one(
                node, roles.OPERATION, valid_at=valid_at, as_of_tx=as_of_tx
            )
            if isinstance(operation, Id):
                result = self.apply_operation(
                    operation,
                    self._ordered(node, roles.OPERAND, valid_at, as_of_tx),
                    valid_at=valid_at,
                    as_of_tx=as_of_tx,
                    _visiting=visiting | {node},
                    _env=env,
                    _current=current,
                    _depth=depth,
                )
            else:
                literal = self.store.one(
                    node, roles.VALUE, valid_at=valid_at, as_of_tx=as_of_tx
                )
                if literal is None:
                    raise UndefinedValueError(f"node {node} has no value")
                result = literal
        finally:
            if track:
                deps = self._dep_stack.pop()
                pats = self._pat_stack.pop()

        if track:
            self._deps[node] = deps
            for subject in deps:
                self._readers.setdefault(subject, set()).add(node)
            self._pattern_deps[node] = pats
            for pattern in pats:
                self._pattern_readers.setdefault(pattern, set()).add(node)
            self._current[node] = result
            self._contribute(node)
        elif not env:
            self._cache[(node, valid_at, as_of_tx)] = result
        return result

    def apply_operation(
        self,
        operation: Id,
        operands: "tuple[Id, ...] | list[Id]",
        *,
        valid_at: datetime | None = None,
        as_of_tx: int | None = None,
        _visiting: frozenset[Id] = frozenset(),
        _env: Env | None = None,
        _current: bool = False,
        _depth: int = 0,
        _by_reference: bool = False,
    ) -> object:
        """Apply an operation (primitive or composite) to explicit operand nodes."""
        env: Env = _env if _env is not None else {}
        operands = tuple(operands)

        fn = self._primitives.get(operation)
        if fn is not None:
            context = EvalContext(
                engine=self,
                store=self.store,
                valid_at=valid_at,
                as_of_tx=as_of_tx,
                operands=operands,
                _visiting=_visiting,
                _env=env,
                _current=_current,
                _depth=_depth,
            )
            return fn(context)

        body = self.store.one(
            operation, roles.BODY, valid_at=valid_at, as_of_tx=as_of_tx
        )
        if isinstance(body, Id):
            params = self._ordered(operation, roles.PARAMETER, valid_at, as_of_tx)
            if len(operands) != len(params):
                raise ArityError(
                    f"operation {operation} expects {len(params)} operands, "
                    f"got {len(operands)}"
                )
            if _depth >= MAX_RECURSION_DEPTH:
                raise RecursionLimitError(
                    f"recursion exceeded {MAX_RECURSION_DEPTH} frames"
                )
            # By value: arguments are evaluated in the caller's frame (so static
            # cycles in arguments are still caught). By reference: parameters are
            # bound to the operand nodes themselves (for predicates over a node).
            # Either way the body runs in a FRESH frame, so a function referencing
            # itself is recursion, not a data cycle.
            if _by_reference:
                args: list = list(operands)
            else:
                args = [
                    self._eval(o, valid_at, as_of_tx, _visiting, env, _current, _depth)
                    for o in operands
                ]
            new_env = dict(env)
            new_env.update(zip(params, args))
            return self._eval(
                body, valid_at, as_of_tx, frozenset(), new_env, _current, _depth + 1
            )

        raise UndefinedValueError(f"operation {operation} has no implementation")

    def _ordered(
        self,
        subject: Id,
        role: Id,
        valid_at: datetime | None,
        as_of_tx: int | None,
    ) -> tuple[Id, ...]:
        """Operand/parameter ids for ``role``, ordered by their INDEX reification."""
        facts = self.store.facts(subject, role, valid_at=valid_at, as_of_tx=as_of_tx)

        def index(fact) -> int:
            i = self.store.one(
                fact.fact_id, roles.INDEX, valid_at=valid_at, as_of_tx=as_of_tx
            )
            return i if isinstance(i, int) else 0

        return tuple(
            fact.object
            for fact in sorted(facts, key=index)
            if isinstance(fact.object, Id)
        )

    # -- types ---------------------------------------------------------------

    def type_of(
        self,
        node: "Node | Id",
        *,
        valid_at: datetime | None = None,
        as_of_tx: int | None = None,
    ) -> Id | None:
        node_id = node.id if isinstance(node, Node) else node
        result = self.store.one(
            node_id, roles.TYPE, valid_at=valid_at, as_of_tx=as_of_tx
        )
        return result if isinstance(result, Id) else None

    def check(
        self,
        node: "Node | Id",
        type_: "Node | Id",
        *,
        valid_at: datetime | None = None,
        as_of_tx: int | None = None,
    ) -> bool:
        """Return whether ``node`` is a valid instance of ``type_``.

        Type-checking is itself ``apply``: the type's validator operation is run
        with the candidate and the type as operands. A type with no validator
        accepts anything (gradual typing).
        """
        node_id = node.id if isinstance(node, Node) else node
        type_id = type_.id if isinstance(type_, Node) else type_
        # Resolve coordinates to a concrete snapshot (so the evaluation cache key
        # is sound); use the reactive cache for "now" so checks track changes.
        current = valid_at is None and as_of_tx is None
        valid = valid_at if valid_at is not None else utcnow()
        tx = as_of_tx if as_of_tx is not None else self.store.latest_tx()
        validator = self.store.one(type_id, roles.VALIDATOR, valid_at=valid, as_of_tx=tx)
        if not isinstance(validator, Id):
            return True
        return bool(
            self.apply_operation(
                validator, [node_id, type_id],
                valid_at=valid, as_of_tx=tx, _current=current,
            )
        )

    def validate(
        self,
        node: "Node | Id",
        *,
        valid_at: datetime | None = None,
        as_of_tx: int | None = None,
    ) -> bool:
        """Validate a node against its own declared type. Untyped nodes are valid."""
        type_id = self.type_of(node, valid_at=valid_at, as_of_tx=as_of_tx)
        if type_id is None:
            return True
        return self.check(node, type_id, valid_at=valid_at, as_of_tx=as_of_tx)

    # -- property nodes (derived sets) ---------------------------------------

    def named(self, name: str) -> Node:
        """A stable well-known node, identified by name (durable across restarts)."""
        return Node(self.store, content_id_of({"named": name}))

    def define_role(
        self,
        name: str,
        *,
        symmetric: bool = False,
        inverse: "Node | Id | None" = None,
    ) -> Node:
        """A role node, optionally symmetric or with a (mutually linked) inverse.

        Stable by name and idempotent, so schema survives restarts and re-running
        the definition returns the same node.
        """
        role_id = content_id_of({"role": name})
        if self.store.one(role_id, roles.LABEL) is not None:
            return Node(self.store, role_id)
        self.store.set(role_id, roles.LABEL, name)
        if symmetric:
            self.store.set(role_id, roles.SYMMETRIC, True)
        if inverse is not None:
            inverse_id = inverse.id if isinstance(inverse, Node) else inverse
            self.store.set(role_id, roles.INVERSE, inverse_id)
            self.store.set(inverse_id, roles.INVERSE, role_id)
        return Node(self.store, role_id)

    def define_property(
        self,
        name: str,
        predicate: "Node | Id",
        *,
        over: "list[Node | Id] | None" = None,
    ) -> Node:
        """A property node: a predicate whose members are derived, not asserted.

        Its membership = nodes satisfying ``predicate`` (intensional) plus any
        explicit ``MEMBER`` edges (extensional). Enumerate with the ``members``
        operation (reactive); check one node with ``is_member``.

        ``over`` lists the roles the predicate ranges over: members then scans
        only nodes having those roles (indexed) and reacts only to writes touching
        them. Omit it to scan the whole graph and react to any write.

        Stable by name and idempotent (define-once semantics), so the property
        survives restarts.
        """
        prop_id = content_id_of({"property": name})
        if self.store.one(prop_id, roles.LABEL) is not None:
            return Node(self.store, prop_id)
        predicate_id = predicate.id if isinstance(predicate, Node) else predicate
        self.store.set(prop_id, roles.LABEL, name)
        self.store.set(prop_id, roles.PREDICATE, predicate_id)
        self.store.set(prop_id, roles.TYPE, roles.PROPERTY_TYPE)
        for role in over or []:
            self.store.put(
                prop_id, roles.OVER, role.id if isinstance(role, Node) else role
            )
        return Node(self.store, prop_id)

    def merge(self, into: "Node | Id", duplicate: "Node | Id") -> Id:
        """Merge ``duplicate`` into ``into``: as if they were always one node.

        Re-attributes the duplicate's facts to ``into`` (keeping their valid-from,
        so the world-timeline unifies), repoints every incoming reference, and
        retires the duplicate — all in one transaction. History is preserved:
        querying ``as_of_tx`` before the merge still shows two separate nodes.
        """
        target = into.id if isinstance(into, Node) else into
        dup = duplicate.id if isinstance(duplicate, Node) else duplicate
        if target == dup:
            raise ValueError("cannot merge a node into itself")
        changes: list = []
        for fact in self.store.out_facts(dup):
            obj = target if fact.object == dup else fact.object
            changes.append(Put(target, fact.role, obj, valid_from=fact.valid_from))
            changes.append(Delete(dup, fact.role, fact.object))
        for fact in self.store.referents(dup):
            subject = target if fact.subject == dup else fact.subject
            changes.append(Put(subject, fact.role, target, valid_from=fact.valid_from))
            changes.append(Delete(fact.subject, fact.role, dup))
        self.store.transact(changes)
        return target

    def is_member(self, property: "Node | Id", node: "Node | Id") -> bool:
        prop = property.id if isinstance(property, Node) else property
        node_id = node.id if isinstance(node, Node) else node
        if node_id in self.store.objects(prop, roles.MEMBER):
            return True
        predicate = self.store.one(prop, roles.PREDICATE)
        if not isinstance(predicate, Id):
            return False
        try:
            return bool(self.apply_operation(
                predicate, [node_id],
                valid_at=utcnow(), as_of_tx=self.store.latest_tx(),
                _by_reference=True, _current=True))
        except Exception:  # a node the predicate can't judge is not a member
            return False

    # -- effects (IO) --------------------------------------------------------

    def define_effect(self, name: str, fn: Callable[[], object]) -> Id:
        """Register an effectful host function as a content-addressed node."""
        effect = content_id_of({"effect": name})
        if effect in self._effects:
            return effect
        self._effects[effect] = fn
        self.store.set(effect, roles.TYPE, roles.EFFECT_TYPE)
        self.store.set(effect, roles.LABEL, name)
        return effect

    def effect_node(self, effect: "Node | Id", freshness: int) -> Node:
        """Create a node whose value is observed from ``effect`` (refreshed on demand)."""
        node = self.node()
        effect_id = effect.id if isinstance(effect, Node) else effect
        self.store.put(node.id, roles.EFFECT, effect_id)
        self.store.put(node.id, roles.FRESHNESS, freshness)
        return node

    def refresh(
        self, node: "Node | Id", *, at: datetime | None = None
    ) -> tuple[str, object]:
        """Run an effectful node's effect and record the observation as a fact.

        The effect runs here, outside evaluation, so evaluation stays pure. On
        success the observed value is recorded; on failure an error is recorded
        and the last good value is left in place.
        """
        node_id = node.id if isinstance(node, Node) else node
        effect = self.store.one(node_id, roles.EFFECT)
        if not isinstance(effect, Id):
            raise ValueError(f"node {node_id} is not an effectful node")
        fn = self._effects.get(effect)
        if fn is None:
            raise UndefinedValueError(f"effect {effect} has no implementation")
        try:
            result = fn()
        except Exception as ex:  # record any failure as an observation
            self._record(node_id, roles.ERROR, str(ex), at)
            return ("error", str(ex))
        self._record(node_id, roles.VALUE, result, at)
        return ("ok", result)

    def _record(self, node: Id, role: Id, value: object, at: datetime | None) -> None:
        """Replace ``(node, role)`` with ``value``, valid from ``at`` (or now)."""
        if at is None:
            self.store.set(node, role, value)
            return
        current = self.store.objects(node, role, valid_at=at)
        changes: list = [Delete(node, role, o, valid_from=at) for o in current if o != value]
        changes.append(Put(node, role, value, valid_from=at))
        self.store.transact(changes, recorded_at=at)

    def is_stale(self, node: "Node | Id", *, now: datetime | None = None) -> bool:
        """Whether an effectful node's latest observation is older than its freshness."""
        node_id = node.id if isinstance(node, Node) else node
        now = now if now is not None else utcnow()
        observations = self.store.facts(node_id, roles.VALUE, valid_at=now)
        if not observations:
            return True
        last = max(fact.valid_from for fact in observations)
        freshness = self.store.one(node_id, roles.FRESHNESS, valid_at=now)
        if not isinstance(freshness, (int, float)):
            return False
        return (now - last).total_seconds() >= freshness

    def due_effects(self, *, now: datetime | None = None) -> list[Id]:
        """Effectful nodes whose latest observation is stale (need refreshing)."""
        now = now if now is not None else utcnow()
        nodes = {f.subject for f in self.store.all_facts() if f.role == roles.EFFECT}
        return [n for n in nodes if self.is_stale(n, now=now)]
