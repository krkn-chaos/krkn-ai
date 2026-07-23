from krkn_ai.models.scenario.base import Scenario, CompositeScenario, CompositeDependency
from krkn_ai.chaos_engines.composite import _expand_composite_json

class MockScenario(Scenario):
    name: str = "mock"
    krknctl_name: str = "mock-scenario"
    krknhub_image: str = "mock-image"
    
    @property
    def parameters(self):
        return []

def test_expand_composite_json_b_on_a_nested_composite():
    """Test that B_ON_A with a nested CompositeScenario correctly assigns key_a as the dependency. (#411)"""
    s1 = MockScenario(cluster_components=None)
    s2 = MockScenario(cluster_components=None)
    s3 = MockScenario(cluster_components=None)
    
    nested = CompositeScenario(
        scenario_a=s2,
        scenario_b=s3,
        dependency=CompositeDependency.NONE,
        cluster_components=None
    )
    
    parent = CompositeScenario(
        scenario_a=s1,
        scenario_b=nested,
        dependency=CompositeDependency.B_ON_A,
        cluster_components=None
    )
    
    result = _expand_composite_json(parent, root="$")
    
    # Expected keys:
    # parent key_a -> "$l"
    # parent key_b -> "$r"
    # nested key_a -> "$rl"
    # nested key_b -> "$rr"
    
    assert "$l" in result
    assert "$rl" in result
    assert "$rr" in result
    
    # Since dependency is B_ON_A, scenario_b (nested) gets passed depends_on="$l".
    # Because nested has NONE dependency between its children, it injects a dummy root "$r".
    # The dummy root "$r" should depend on "$l".
    # Both nested children "$rl" and "$rr" should depend on the dummy root "$r".
    assert result["$r"].get("depends_on") == "$l"
    assert result["$rl"].get("depends_on") == "$r"
    assert result["$rr"].get("depends_on") == "$r"
