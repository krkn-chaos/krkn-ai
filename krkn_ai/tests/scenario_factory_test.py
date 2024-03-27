import unittest

from krkn_ai.abc.ai_scenario import AIScenario
from krkn_ai.scenarios.scenario_factory import ScenarioFactory


class ScenarioFactoryTest(unittest.TestCase):
    def test_create_instance(self):
        factory = ScenarioFactory("krkn_ai.tests")

        instance = factory.get_instance("DummyScenario", "/tmp/vector_db_test")
        self.assertTrue(instance.get_vector_db_path(), "/tmp/vector_db_test")
