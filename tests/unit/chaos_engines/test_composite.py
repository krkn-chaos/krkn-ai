"""Tests for krkn_ai.chaos_engines.composite"""

import json
import os
import re

import pytest

from krkn_ai.chaos_engines.composite import (
    _expand_composite_json,
    build_graph_command,
)
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.scenario.base import CompositeDependency, CompositeScenario
from krkn_ai.models.scenario.factory import ScenarioFactory
from krkn_ai.models.scenario.scenario_dummy import DummyScenario

# krknctl names a node's container krknctl-<node id>-<n>. Docker rejects any
# other name: "Invalid container name, only [a-zA-Z0-9][a-zA-Z0-9_.-] are allowed"
CONTAINER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


def _dummy():
    return DummyScenario(cluster_components=ClusterComponents())


def _composite(dependency, a=None, b=None):
    return CompositeScenario(
        scenario_a=a or _dummy(), scenario_b=b or _dummy(), dependency=dependency
    )


def _graph(scenario, output_dir):
    command = build_graph_command(scenario, "/tmp/kubeconfig", str(output_dir))
    graph_dir = os.path.join(str(output_dir), "graphs")
    path = next(os.path.join(graph_dir, name) for name in os.listdir(graph_dir))
    assert path in command
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize(
    "scenario",
    [
        _composite(dependency)
        for dependency in (
            CompositeDependency.NONE,
            CompositeDependency.A_ON_B,
            CompositeDependency.B_ON_A,
        )
    ]
    + [
        _composite(
            CompositeDependency.NONE,
            a=_composite(CompositeDependency.A_ON_B),
            b=_composite(
                CompositeDependency.NONE, a=_composite(CompositeDependency.B_ON_A)
            ),
        )
    ],
    ids=["none", "a_on_b", "b_on_a", "nested"],
)
class TestGraphNodeIds:
    def test_node_ids_are_valid_in_a_container_name(self, scenario, tmp_path):
        graph = _graph(scenario, tmp_path)
        assert graph
        for node_id in graph:
            assert CONTAINER_NAME_RE.match(f"krknctl-{node_id}-123"), node_id

    def test_depends_on_refers_to_a_node_in_the_graph(self, scenario, tmp_path):
        graph = _graph(scenario, tmp_path)
        for node in graph.values():
            if node.get("depends_on") is not None:
                assert node["depends_on"] in graph


def test_expand_composite_json_b_on_a_nested():
    """
    Test that when a nested CompositeScenario is placed in scenario_b
    with a B_ON_A dependency, the nested root properly depends on key_a
    rather than causing a dangling pointer to itself (key_b).
    Resolves Issue #411.
    """
    # Create the nested composite for scenario_b
    nested_b = CompositeScenario(
        scenario_a=ScenarioFactory.create_dummy_scenario(),
        scenario_b=ScenarioFactory.create_dummy_scenario(),
        dependency=CompositeDependency.A_ON_B,
    )

    # Create the parent composite with B_ON_A dependency
    parent = CompositeScenario(
        scenario_a=ScenarioFactory.create_dummy_scenario(),
        scenario_b=nested_b,
        dependency=CompositeDependency.B_ON_A,
    )

    # Expand the JSON graph
    # Default root key is "root"
    # key_a is "rootl", key_b is "rootr"
    result, _ = _expand_composite_json(parent)

    # In the result, we should see nodes for the nested B composite.
    # Because B depends on A, the nested B components should depend on key_a ("rootl").

    # nested_b is "rootr". Its A component is "rootrl", its B component is "rootrr".
    # nested_b has A_ON_B dependency.
    # So "rootrl" should depend on "rootrr".
    # And "rootrr" (the root of the nested_b subtree) should depend on the parent's depends_on.
    # Since parent is B_ON_A, nested_b's depends_on is "rootl" (key_a).

    assert "rootl" in result
    assert "rootrl" in result
    assert "rootrr" in result

    # "rootrl" (A of nested) depends on "rootrr" (B of nested) because nested_b is A_ON_B
    assert result["rootrl"]["depends_on"] == "rootrr"
    assert result["rootrr"]["depends_on"] == "rootl"


def test_expand_composite_json_b_on_a_with_composite_a():
    """
    Test the edge case requested by AI reviewer:
    Parent has B_ON_A dependency, but scenario_a is a CompositeScenario
    with A_ON_B dependency. Ensure B depends on the *actual* terminal node
    of A (which is A's A component, i.e., "rootll"), and not the missing "rootl".
    """
    nested_a = CompositeScenario(
        scenario_a=ScenarioFactory.create_dummy_scenario(),
        scenario_b=ScenarioFactory.create_dummy_scenario(),
        dependency=CompositeDependency.A_ON_B,
    )

    parent = CompositeScenario(
        scenario_a=nested_a,
        scenario_b=ScenarioFactory.create_dummy_scenario(),
        dependency=CompositeDependency.B_ON_A,
    )

    result, _ = _expand_composite_json(parent)

    # Assert every depends_on value exists in the graph (no dangling pointers)
    for key, node in result.items():
        if "depends_on" in node:
            assert node["depends_on"] in result, (
                f"Dangling pointer found: {node['depends_on']}"
            )

    # nested_a is A_ON_B, so "rootll" depends on "rootlr"
    assert result["rootll"]["depends_on"] == "rootlr"

    # parent is B_ON_A, so B ("rootr") should depend on the terminal key of A ("rootll")
    assert result["rootr"]["depends_on"] == "rootll"
