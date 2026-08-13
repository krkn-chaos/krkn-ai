"""
Lineage dashboard tab unit tests
"""

import pandas as pd

from krkn_ai.dashboard.tabs.lineage import (
    _build_ancestry_chain,
    _origin_to_streamlit_color,
)


class TestBuildAncestryChain:
    def _make_uuid_map(self, rows):
        df = pd.DataFrame(rows)
        return {row["scenario_uuid"]: df.iloc[i] for i, row in df.iterrows()}

    def test_single_initial_scenario(self):
        uuid_map = self._make_uuid_map(
            [
                {
                    "scenario_uuid": "a",
                    "parent_ids": [],
                    "origin": "initial",
                    "generation": 0,
                    "fitness_score": 1.0,
                    "scenario_id": 0,
                },
            ]
        )
        chain = _build_ancestry_chain("a", uuid_map)
        assert len(chain) == 1
        assert chain[0]["scenario_uuid"] == "a"

    def test_follows_first_parent(self):
        uuid_map = self._make_uuid_map(
            [
                {
                    "scenario_uuid": "c",
                    "parent_ids": ["b", "a"],
                    "origin": "crossover",
                    "generation": 2,
                    "fitness_score": 3.0,
                    "scenario_id": 2,
                },
                {
                    "scenario_uuid": "b",
                    "parent_ids": ["a"],
                    "origin": "crossover",
                    "generation": 1,
                    "fitness_score": 2.0,
                    "scenario_id": 1,
                },
                {
                    "scenario_uuid": "a",
                    "parent_ids": [],
                    "origin": "initial",
                    "generation": 0,
                    "fitness_score": 1.0,
                    "scenario_id": 0,
                },
            ]
        )
        chain = _build_ancestry_chain("c", uuid_map)
        assert len(chain) == 3
        assert [n["scenario_uuid"] for n in chain] == ["c", "b", "a"]

    def test_stops_at_max_depth(self):
        rows = []
        for i in range(10):
            rows.append(
                {
                    "scenario_uuid": str(i),
                    "parent_ids": [str(i - 1)] if i > 0 else [],
                    "origin": "crossover" if i > 0 else "initial",
                    "generation": i,
                    "fitness_score": float(i),
                    "scenario_id": i,
                }
            )
        uuid_map = self._make_uuid_map(rows)
        chain = _build_ancestry_chain("9", uuid_map, max_depth=3)
        assert len(chain) == 3

    def test_handles_cycle(self):
        uuid_map = self._make_uuid_map(
            [
                {
                    "scenario_uuid": "a",
                    "parent_ids": ["b"],
                    "origin": "crossover",
                    "generation": 0,
                    "fitness_score": 1.0,
                    "scenario_id": 0,
                },
                {
                    "scenario_uuid": "b",
                    "parent_ids": ["a"],
                    "origin": "crossover",
                    "generation": 1,
                    "fitness_score": 2.0,
                    "scenario_id": 1,
                },
            ]
        )
        chain = _build_ancestry_chain("a", uuid_map)
        assert len(chain) == 2

    def test_missing_parent_stops_chain(self):
        uuid_map = self._make_uuid_map(
            [
                {
                    "scenario_uuid": "b",
                    "parent_ids": ["missing"],
                    "origin": "crossover",
                    "generation": 1,
                    "fitness_score": 2.0,
                    "scenario_id": 1,
                },
            ]
        )
        chain = _build_ancestry_chain("b", uuid_map)
        assert len(chain) == 1

    def test_unknown_start_returns_empty(self):
        chain = _build_ancestry_chain("nonexistent", {})
        assert chain == []


class TestOriginToStreamlitColor:
    def test_known_origins(self):
        assert _origin_to_streamlit_color("initial") == "gray"
        assert _origin_to_streamlit_color("crossover") == "blue"
        assert _origin_to_streamlit_color("composition") == "violet"
        assert _origin_to_streamlit_color("parameter_mutation") == "orange"
        assert _origin_to_streamlit_color("type_mutation") == "red"

    def test_unknown_origin_defaults_to_gray(self):
        assert _origin_to_streamlit_color("something_else") == "gray"
        assert _origin_to_streamlit_color(None) == "gray"
