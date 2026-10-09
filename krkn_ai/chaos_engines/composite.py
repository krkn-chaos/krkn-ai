import json
import os
import tempfile

from krkn_ai.chaos_engines.commands import es_env_vars
from krkn_ai.models.config import ElasticConfig
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
    scenario: CompositeScenario,
    kubeconfig_path: str,
    output_dir: str,
    elastic: ElasticConfig | None = None,
) -> str:
    graph_json_directory = os.path.join(output_dir, "graphs")
    os.makedirs(graph_json_directory, exist_ok=True)

    scenario_json = _expand_composite_json(scenario, elastic=elastic)
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
    scenario: CompositeScenario,
    root: str = "$",
    depends_on: str = None,
    elastic: ElasticConfig | None = None,
):
    result = {}
    scenario_a = scenario.scenario_a
    scenario_b = scenario.scenario_b

    key_root = root
    key_a = root + "l"
    key_b = root + "r"

    if scenario.dependency == CompositeDependency.NONE:
        result[key_root] = _generate_scenario_json(
            ScenarioFactory.create_dummy_scenario(),
            depends_on=depends_on,
            elastic=elastic,
        )

    if isinstance(scenario_a, CompositeScenario):
        key = None
        if scenario.dependency == CompositeDependency.A_ON_B:
            key = key_b
        elif scenario.dependency == CompositeDependency.B_ON_A:
            key = depends_on
        elif scenario.dependency == CompositeDependency.NONE:
            key = key_root

        result.update(
            _expand_composite_json(scenario_a, key_a, depends_on=key, elastic=elastic)
        )
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
            elastic=elastic,
        )

    if isinstance(scenario_b, CompositeScenario):
        key = None
        if scenario.dependency == CompositeDependency.A_ON_B:
            key = depends_on
        elif scenario.dependency == CompositeDependency.B_ON_A:
            key = key_b
        elif scenario.dependency == CompositeDependency.NONE:
            key = key_root

        result.update(
            _expand_composite_json(scenario_b, key_b, depends_on=key, elastic=elastic)
        )
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
            elastic=elastic,
        )

    return result


def _generate_scenario_json(
    scenario: Scenario,
    depends_on: str = None,
    elastic: ElasticConfig | None = None,
):
    env = {
        param.get_name(return_krknhub_name=True): str(
            param.get_value(return_krknhub_name=True)
        )
        for param in scenario.parameters
    }
    if elastic is not None and elastic.enable:
        env.update(es_env_vars(elastic))
    result = {
        "image": scenario.krknhub_image,
        "name": scenario.krknctl_name,
        "env": env,
    }
    if depends_on is not None:
        result["depends_on"] = depends_on
    return result
