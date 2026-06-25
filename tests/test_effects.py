"""M7: effects/IO — observations recorded as facts; pure evaluation."""

from __future__ import annotations

from datetime import timedelta

from thallus import Engine, roles, stdlib, utcnow


def test_refresh_records_observations():
    e = Engine()
    readings = iter([22.5, 23.0])
    temp = e.define_effect("temperature", lambda: next(readings))
    weather = e.effect_node(temp, freshness=900)

    e.refresh(weather)
    assert e.value(weather) == 22.5
    e.refresh(weather)
    assert e.value(weather) == 23.0  # a new observation supersedes the old


def test_dependents_react_to_new_observations():
    e = Engine()
    ops = stdlib.install(e)
    readings = iter([22.5, 100.0])
    temp = e.define_effect("temperature", lambda: next(readings))
    weather = e.effect_node(temp, freshness=900)
    is_hot = e.application(ops["lt"], e.literal(50.0), weather)  # 50 < temp ?

    e.refresh(weather)
    assert e.value(is_hot) is False
    e.refresh(weather)
    assert e.value(is_hot) is True  # downstream recomputed from the new fact


def test_failure_keeps_last_good_value_and_records_error():
    e = Engine()
    calls = [0]

    def flaky():
        calls[0] += 1
        if calls[0] == 1:
            return 42
        raise RuntimeError("api down")

    eff = e.define_effect("flaky", flaky)
    node = e.effect_node(eff, freshness=900)

    assert e.refresh(node) == ("ok", 42)
    assert e.value(node) == 42
    status, message = e.refresh(node)
    assert status == "error" and message == "api down"
    assert e.value(node) == 42  # last good value retained
    assert e.store.one(node.id, roles.ERROR) == "api down"


def test_freshness_and_due_effects():
    e = Engine()
    readings = iter([1, 2])
    eff = e.define_effect("counter", lambda: next(readings))
    node = e.effect_node(eff, freshness=300)  # 5 minutes
    t0 = utcnow()
    e.refresh(node, at=t0)

    assert e.is_stale(node, now=t0 + timedelta(seconds=100)) is False
    assert e.is_stale(node, now=t0 + timedelta(seconds=400)) is True
    assert node.id in e.due_effects(now=t0 + timedelta(seconds=400))
    assert node.id not in e.due_effects(now=t0 + timedelta(seconds=100))


def test_each_observation_is_bitemporal():
    e = Engine()
    readings = iter([10, 20])
    eff = e.define_effect("counter", lambda: next(readings))
    node = e.effect_node(eff, freshness=300)
    t0 = utcnow()
    t1 = t0 + timedelta(hours=1)
    e.refresh(node, at=t0)
    e.refresh(node, at=t1)

    assert e.value(node, valid_at=t1) == 20
    assert e.value(node, valid_at=t0 + timedelta(minutes=1)) == 10  # time-travel
