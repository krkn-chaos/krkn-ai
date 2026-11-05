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

    scenario_json, _ = _expand_composite_json(scenario)
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
) -> tuple[dict, str]:
    result = {}
    scenario_a = scenario.scenario_a
    scenario_b = scenario.scenario_b

    key_root = root
    key_a = root + "l"
    key_b = root + "r"
    
    terminal_key = None

    if scenario.dependency == CompositeDependency.NONE:
        result[key_root] = _generate_scenario_json(
            ScenarioFactory.create_dummy_scenario(), depends_on=depends_on
        )
        terminal_key = key_root

        if isinstance(scenario_a, CompositeScenario):
            nodes_a, _ = _expand_composite_json(scenario_a, key_a, depends_on=key_root)
            result.update(nodes_a)
        elif isinstance(scenario_a, Scenario):
            result[key_a] = _generate_scenario_json(scenario_a, depends_on=key_root)
        else:
            raise TypeError(f"Unsupported scenario type: {type(scenario_a)}")

        if isinstance(scenario_b, CompositeScenario):
            nodes_b, _ = _expand_composite_json(scenario_b, key_b, depends_on=key_root)
            result.update(nodes_b)
        elif isinstance(scenario_b, Scenario):
            result[key_b] = _generate_scenario_json(scenario_b, depends_on=key_root)
        else:
            raise TypeError(f"Unsupported scenario type: {type(scenario_b)}")

    elif scenario.dependency == CompositeDependency.A_ON_B:
        if isinstance(scenario_b, CompositeScenario):
            nodes_b, term_b = _expand_composite_json(scenario_b, key_b, depends_on=depends_on)
            result.update(nodes_b)
        elif isinstance(scenario_b, Scenario):
            result[key_b] = _generate_scenario_json(scenario_b, depends_on=depends_on)
            term_b = key_b
        else:
            raise TypeError(f"Unsupported scenario type: {type(scenario_b)}")
        
        if isinstance(scenario_a, CompositeScenario):
            nodes_a, term_a = _expand_composite_json(scenario_a, key_a, depends_on=term_b)
            result.update(nodes_a)
        elif isinstance(scenario_a, Scenario):
            result[key_a] = _generate_scenario_json(scenario_a, depends_on=term_b)
            term_a = key_a
        else:
            raise TypeError(f"Unsupported scenario type: {type(scenario_a)}")
            
        terminal_key = term_a

    elif scenario.dependency == CompositeDependency.B_ON_A:
        if isinstance(scenario_a, CompositeScenario):
            nodes_a, term_a = _expand_composite_json(scenario_a, key_a, depends_on=depends_on)
            result.update(nodes_a)
        elif isinstance(scenario_a, Scenario):
            result[key_a] = _generate_scenario_json(scenario_a, depends_on=depends_on)
            term_a = key_a
        else:
            raise TypeError(f"Unsupported scenario type: {type(scenario_a)}")
            
        if isinstance(scenario_b, CompositeScenario):
            nodes_b, term_b = _expand_composite_json(scenario_b, key_b, depends_on=term_a)
            result.update(nodes_b)
        elif isinstance(scenario_b, Scenario):
            result[key_b] = _generate_scenario_json(scenario_b, depends_on=term_a)
            term_b = key_b
        else:
            raise TypeError(f"Unsupported scenario type: {type(scenario_b)}")
            
        terminal_key = term_b
    else:
        raise ValueError(f"Unsupported dependency type: {scenario.dependency}")

    assert terminal_key is not None, "terminal_key must be resolved"
    return result, terminal_key


def _generate_scenario_json(scenario: Scenario, depends_on: str = None):
    env = {
        param.get_name(return_krknhub_name=True): str(
            param.get_value(return_krknhub_name=True)
        )
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
