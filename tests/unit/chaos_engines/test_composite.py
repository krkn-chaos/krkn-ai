"""Tests for krkn_ai.chaos_engines.composite"""

import json
import os
import re

import pytest

from krkn_ai.chaos_engines.composite import build_graph_command
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.scenario.base import CompositeDependency, CompositeScenario
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
