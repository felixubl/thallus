"""Tests for composite operations (lambdas) and ordered operands (M4)."""

from __future__ import annotations

import pytest

from thallus import ArityError, Engine, stdlib


def test_identity_lambda():
    e = Engine()
    x = e.node()
    identity = e.define_lambda([x], x, name="identity")
    app = e.application(identity, e.literal(42))
    assert e.value(app) == 42


def test_composite_over_primitives_nand():
    e = Engine()
    ops = stdlib.install(e)
    a, b = e.node(), e.node()
    conj = e.application(ops["and"], a, b)
    body = e.application(ops["not"], conj)
    nand = e.define_lambda([a, b], body, name="nand")

    assert e.value(e.application(nand, e.literal(True), e.literal(True))) is False
    assert e.value(e.application(nand, e.literal(True), e.literal(False))) is True


def test_operand_order_is_significant():
    # implies(a, b) = or(not(a), b); asymmetric, so order must be respected.
    e = Engine()
    ops = stdlib.install(e)
    a, b = e.node(), e.node()
    body = e.application(ops["or"], e.application(ops["not"], a), b)
    implies = e.define_lambda([a, b], body, name="implies")

    assert e.value(e.application(implies, e.literal(True), e.literal(False))) is False
    assert e.value(e.application(implies, e.literal(False), e.literal(True))) is True
    # If order were ignored, these two would not differ.


def test_parameter_used_twice():
    e = Engine()
    ops = stdlib.install(e)
    x = e.node()
    body = e.application(ops["and"], x, x)
    same = e.define_lambda([x], body, name="self_and")
    assert e.value(e.application(same, e.literal(True))) is True
    assert e.value(e.application(same, e.literal(False))) is False


def test_arity_mismatch():
    e = Engine()
    x = e.node()
    identity = e.define_lambda([x], x)
    with pytest.raises(ArityError):
        e.value(e.application(identity, e.literal(1), e.literal(2)))


def test_lambda_is_an_editable_entity_with_content_fingerprint():
    e = Engine()
    x = e.node()
    op = e.define_lambda([x], x)
    assert op.scheme == "ent"  # editable identity, not content-addressed
    assert e.fingerprint(op).scheme == "cas"  # structural digest for detection


def test_nested_lambda_application():
    # double_not(x) = not(not(x)) using a composite inside another expression.
    e = Engine()
    ops = stdlib.install(e)
    x = e.node()
    body = e.application(ops["not"], e.application(ops["not"], x))
    double_not = e.define_lambda([x], body, name="double_not")
    assert e.value(e.application(double_not, e.literal(True))) is True
    assert e.value(e.application(double_not, e.literal(False))) is False
