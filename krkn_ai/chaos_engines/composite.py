import json
import os
import tempfile

from krkn_ai.models.scenario.base import (
    Scenario,
    CompositeDependency,
    CompositeScenario,
)
from krkn_ai.models.scenario.factory import ScenarioFactory
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

KRKNCTL_GRAPH_RUN_TEMPLATE = "krknctl graph run {path} --kubeconfig {kubeconfig}"


def build_graph_command(
    scenario: CompositeScenario, kubeconfig_path: str, output_dir: str
) -> str:
    graph_json_directory = os.path.join(output_dir, "graphs")
    os.makedirs(graph_json_directory, exist_ok=True)

    scenario_json = _expand_composite_json(scenario)
    with tempfile.NamedTemporaryFile(
        suffix=".json",
        dir=graph_json_directory,
        delete=False,
        mode="w",
        encoding="utf-8",
    ) as f:
        json_file = f.name
        json.dump(scenario_json, f, ensure_ascii=False, indent=4)
    logger.info("Created scenario json in path: %s", json_file)

    command = KRKNCTL_GRAPH_RUN_TEMPLATE.format(
        path=json_file,
        kubeconfig=kubeconfig_path,
    )
    return command


def _expand_composite_json(
    scenario: CompositeScenario, root: str = "$", depends_on: str = None
):
    result = {}
    scenario_a = scenario.scenario_a
    scenario_b = scenario.scenario_b

    key_root = root
    key_a = root + "l"
    key_b = root + "r"

    if scenario.dependency == CompositeDependency.NONE:
        result[key_root] = _generate_scenario_json(
            ScenarioFactory.create_dummy_scenario(), depends_on=depends_on
        )

    if isinstance(scenario_a, CompositeScenario):
        key = None
        if scenario.dependency == CompositeDependency.A_ON_B:
            key = key_b
        elif scenario.dependency == CompositeDependency.B_ON_A:
            key = depends_on
        elif scenario.dependency == CompositeDependency.NONE:
            key = key_root

        result.update(_expand_composite_json(scenario_a, key_a, depends_on=key))
    elif isinstance(scenario_a, Scenario):
        key = None
        if scenario.dependency == CompositeDependency.A_ON_B:
            key = key_b
        elif scenario.dependency == CompositeDependency.B_ON_A:
            key = depends_on
        elif scenario.dependency == CompositeDependency.NONE:
            key = key_root

        result[key_a] = _generate_scenario_json(
            scenario_a,
            depends_on=key,
        )

    if isinstance(scenario_b, CompositeScenario):
        key = None
        if scenario.dependency == CompositeDependency.A_ON_B:
            key = depends_on
        elif scenario.dependency == CompositeDependency.B_ON_A:
            key = key_b
        elif scenario.dependency == CompositeDependency.NONE:
            key = key_root

        result.update(_expand_composite_json(scenario_b, key_b, depends_on=key))
    elif isinstance(scenario_b, Scenario):
        key = None
        if scenario.dependency == CompositeDependency.A_ON_B:
            key = depends_on
        elif scenario.dependency == CompositeDependency.B_ON_A:
            key = key_a
        elif scenario.dependency == CompositeDependency.NONE:
            key = key_root
        result[key_b] = _generate_scenario_json(
            scenario_b,
            depends_on=key,
        )

    return result


def _generate_scenario_json(scenario: Scenario, depends_on: str = None):
    env = {
        param.get_name(return_krknhub_name=True): str(param.get_value())
        for param in scenario.parameters
    }
    result = {
        "image": scenario.krknhub_image,
        "name": scenario.krknctl_name,
        "env": env,
    }
    if depends_on is not None:
        result["depends_on"] = depends_on
    return result
