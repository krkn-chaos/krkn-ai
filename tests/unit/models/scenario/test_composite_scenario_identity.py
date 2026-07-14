"""Regression tests for #380.

`CompositeScenario` identity must include the ``dependency`` field. Two
composites with the same children but a different dependency execute as
different graphs (`KrknRunner.__expand_composite_json`), so they must not
collide as the same hash/equality key — otherwise the GA fitness cache
(`GeneticAlgorithm.seen_population`, keyed by scenario) returns the wrong
scenario's cached result.
"""

from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.scenario.base import CompositeScenario, CompositeDependency


def _pair():
    cluster = ClusterComponents(namespaces=[], nodes=[])
    a = DummyScenario(cluster_components=cluster)
    b = DummyScenario(cluster_components=cluster)
    none = CompositeScenario(
        name="composite",
        scenario_a=a,
        scenario_b=b,
        dependency=CompositeDependency.NONE,
    )
    a_on_b = CompositeScenario(
        name="composite",
        scenario_a=a,
        scenario_b=b,
        dependency=CompositeDependency.A_ON_B,
    )
    return none, a_on_b


def test_different_dependency_not_equal():
    none, a_on_b = _pair()
    assert none != a_on_b


def test_different_dependency_distinct_hash():
    none, a_on_b = _pair()
    assert hash(none) != hash(a_on_b)


def test_different_dependency_distinct_cache_keys():
    none, a_on_b = _pair()
    cache = {none: "result_for_NONE"}
    assert a_on_b not in cache


def test_same_dependency_still_collides():
    cluster = ClusterComponents(namespaces=[], nodes=[])
    a = DummyScenario(cluster_components=cluster)
    b = DummyScenario(cluster_components=cluster)
    c1 = CompositeScenario(
        name="composite",
        scenario_a=a,
        scenario_b=b,
        dependency=CompositeDependency.NONE,
    )
    c2 = CompositeScenario(
        name="composite",
        scenario_a=a,
        scenario_b=b,
        dependency=CompositeDependency.NONE,
    )
    assert c1 == c2
    assert hash(c1) == hash(c2)
