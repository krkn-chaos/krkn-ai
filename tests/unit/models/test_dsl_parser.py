from unittest.mock import MagicMock
from krkn_ai.models.scenario.dsl_parser import ScenarioDSLParser
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.scenario.base import Scenario, CompositeScenario


def test_dsl_parser_initialization():
    components = MagicMock(spec=ClusterComponents)
    parser = ScenarioDSLParser(components)
    assert "pod" in parser._type_map
    assert "network" in parser._type_map
    assert "cpu-hog" in parser._type_map


def test_parse_linear_chain():
    components = MagicMock(spec=ClusterComponents)
    parser = ScenarioDSLParser(components)

    # Mock the scenario classes
    mock_pod_cls = MagicMock()
    mock_pod_instance = MagicMock(spec=Scenario)
    mock_pod_instance.parameters = []
    mock_pod_instance.name = "Step 1"
    mock_pod_cls.return_value = mock_pod_instance

    mock_net_cls = MagicMock()
    mock_net_instance = MagicMock(spec=Scenario)
    mock_net_instance.parameters = []
    mock_net_instance.name = "Step 2"
    mock_net_cls.return_value = mock_net_instance

    parser._type_map["pod"] = mock_pod_cls
    parser._type_map["network"] = mock_net_cls

    recipe = {
        "name": "Test Chain",
        "steps": [
            {"name": "Step 1", "type": "pod", "parameters": {"namespace": "test-ns"}},
            {
                "name": "Step 2",
                "type": "network",
                "depends_on": "Step 1",
                "parameters": {"duration": 100},
            },
        ],
    }

    scenario = parser._build_recipe(recipe)
    assert isinstance(scenario, CompositeScenario)
    assert scenario.scenario_a.name == "Step 2"
    assert scenario.scenario_b.name == "Step 1"


def test_parse_dict_multiple():
    components = MagicMock(spec=ClusterComponents)
    parser = ScenarioDSLParser(components)

    mock_pod_cls = MagicMock()
    mock_pod_instance = MagicMock(spec=Scenario)
    mock_pod_instance.parameters = []
    mock_pod_instance.name = "S1"
    mock_pod_cls.return_value = mock_pod_instance

    mock_net_cls = MagicMock()
    mock_net_instance = MagicMock(spec=Scenario)
    mock_net_instance.parameters = []
    mock_net_instance.name = "S2"
    mock_net_cls.return_value = mock_net_instance

    parser._type_map["pod"] = mock_pod_cls
    parser._type_map["network"] = mock_net_cls

    data = {
        "recipes": [
            {"name": "Recipe 1", "steps": [{"name": "S1", "type": "pod"}]},
            {"name": "Recipe 2", "steps": [{"name": "S2", "type": "network"}]},
        ]
    }

    scenarios = parser.parse_dict(data)
    assert len(scenarios) == 2
    assert scenarios[0].name == "S1"
    assert scenarios[1].name == "S2"


def test_parse_with_depends_on():
    components = MagicMock(spec=ClusterComponents)
    parser = ScenarioDSLParser(components)

    mock_pod_cls = MagicMock()
    mock_pod_instance = MagicMock(spec=Scenario)
    mock_pod_instance.parameters = []
    mock_pod_instance.name = "Root Pod"
    mock_pod_cls.return_value = mock_pod_instance

    mock_net_cls = MagicMock()
    mock_net_instance = MagicMock(spec=Scenario)
    mock_net_instance.parameters = []
    mock_net_instance.name = "Dependent Network"
    mock_net_cls.return_value = mock_net_instance

    parser._type_map["pod"] = mock_pod_cls
    parser._type_map["network"] = mock_net_cls

    # S2 depends on S1, but defined in reverse order in list
    recipe = {
        "name": "Dependency Test",
        "steps": [
            {"name": "S2", "type": "network", "depends_on": "S1"},
            {"name": "S1", "type": "pod"},
        ],
    }

    scenario = parser._build_recipe(recipe)
    assert isinstance(scenario, CompositeScenario)
    assert scenario.scenario_a.name == "Dependent Network"  # S2
    assert scenario.scenario_b.name == "Root Pod"  # S1
