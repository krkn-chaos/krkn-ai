from krkn_ai.dashboard.lineage import build_lineage_edges, summarize_mutation_impact


def _records():
    return [
        {"scenario_uuid": "a", "generation": 0, "fitness_score": 2.0, "parent_uuids": []},
        {
            "scenario_uuid": "b", "generation": 0, "fitness_score": 4.0,
            "parent_uuids": [],
        },
        {
            "scenario_uuid": "c", "generation": 1, "fitness_score": 8.0,
            "parent_uuids": ["a", "b"], "mutation_type": "crossover",
        },
    ]


def test_build_lineage_edges_joins_uuid_fields():
    assert build_lineage_edges(_records()) == [
        {"parent_uuid": "a", "child_uuid": "c"},
        {"parent_uuid": "b", "child_uuid": "c"},
    ]


def test_summarize_mutation_impact_uses_average_parent():
    assert summarize_mutation_impact(_records()) == [
        {
            "mutation_type": "crossover",
            "samples": 1,
            "average_fitness_delta": 5.0,
        }
    ]
