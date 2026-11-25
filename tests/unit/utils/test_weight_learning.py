"""Unit tests for learning fitness-query weights from a run."""

import datetime
from types import SimpleNamespace

import pytest

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
    @pytest.mark.parametrize(
        "content", ['["up"]', '"up"', "1", "0.5", "true", "null", "[]", "false", "0"]
    )
    def test_non_object_json_returns_empty(self, tmp_path, content):
        path = tmp_path / "learned_weights.json"
        path.write_text(content, encoding="utf-8")

        assert load_learned_weights(str(path)) == {}

    def test_malformed_json_returns_empty(self, tmp_path):
        path = tmp_path / "learned_weights.json"
        path.write_text('{"up":', encoding="utf-8")

        assert load_learned_weights(str(path)) == {}

    def test_roundtrip(self, tmp_path):
        path = str(tmp_path / "learned_weights.json")
        save_learned_weights({"q1": 0.7, "q2": 0.3}, path)
        assert load_learned_weights(path) == {"q1": 0.7, "q2": 0.3}

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_learned_weights(str(tmp_path / "nope.json")) == {}

    def test_none_path_returns_empty(self):
        assert load_learned_weights(None) == {}


class TestSNRWeightLearning:
    def test_snr_downweights_noisy_steady_state_query(self):
        items = [_item(0, "quiet_metric"), _item(1, "noisy_metric")]
        # Both metrics exhibit identical scenario spread across chaos runs
        results = [
            _scenario([(0, 0.0), (1, 0.0)]),
            _scenario([(0, 100.0), (1, 100.0)]),
        ]

        class FakePromClient:
            def process_prom_query_in_range(self, query, start_time, end_time, granularity):
                if "quiet_metric" in query:
                    # Flat steady-state baseline: constant 10.0
                    return [{"values": [[0, "10.0"], [30, "10.0"], [60, "10.0"]]}]
                else:
                    # Noisy steady-state baseline: wild fluctuations
                    return [{"values": [[0, "0.0"], [30, "50.0"], [60, "100.0"]]}]

        weights = learn_weights(results, items, prom_client=FakePromClient())
        assert weights["quiet_metric"] > weights["noisy_metric"]

    def test_snr_shared_scale_and_noise_floor_stability(self):
        # A perfectly quiet metric (noise=0) should not cause runaway explosive weighting
        items = [_item(0, "zero_noise"), _item(1, "tiny_noise")]
        results = [
            _scenario([(0, 10.0), (1, 10.0)]),
            _scenario([(0, 50.0), (1, 50.0)]),
        ]

        class FakePromClient:
            def process_prom_query_in_range(self, query, start_time, end_time, granularity):
                if "zero_noise" in query:
                    return [{"values": [[0, "5.0"], [30, "5.0"]]}]
                else:
                    return [{"values": [[0, "5.0"], [30, "5.05"]]}]

        weights = learn_weights(results, items, prom_client=FakePromClient())
        # Both weights should be in sane, comparable proportions, bounded by the noise floor
        ratio = weights["zero_noise"] / weights["tiny_noise"]
        assert 1.0 <= ratio < 2.0

    def test_baseline_window_passed_to_prom(self):
        items = [_item(0, "metric_a")]
        results = [_scenario([(0, 10.0)]), _scenario([(0, 50.0)])]

        captured_window = {}
        t_start = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        t_end = datetime.datetime(2026, 1, 1, 12, 5, 0, tzinfo=datetime.timezone.utc)

        class CapturingPromClient:
            def process_prom_query_in_range(self, query, start_time, end_time, granularity):
                captured_window["start"] = start_time
                captured_window["end"] = end_time
                return [{"values": [[0, "5.0"]]}]

        learn_weights(
            results,
            items,
            prom_client=CapturingPromClient(),
            baseline_window=(t_start, t_end),
        )
        assert captured_window["start"] == t_start
        assert captured_window["end"] == t_end

    def test_prom_failure_gracefully_degrades_to_signal_spread(self):
        items = [_item(0, "metric_a"), _item(1, "metric_b")]
        results = [
            _scenario([(0, 10.0), (1, 5.0)]),
            _scenario([(0, 50.0), (1, 5.0)]),
        ]

        class BrokenPromClient:
            def process_prom_query_in_range(self, query, start_time, end_time, granularity):
                raise RuntimeError("Prometheus timeout")

        weights = learn_weights(results, items, prom_client=BrokenPromClient())
        assert weights["metric_a"] == 1.0
        assert weights["metric_b"] == 0.0
