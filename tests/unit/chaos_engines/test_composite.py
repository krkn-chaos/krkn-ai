from krkn_ai.models.scenario.base import CompositeDependency, CompositeScenario
from krkn_ai.models.scenario.factory import ScenarioFactory
from krkn_ai.chaos_engines.composite import _expand_composite_json


def test_expand_composite_json_b_on_a_nested():
    """
    Test that when a nested CompositeScenario is placed in scenario_b
    with a B_ON_A dependency, the nested root properly depends on key_a
    rather than causing a dangling pointer to itself (key_b).
    Resolves Issue #411.
    """
    # Create the nested composite for scenario_b
    nested_b = CompositeScenario(
        scenario_a=ScenarioFactory.create_dummy_scenario(),
        scenario_b=ScenarioFactory.create_dummy_scenario(),
        dependency=CompositeDependency.A_ON_B,
    )

    # Create the parent composite with B_ON_A dependency
    parent = CompositeScenario(
        scenario_a=ScenarioFactory.create_dummy_scenario(),
        scenario_b=nested_b,
        dependency=CompositeDependency.B_ON_A,
    )

    # Expand the JSON graph
    # Root key is "$"
    # key_a is "$l", key_b is "$r"
    result, _ = _expand_composite_json(parent, root="$")

    # In the result, we should see nodes for the nested B composite.
    # Because B depends on A, the nested B components should depend on key_a ("$l").

    # nested_b is "$r". Its A component is "$rl", its B component is "$rr".
    # nested_b has A_ON_B dependency.
    # So "$rl" should depend on "$rr".
    # And "$rr" (the root of the nested_b subtree) should depend on the parent's depends_on.
    # Since parent is B_ON_A, nested_b's depends_on is "$l" (key_a).

    assert "$l" in result
    assert "$rl" in result
    assert "$rr" in result

    # "$rl" (A of nested) depends on "$rr" (B of nested) because nested_b is A_ON_B
    assert result["$rl"]["depends_on"] == "$rr"
    assert result["$rr"]["depends_on"] == "$l"


def test_expand_composite_json_b_on_a_with_composite_a():
    """
    Test the edge case requested by AI reviewer:
    Parent has B_ON_A dependency, but scenario_a is a CompositeScenario
    with A_ON_B dependency. Ensure B depends on the *actual* terminal node
    of A (which is A's A component, i.e., "$ll"), and not the missing "$l".
    """
    nested_a = CompositeScenario(
        scenario_a=ScenarioFactory.create_dummy_scenario(),
        scenario_b=ScenarioFactory.create_dummy_scenario(),
        dependency=CompositeDependency.A_ON_B,
    )

    parent = CompositeScenario(
        scenario_a=nested_a,
        scenario_b=ScenarioFactory.create_dummy_scenario(),
        dependency=CompositeDependency.B_ON_A,
    )

    result, _ = _expand_composite_json(parent, root="$")

    # Assert every depends_on value exists in the graph (no dangling pointers)
    for key, node in result.items():
        if "depends_on" in node:
            assert node["depends_on"] in result, (
                f"Dangling pointer found: {node['depends_on']}"
            )

    # nested_a is A_ON_B, so "$ll" depends on "$lr"
    assert result["$ll"]["depends_on"] == "$lr"

    # parent is B_ON_A, so B ("$r") should depend on the terminal key of A ("$ll")
    assert result["$r"]["depends_on"] == "$ll"
