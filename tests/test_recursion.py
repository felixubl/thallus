"""Recursion, lazy conditional, and arithmetic/comparison primitives."""

from __future__ import annotations

import pytest

from thallus import Engine, RecursionLimitError, stdlib


def test_comparisons_and_arithmetic():
    e = Engine()
    ops = stdlib.install(e)
    assert e.value(e.application(ops["add"], e.literal(2), e.literal(3))) == 5
    assert e.value(e.application(ops["le"], e.literal(1), e.literal(1))) is True
    assert e.value(e.application(ops["lt"], e.literal(2), e.literal(1))) is False


def test_if_is_lazy():
    e = Engine()
    ops = stdlib.install(e)
    boom = e.node()  # no value: evaluating it would raise
    out = e.application(ops["if"], e.literal(True), e.literal("ok"), boom)
    assert e.value(out) == "ok"  # the else branch is never evaluated


def test_recursive_factorial():
    e = Engine()
    ops = stdlib.install(e)
    fact = e.node()  # forward declaration so the body can reference it
    n = e.node()
    cond = e.application(ops["le"], n, e.literal(1))
    recurse = e.application(
        ops["mul"],
        n,
        e.application(fact, e.application(ops["sub"], n, e.literal(1))),
    )
    body = e.application(ops["if"], cond, e.literal(1), recurse)
    e.define_lambda([n], body, into=fact, name="fact")

    assert e.value(e.application(fact, e.literal(0))) == 1
    assert e.value(e.application(fact, e.literal(5))) == 120


def test_non_terminating_recursion_is_bounded():
    e = Engine()
    loop = e.node()
    m = e.node()
    body = e.application(loop, m)  # loop(m) = loop(m): no base case
    e.define_lambda([m], body, into=loop)
    with pytest.raises(RecursionLimitError):
        e.value(e.application(loop, e.literal(1)))


def test_static_data_cycle_still_detected():
    # A self-referential value (not a function call) is still a hard error.
    from thallus import CycleError

    e = Engine()
    ops = stdlib.install(e)
    x = e.node()
    x.apply(ops["not"], x)  # x = not x
    with pytest.raises(CycleError):
        e.value(x)
