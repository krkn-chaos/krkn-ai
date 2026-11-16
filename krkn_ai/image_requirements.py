"""Canonical managed-registry scenario image requirements."""

from __future__ import annotations

from typing import Any

from krkn_ai.models.config import ConfigFile
from krkn_ai.models.scenario.factory import ScenarioFactory, scenario_specs
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.registry import RegistryContext

DEFAULT_WORKLOAD_IMAGE_TAGS = {
    "hog": "workload-krkn-hog",
    "tools": "workload-krkn-tools",
    "synFlood": "workload-krkn-syn-flood",
    "networkChaos": "workload-krkn-network-chaos",
}


def scenario_tags() -> list[str]:
    """Return every executable scenario identity without instantiating scenarios."""
    tags = {
        scenario_type.model_fields["krknctl_name"].default
        for _config_name, scenario_type in scenario_specs
    }
    tags.add(DummyScenario.model_fields["krknctl_name"].default)
    return sorted(tag for tag in tags if tag)


def requirements_response() -> dict[str, Any]:
    return {
        "scenarioTags": scenario_tags(),
        "workloadImageTags": dict(DEFAULT_WORKLOAD_IMAGE_TAGS),
    }


def _active_private_scenarios(config: ConfigFile) -> list[tuple[str, str]]:
    active = set(ScenarioFactory.list_scenarios(config))
    return [
        (config_name, scenario_type.model_fields["krknctl_name"].default)
        for config_name, scenario_type in scenario_specs
        if (config_name, scenario_type) in active
    ]


def image_dependency_errors(config: ConfigFile, context: RegistryContext) -> list[str]:
    errors: list[str] = []
    active = _active_private_scenarios(config)
    baseline_tag = DummyScenario.model_fields["krknctl_name"].default
    if config.baseline.enable and baseline_tag not in context.inventory.available_tags:
        errors.append(f"scenario image '{baseline_tag}' is unavailable")
    for _config_name, tag in active:
        if tag not in context.inventory.available_tags:
            errors.append(f"scenario image '{tag}' is unavailable")
    return errors


def filter_discovery_scenarios(
    scenario_enables: dict[str, bool] | None,
    context: RegistryContext,
) -> tuple[dict[str, bool] | None, list[str]]:
    if scenario_enables is None:
        return None, []
    available = context.inventory.available_tags
    baseline_tag = DummyScenario.model_fields["krknctl_name"].default
    if baseline_tag not in available:
        raise ValueError(f"Private discovery requires baseline image '{baseline_tag}'.")
    filtered = dict(scenario_enables)
    warnings = []
    for config_name, scenario_type in scenario_specs:
        tag = scenario_type.model_fields["krknctl_name"].default
        if filtered.get(config_name, False) and tag not in available:
            filtered[config_name] = False
            warnings.append(
                f"Disabled {config_name}: private registry is missing "
                f"scenario image '{tag}'."
            )
    return filtered, warnings
