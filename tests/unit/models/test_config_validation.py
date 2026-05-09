"""
Tests for ConfigFile, BaselineConfig, and AdaptiveMutation input validation.

Validates that genetic algorithm parameters are properly constrained:
- Probability rates within [0.0, 1.0]
- Positive integer constraints on sizes, generations, and durations
- Cross-field validation (adaptive_mutation.min < adaptive_mutation.max)
"""

import pytest
from pydantic import ValidationError

from krkn_ai.models.config import (
    AdaptiveMutation,
    BaselineConfig,
    ConfigFile,
    FitnessFunction,
)
from krkn_ai.models.cluster_components import ClusterComponents


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> ConfigFile:
    """Create a valid ConfigFile with optional field overrides."""
    defaults = {
        "kubeconfig_file_path": "/path/to/kubeconfig",
        "fitness_function": FitnessFunction(query="up"),
        "cluster_components": ClusterComponents(namespaces=[], nodes=[]),
    }
    defaults.update(overrides)
    return ConfigFile(**defaults)


# ===========================================================================
# BaselineConfig validation
# ===========================================================================


class TestBaselineConfigValidation:
    """Tests for BaselineConfig.duration validation."""

    def test_valid_duration(self):
        config = BaselineConfig(duration=120)
        assert config.duration == 120

    def test_duration_zero_raises(self):
        with pytest.raises(ValidationError, match="baseline duration must be a positive integer"):
            BaselineConfig(duration=0)

    def test_duration_negative_raises(self):
        with pytest.raises(ValidationError, match="baseline duration must be a positive integer"):
            BaselineConfig(duration=-10)


# ===========================================================================
# AdaptiveMutation validation
# ===========================================================================


class TestAdaptiveMutationValidation:
    """Tests for AdaptiveMutation field and cross-field validation."""

    # --- rate range ---

    def test_valid_min_max(self):
        am = AdaptiveMutation(min=0.1, max=0.8)
        assert am.min == 0.1
        assert am.max == 0.8

    def test_min_below_zero_raises(self):
        with pytest.raises(ValidationError, match="adaptive_mutation.min must be between 0.0 and 1.0"):
            AdaptiveMutation(min=-0.1)

    def test_min_above_one_raises(self):
        with pytest.raises(ValidationError, match="adaptive_mutation.min must be between 0.0 and 1.0"):
            AdaptiveMutation(min=1.5)

    def test_max_below_zero_raises(self):
        with pytest.raises(ValidationError, match="adaptive_mutation.max must be between 0.0 and 1.0"):
            AdaptiveMutation(max=-0.5)

    def test_max_above_one_raises(self):
        with pytest.raises(ValidationError, match="adaptive_mutation.max must be between 0.0 and 1.0"):
            AdaptiveMutation(max=2.0)

    def test_boundary_min_zero_max_one(self):
        """Boundary: min=0.0 and max=1.0 are valid."""
        am = AdaptiveMutation(min=0.0, max=1.0)
        assert am.min == 0.0
        assert am.max == 1.0

    # --- cross-field: min < max ---

    def test_min_equals_max_raises(self):
        with pytest.raises(ValidationError, match="must be less than"):
            AdaptiveMutation(min=0.5, max=0.5)

    def test_min_greater_than_max_raises(self):
        with pytest.raises(ValidationError, match="must be less than"):
            AdaptiveMutation(min=0.9, max=0.1)

    # --- generations ---

    def test_valid_generations(self):
        am = AdaptiveMutation(generations=10)
        assert am.generations == 10

    def test_generations_zero_raises(self):
        with pytest.raises(ValidationError, match="adaptive_mutation.generations must be a positive integer"):
            AdaptiveMutation(generations=0)

    def test_generations_negative_raises(self):
        with pytest.raises(ValidationError, match="adaptive_mutation.generations must be a positive integer"):
            AdaptiveMutation(generations=-5)


# ===========================================================================
# ConfigFile probability rate validation
# ===========================================================================


class TestConfigFileProbabilityRates:
    """Tests for rate fields that must be within [0.0, 1.0]."""

    RATE_FIELDS = [
        "mutation_rate",
        "scenario_mutation_rate",
        "crossover_rate",
        "composition_rate",
        "population_injection_rate",
    ]

    @pytest.mark.parametrize("field", RATE_FIELDS)
    def test_valid_rate_zero(self, field):
        config = _make_config(**{field: 0.0})
        assert getattr(config, field) == 0.0

    @pytest.mark.parametrize("field", RATE_FIELDS)
    def test_valid_rate_one(self, field):
        config = _make_config(**{field: 1.0})
        assert getattr(config, field) == 1.0

    @pytest.mark.parametrize("field", RATE_FIELDS)
    def test_valid_rate_midpoint(self, field):
        config = _make_config(**{field: 0.5})
        assert getattr(config, field) == 0.5

    @pytest.mark.parametrize("field", RATE_FIELDS)
    def test_rate_above_one_raises(self, field):
        with pytest.raises(ValidationError, match=f"{field} must be between 0.0 and 1.0"):
            _make_config(**{field: 1.5})

    @pytest.mark.parametrize("field", RATE_FIELDS)
    def test_rate_negative_raises(self, field):
        with pytest.raises(ValidationError, match=f"{field} must be between 0.0 and 1.0"):
            _make_config(**{field: -0.1})

    @pytest.mark.parametrize("field", RATE_FIELDS)
    def test_rate_large_value_raises(self, field):
        with pytest.raises(ValidationError, match=f"{field} must be between 0.0 and 1.0"):
            _make_config(**{field: 99.0})


# ===========================================================================
# ConfigFile population_size validation
# ===========================================================================


class TestConfigFilePopulationSize:
    """Tests for population_size validation (must be >= 2)."""

    def test_valid_population_size(self):
        config = _make_config(population_size=10)
        assert config.population_size == 10

    def test_population_size_minimum(self):
        config = _make_config(population_size=2)
        assert config.population_size == 2

    def test_population_size_one_raises(self):
        with pytest.raises(ValidationError, match="population_size must be at least 2"):
            _make_config(population_size=1)

    def test_population_size_zero_raises(self):
        with pytest.raises(ValidationError, match="population_size must be at least 2"):
            _make_config(population_size=0)

    def test_population_size_negative_raises(self):
        with pytest.raises(ValidationError, match="population_size must be at least 2"):
            _make_config(population_size=-5)


# ===========================================================================
# ConfigFile population_injection_size validation
# ===========================================================================


class TestConfigFileInjectionSize:
    """Tests for population_injection_size validation (must be >= 1)."""

    def test_valid_injection_size(self):
        config = _make_config(population_injection_size=5)
        assert config.population_injection_size == 5

    def test_injection_size_minimum(self):
        config = _make_config(population_injection_size=1)
        assert config.population_injection_size == 1

    def test_injection_size_zero_raises(self):
        with pytest.raises(ValidationError, match="population_injection_size must be at least 1"):
            _make_config(population_injection_size=0)

    def test_injection_size_negative_raises(self):
        with pytest.raises(ValidationError, match="population_injection_size must be at least 1"):
            _make_config(population_injection_size=-3)


# ===========================================================================
# ConfigFile generations validation
# ===========================================================================


class TestConfigFileGenerations:
    """Tests for generations validation (must be > 0 when set)."""

    def test_valid_generations(self):
        config = _make_config(generations=20)
        assert config.generations == 20

    def test_generations_none_allowed(self):
        config = _make_config(generations=None)
        assert config.generations is None

    def test_generations_one_valid(self):
        config = _make_config(generations=1)
        assert config.generations == 1

    def test_generations_zero_raises(self):
        with pytest.raises(ValidationError, match="generations must be a positive integer"):
            _make_config(generations=0)

    def test_generations_negative_raises(self):
        with pytest.raises(ValidationError, match="generations must be a positive integer"):
            _make_config(generations=-10)


# ===========================================================================
# ConfigFile duration validation
# ===========================================================================


class TestConfigFileDuration:
    """Tests for duration validation (must be > 0 when set)."""

    def test_valid_duration(self):
        config = _make_config(duration=3600)
        assert config.duration == 3600

    def test_duration_none_allowed(self):
        config = _make_config(duration=None)
        assert config.duration is None

    def test_duration_one_valid(self):
        config = _make_config(duration=1)
        assert config.duration == 1

    def test_duration_zero_raises(self):
        with pytest.raises(ValidationError, match="duration must be a positive integer"):
            _make_config(duration=0)

    def test_duration_negative_raises(self):
        with pytest.raises(ValidationError, match="duration must be a positive integer"):
            _make_config(duration=-60)


# ===========================================================================
# ConfigFile wait_duration validation
# ===========================================================================


class TestConfigFileWaitDuration:
    """Tests for wait_duration validation (must be >= 0)."""

    def test_valid_wait_duration(self):
        config = _make_config(wait_duration=120)
        assert config.wait_duration == 120

    def test_wait_duration_zero_allowed(self):
        config = _make_config(wait_duration=0)
        assert config.wait_duration == 0

    def test_wait_duration_negative_raises(self):
        with pytest.raises(ValidationError, match="wait_duration must be non-negative"):
            _make_config(wait_duration=-1)


# ===========================================================================
# Integration: valid defaults pass all validation
# ===========================================================================


class TestConfigFileDefaultsValid:
    """Ensure the default values for all fields pass validation."""

    def test_defaults_pass(self):
        config = _make_config()
        assert config.population_size == 10
        assert config.generations == 20
        assert config.duration is None
        assert config.wait_duration == 120
        assert config.mutation_rate == 0.7
        assert config.scenario_mutation_rate == 0.6
        assert config.crossover_rate == 0.6
        assert config.composition_rate == 0
        assert config.population_injection_rate == 0
        assert config.population_injection_size == 2
