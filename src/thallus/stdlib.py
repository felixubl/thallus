"""Standard library: the first operations, expressed on top of the apply kernel.

Each is a content-addressed primitive. Logic operations are variadic over their
operands; ``gather`` and ``collect`` aggregate them. Ordering of operands is not
yet significant (M2 targets order-independent operations); ordered operands
arrive with the lambda layer.
"""

from __future__ import annotations

import operator

from . import roles
from .eval import Engine, EvalContext
from .ids import Id

__all__ = ["install", "install_types"]


_STRUCTURAL_ROLES = frozenset(
    {
        roles.VALUE,
        roles.TYPE,
        roles.OPERATION,
        roles.OPERAND,
        roles.PARAMETER,
        roles.BODY,
        roles.INDEX,
        roles.VALIDATOR,
        roles.REQUIRES,
        roles.EFFECT,
        roles.FRESHNESS,
        roles.ERROR,
    }
)


def _single(ctx: EvalContext) -> object:
    (operand,) = ctx.operands
    return ctx.evaluate(operand)


def _gather(ctx: EvalContext) -> dict[object, object]:
    """Summarize an entity: its outgoing relational edges, keyed by role.

    The single operand is the entity. Each non-structural outgoing edge becomes
    a dict entry keyed by the role node's label (its name), valued by the
    evaluated object. The leaf value nodes carry no label — categorization lives
    on the edge's role, which is itself a node.
    """
    (entity,) = ctx.operands
    summary: dict[object, object] = {}
    for fact in ctx.store.out_facts(
        entity, valid_at=ctx.valid_at, as_of_tx=ctx.as_of_tx
    ):
        if fact.role in _STRUCTURAL_ROLES:
            continue
        name = ctx.label(fact.role)
        key = name if name is not None else str(fact.role)
        summary[key] = (
            ctx.evaluate(fact.object)
            if isinstance(fact.object, Id)
            else fact.object
        )
    return summary


def _if(ctx: EvalContext) -> object:
    """Lazy conditional: evaluate the condition, then only the taken branch."""
    cond, then_branch, else_branch = ctx.operands
    return ctx.evaluate(then_branch) if ctx.evaluate(cond) else ctx.evaluate(else_branch)


def _binary(op):
    def fn(ctx: EvalContext) -> object:
        left, right = ctx.values()
        return op(left, right)

    return fn


def _get(ctx: EvalContext) -> object:
    """Follow an edge: the object of ``(node, role)``."""
    node = ctx.reference(ctx.operands[0])
    role = ctx.reference(ctx.operands[1])
    return ctx.store.one(node, role, valid_at=ctx.valid_at, as_of_tx=ctx.as_of_tx)


def _value_of(ctx: EvalContext) -> object:
    """Dereference a node reference to its value."""
    return ctx.evaluate(ctx.reference(ctx.operands[0]))


def _related(ctx: EvalContext) -> set:
    """Nodes related to a node via a role, honoring the role's direction.

    Forward (the role's edges) always; plus the reverse direction when the role
    is symmetric or has an inverse. Reverse lookups depend on the role, so new
    edges re-trigger the query.
    """
    node = ctx.reference(ctx.operands[0])
    role = ctx.reference(ctx.operands[1])
    va, tx = ctx.valid_at, ctx.as_of_tx
    result = set(ctx.store.objects(node, role, valid_at=va, as_of_tx=tx))
    if ctx.store.one(role, roles.SYMMETRIC, valid_at=va, as_of_tx=tx):
        ctx.engine._note_scan(str(role))
        result |= ctx.store.subjects(role, node, valid_at=va, as_of_tx=tx)
    inverse = ctx.store.one(role, roles.INVERSE, valid_at=va, as_of_tx=tx)
    if isinstance(inverse, Id):
        ctx.engine._note_scan(str(inverse))
        result |= ctx.store.subjects(inverse, node, valid_at=va, as_of_tx=tx)
    return result


def _members(ctx: EvalContext) -> set:
    """The members of a property node: explicit members plus those the predicate accepts.

    Scans every node and keeps those the predicate accepts; a node the predicate
    can't be evaluated against is simply not a member. Reactive: the scan
    registers a pattern dependency, so newly-added nodes re-trigger it.
    """
    (prop,) = ctx.operands
    predicate = ctx.store.one(
        prop, roles.PREDICATE, valid_at=ctx.valid_at, as_of_tx=ctx.as_of_tx
    )
    found = set(
        ctx.store.objects(prop, roles.MEMBER, valid_at=ctx.valid_at, as_of_tx=ctx.as_of_tx)
    )
    over = ctx.store.objects(
        prop, roles.OVER, valid_at=ctx.valid_at, as_of_tx=ctx.as_of_tx
    )
    if over:  # narrowed: only nodes with the declared roles, reacting to those roles
        candidates: set = set()
        for role in over:
            if isinstance(role, Id):
                candidates |= ctx.scan_role(role)
    else:  # whole-graph scan, reacting to any write
        candidates = ctx.all_subjects()
    if isinstance(predicate, Id):
        for candidate in candidates:
            try:
                if ctx.apply(predicate, [candidate], by_reference=True):
                    found.add(candidate)
            except Exception:  # a node the predicate can't judge is not a member
                pass
    return found


def install(engine: Engine) -> dict[str, Id]:
    """Register the standard operations and return a name -> operation-id map."""
    return {
        "and": engine.define_primitive("and", lambda ctx: all(ctx.values())),
        "or": engine.define_primitive("or", lambda ctx: any(ctx.values())),
        "not": engine.define_primitive("not", lambda ctx: not _single(ctx)),
        "gather": engine.define_primitive("gather", _gather),
        "collect": engine.define_primitive("collect", lambda ctx: ctx.values()),
        "if": engine.define_primitive("if", _if),
        "add": engine.define_primitive("add", _binary(operator.add)),
        "sub": engine.define_primitive("sub", _binary(operator.sub)),
        "mul": engine.define_primitive("mul", _binary(operator.mul)),
        "eq": engine.define_primitive("eq", _binary(operator.eq)),
        "lt": engine.define_primitive("lt", _binary(operator.lt)),
        "le": engine.define_primitive("le", _binary(operator.le)),
        "get": engine.define_primitive("get", _get),
        "value_of": engine.define_primitive("value_of", _value_of),
        "related": engine.define_primitive("related", _related),
        "members": engine.define_primitive("members", _members),
    }


def _is_int(ctx: EvalContext) -> bool:
    value = ctx.evaluate(ctx.operands[0])
    return isinstance(value, int) and not isinstance(value, bool)


def _has_required_roles(ctx: EvalContext) -> bool:
    node, type_ = ctx.operands[0], ctx.operands[1]
    required = ctx.store.objects(
        type_, roles.REQUIRES, valid_at=ctx.valid_at, as_of_tx=ctx.as_of_tx
    )
    return all(
        ctx.store.objects(node, role, valid_at=ctx.valid_at, as_of_tx=ctx.as_of_tx)
        for role in required
    )


def install_types(engine: Engine) -> dict[str, Id]:
    """Register the standard types (and the structural validator) by name.

    Value types validate the evaluated value's Python type; ``structural`` is a
    validator operation that checks a node has every role listed under the type's
    ``REQUIRES`` facts — the basis for entity schemas like Person.
    """
    is_bool = engine.define_primitive(
        "validate/bool", lambda ctx: isinstance(ctx.evaluate(ctx.operands[0]), bool)
    )
    is_text = engine.define_primitive(
        "validate/text", lambda ctx: isinstance(ctx.evaluate(ctx.operands[0]), str)
    )
    is_int = engine.define_primitive("validate/int", _is_int)
    structural = engine.define_primitive("validate/structural", _has_required_roles)
    return {
        "Boolean": engine.define_type("Boolean", is_bool),
        "Integer": engine.define_type("Integer", is_int),
        "Text": engine.define_type("Text", is_text),
        "structural": structural,
    }
