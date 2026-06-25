"""Built-in role and bootstrap vocabulary.

Roles are ordinary nodes; these are the few with stable, kernel-known identities.
Their *behavior* is given by later layers (eval, types) — here they are just
names so the vocabulary is fixed from the start.
"""

from __future__ import annotations

from .ids import builtin_id

__all__ = [
    "VALUE",
    "TYPE",
    "LABEL",
    "MEMBER",
    "OPERATION",
    "OPERAND",
    "PARAMETER",
    "BODY",
    "VALIDATOR",
    "REQUIRES",
    "INDEX",
    "EFFECT",
    "FRESHNESS",
    "ERROR",
    "PREDICATE",
    "OVER",
    "SYMMETRIC",
    "INVERSE",
    "ROOT_TYPE",
    "OPERATION_TYPE",
    "EFFECT_TYPE",
    "PROPERTY_TYPE",
]

# Roles
VALUE = builtin_id("role/value")
TYPE = builtin_id("role/type")
LABEL = builtin_id("role/label")
MEMBER = builtin_id("role/member")
OPERATION = builtin_id("role/operation")
OPERAND = builtin_id("role/operand")
PARAMETER = builtin_id("role/parameter")
BODY = builtin_id("role/body")
VALIDATOR = builtin_id("role/validator")
REQUIRES = builtin_id("role/requires")
INDEX = builtin_id("role/index")  # ordering annotation on an operand/parameter fact
EFFECT = builtin_id("role/effect")  # links an effectful node to its effect
FRESHNESS = builtin_id("role/freshness")  # max age (seconds) before an observation is stale
ERROR = builtin_id("role/error")  # last failure of an effectful node
PREDICATE = builtin_id("role/predicate")  # a property node's membership predicate
OVER = builtin_id("role/over")  # roles a property ranges over (narrows its scan)
SYMMETRIC = builtin_id("role/symmetric")  # marks a role as bidirectional
INVERSE = builtin_id("role/inverse")  # links a role to its inverse (manages/managed_by)

# Bootstrap types
ROOT_TYPE = builtin_id("type/Type")  # its own type
OPERATION_TYPE = builtin_id("type/Operation")
EFFECT_TYPE = builtin_id("type/Effect")
PROPERTY_TYPE = builtin_id("type/Property")
