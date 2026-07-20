"""Unit tests for scenario parameter mutation behaviour."""

from unittest.mock import patch

from krkn_ai.models.scenario.parameters import (
    IOWriteBytesParameter,
    NodeCPUPercentageParameter,
    NodeMemoryPercentageParameter,
)

_RNG = "krkn_ai.models.scenario.parameters.rng"


class TestPercentageMutationDoesNotStagnate:
    """Regression tests for #292: mutate must change small values by >= 1.

    The old logic did ``self.value += int(rng.randint(1, 35) * self.value / 100)``.
    For small values the product is < 1, ``int()`` truncates it to ``0`` and the
    mutation is a no-op, so the genetic algorithm stops exploring those params.
    """

    def test_io_write_bytes_low_value_increments_by_at_least_one(self):
        param = IOWriteBytesParameter()
        param.value = 1
        # random < 0.5 -> increment branch; smallest possible multiplier (1).
        # Old code: int(1 * 1 / 100) == 0 -> value stays 1 (the bug).
        with (
            patch(f"{_RNG}.random", return_value=0.0),
            patch(f"{_RNG}.randint", return_value=1),
        ):
            param.mutate()
        assert param.value == 2

    def test_cpu_percentage_at_floor_can_increase(self):
        param = NodeCPUPercentageParameter()
        param.value = 20  # the floor
        with (
            patch(f"{_RNG}.random", return_value=0.0),
            patch(f"{_RNG}.randint", return_value=1),
        ):
            param.mutate()
        assert param.value == 21

    def test_decrement_at_floor_stays_at_floor(self):
        param = IOWriteBytesParameter()
        param.value = 1  # floor for this parameter
        # random >= 0.5 -> decrement branch; would go to 0 but is clamped up.
        with (
            patch(f"{_RNG}.random", return_value=0.9),
            patch(f"{_RNG}.randint", return_value=1),
        ):
            param.mutate()
        assert param.value == 1

    def test_result_always_within_bounds_and_integer(self):
        for cls, floor in (
            (NodeCPUPercentageParameter, 20),
            (NodeMemoryPercentageParameter, 20),
            (IOWriteBytesParameter, 1),
        ):
            param = cls()
            for start in (floor, 50, 100):
                param.value = start
                for _ in range(200):
                    param.mutate()
                    assert floor <= param.value <= 100
                    assert isinstance(param.value, int)
