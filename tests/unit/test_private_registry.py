import json
from unittest.mock import Mock, patch

import pytest
from krkn_ai.models.app import KrknRunnerType
from krkn_ai.models.config import ScenarioConfig

from krkn_ai.chaos_engines.krkn_runner import KrknRunner
from click.testing import CliRunner
from krkn_ai.cli.cmd import main

from krkn_ai.image_requirements import (
    DEFAULT_WORKLOAD_IMAGE_TAGS,
    filter_discovery_scenarios,
    image_dependency_errors,
    requirements_response,
    scenario_tags,
)
from krkn_ai.registry import (
    RegistryContext,
    registry_context_from_request,
    registry_context_from_sources,
)


@pytest.fixture(name="minimal_config")
def initialized_scenarios(minimal_config):
    # The shared fixture leaves optional scenario blocks unset.
    flags = {}
    for name in ScenarioConfig.model_fields:
        current = getattr(minimal_config.scenario, name)
        flags[name] = {"enable": current.enable if current else False}
    minimal_config.scenario = ScenarioConfig.model_validate(flags)
    return minimal_config


def _inventory(available_tags=None, workload_tags=None):
    return {
        "registryName": "managed",
        "repository": "registry.example.test/krkn/scenarios",
        "availableTags": list(
            available_tags if available_tags is not None else scenario_tags()
        ),
        "workloadImageTags": dict(
            workload_tags if workload_tags is not None else DEFAULT_WORKLOAD_IMAGE_TAGS
        ),
        "orchestratorImage": "registry.example.test/krkn/ai@sha256:" + "a" * 64,
        "resultUploaderImage": "registry.example.test/krkn/uploader@sha256:" + "b" * 64,
    }


def _context(inventory=None):
    return RegistryContext.create("managed", inventory or _inventory())


def test_requirements_catalog_lists_scenario_aliases_and_helper_defaults():
    requirements = requirements_response()

    assert requirements["scenarioTags"] == scenario_tags()
    assert "pod-network-filter" in requirements["scenarioTags"]
    assert "dummy-scenario" in requirements["scenarioTags"]
    assert requirements["workloadImageTags"] == DEFAULT_WORKLOAD_IMAGE_TAGS


def test_discovery_filters_scenarios_missing_private_scenario_images():
    context = _context(_inventory(available_tags=["pod-scenarios", "dummy-scenario"]))

    enabled, warnings = filter_discovery_scenarios(
        {"node_cpu_hog": True, "pod_scenarios": True}, context
    )

    assert enabled == {"node_cpu_hog": False, "pod_scenarios": True}
    assert warnings == [
        "Disabled node_cpu_hog: private registry is missing scenario image "
        "'node-cpu-hog'."
    ]


def test_private_helper_image_availability_does_not_filter_scenarios(minimal_config):
    minimal_config.scenario.node_cpu_hog.enable = True
    context = _context(
        _inventory(
            available_tags=["dummy-scenario", "pod-scenarios", "node-cpu-hog"],
            workload_tags={},
        )
    )

    enabled, warnings = filter_discovery_scenarios({"node_cpu_hog": True}, context)

    assert enabled == {"node_cpu_hog": True}
    assert warnings == []
    assert image_dependency_errors(minimal_config, context) == []


def test_runtime_context_rejects_selection_mismatch_and_missing_inventory():
    inventory = _inventory()
    inventory["registryName"] = "other"
    with pytest.raises(ValueError, match="does not match selection"):
        registry_context_from_request("managed", inventory)

    with pytest.raises(ValueError, match="requires KRKNAI_IMAGE_INVENTORY"):
        registry_context_from_sources(
            "managed", environ={"KRKNAI_OPERATOR_REGISTRY_NAME": "managed"}
        )

    with pytest.raises(
        ValueError, match="does not match KRKNAI_OPERATOR_REGISTRY_NAME"
    ):
        registry_context_from_sources(
            "other",
            environ={
                "KRKNAI_OPERATOR_REGISTRY_NAME": "managed",
                "KRKNAI_IMAGE_INVENTORY": json.dumps(_inventory()),
            },
        )


def test_private_registry_rejects_non_operator_runner(minimal_config):
    with pytest.raises(ValueError, match="only by the operator runner"):
        KrknRunner(
            minimal_config,
            "./output",
            KrknRunnerType.CLI_RUNNER,
            _context(),
        )


def test_runtime_context_reads_registry_inventory_without_config_leakage(
    minimal_config,
):
    context = registry_context_from_sources(
        None,
        environ={
            "KRKNAI_OPERATOR_REGISTRY_NAME": "managed",
            "KRKNAI_IMAGE_INVENTORY": json.dumps(_inventory()),
        },
    )

    assert context.registry_name == "managed"
    assert context.inventory.registry_name == "managed"
    assert "registryName" not in minimal_config.model_dump(mode="json")


def test_cli_passes_registry_selection_as_runtime_context(minimal_config, tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("not parsed by mocked config reader", encoding="utf-8")
    engine = Mock(cancelled=False, current_generation=0)

    with patch("krkn_ai.cli.cmd.read_config_from_file", return_value=minimal_config):
        with patch(
            "krkn_ai.cli.cmd.GeneticAlgorithm", return_value=engine
        ) as create_engine:
            result = CliRunner().invoke(
                main,
                [
                    "run",
                    "--config",
                    str(config_file),
                    "--output",
                    str(tmp_path / "output"),
                    "--runner-type",
                    "operator",
                    "--operator-registry-name",
                    "managed",
                ],
                env={"KRKNAI_IMAGE_INVENTORY": json.dumps(_inventory())},
            )

    assert result.exit_code == 0, result.output
    context = create_engine.call_args.kwargs["registry_context"]
    assert context.registry_name == "managed"
    assert "registryName" not in json.dumps(minimal_config.model_dump(mode="json"))


def test_discovery_rejects_missing_baseline_image():
    context = _context(_inventory(available_tags=["pod-scenarios"], workload_tags={}))
    with pytest.raises(ValueError, match="baseline image 'dummy-scenario'"):
        filter_discovery_scenarios({"pod_scenarios": True}, context)


def test_private_discovery_merge_disables_only_ineligible_scenarios(
    minimal_config, tmp_path
):
    import yaml
    from krkn_ai.utils.fs import save_discovery

    data = minimal_config.model_dump(mode="json", by_alias=True)
    data["scenario"]["node-cpu-hog"]["enable"] = True
    data["site_extension"] = {"keep": True}
    destination = tmp_path / "private.yaml"
    destination.write_text(yaml.safe_dump(data))
    save_discovery(
        str(destination),
        "merge",
        minimal_config.cluster_components,
        minimal_config.kubeconfig_file_path,
        scenario_enables={
            "node_cpu_hog": False,
            "pod_scenarios": True,
            "container_scenarios": True,
        },
    )
    merged = yaml.safe_load(destination.read_text())
    assert merged["scenario"]["node-cpu-hog"]["enable"] is False
    assert merged["scenario"]["pod-scenarios"]["enable"] is True
    assert merged["scenario"]["container-scenarios"]["enable"] is False
    assert merged["site_extension"] == {"keep": True}
