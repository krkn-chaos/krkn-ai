"""Unit tests for learning fitness-query weights from a run."""

from types import SimpleNamespace

from krkn_ai.utils.weight_learning import (
    learn_weights,
    load_learned_weights,
    save_learned_weights,
)


def _item(id, query):
    return SimpleNamespace(id=id, query=query)


def _scenario(scores):
    # scores: list of (id, raw_value)
    return SimpleNamespace(
        fitness_result=SimpleNamespace(
            scores=[SimpleNamespace(id=i, fitness_score=v) for i, v in scores]
        )
    )


class TestLearnWeights:
    def test_discriminating_query_gets_more_weight(self):
        items = [_item(0, "restarts"), _item(1, "always-flat")]
        # restarts spikes in one scenario; always-flat never moves
        results = [
            _scenario([(0, 0.0), (1, 5.0)]),
            _scenario([(0, 0.0), (1, 5.0)]),
            _scenario([(0, 50.0), (1, 5.0)]),
        ]
        weights = learn_weights(results, items)
        assert weights["restarts"] > weights["always-flat"]
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_no_signal_returns_empty(self):
        items = [_item(0, "flat")]
        results = [_scenario([(0, 5.0)]), _scenario([(0, 5.0)])]
        assert learn_weights(results, items) == {}

    def test_signed_values_keep_signal(self):
        # negative values must still count as signal
        items = [_item(0, "delta")]
        results = [_scenario([(0, -10.0)]), _scenario([(0, 10.0)])]
        assert learn_weights(results, items) == {"delta": 1.0}

    def test_near_zero_mean_does_not_explode(self):
        # a near-zero mean must not blow up the weight
        items = [_item(0, "swingy"), _item(1, "steady")]
        results = [
            _scenario([(0, -5.0), (1, 100.0)]),
            _scenario([(0, 5.0), (1, 300.0)]),
        ]
        weights = learn_weights(results, items)
        assert all(0.0 <= w <= 1.0 for w in weights.values())

    def test_keys_by_query_not_id(self):
        items = [_item(7, "q-a"), _item(9, "q-b")]
        results = [_scenario([(7, 1.0), (9, 0.0)]), _scenario([(7, 0.0), (9, 9.0)])]
        weights = learn_weights(results, items)
        assert set(weights) == {"q-a", "q-b"}

    def test_ignores_unknown_ids(self):
        items = [_item(0, "known")]
        results = [_scenario([(0, 1.0), (99, 5.0)]), _scenario([(0, 9.0), (99, 5.0)])]
        weights = learn_weights(results, items)
        assert set(weights) == {"known"}


class TestSaveLoad:
    def test_roundtrip(self, tmp_path):
        path = str(tmp_path / "learned_weights.json")
        save_learned_weights({"q1": 0.7, "q2": 0.3}, path)
        assert load_learned_weights(path) == {"q1": 0.7, "q2": 0.3}

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_learned_weights(str(tmp_path / "nope.json")) == {}

    def test_none_path_returns_empty(self):
        assert load_learned_weights(None) == {}
