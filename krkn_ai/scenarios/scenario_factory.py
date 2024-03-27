import importlib

from krkn_ai.abc.ai_scenario import AIScenario
from krkn_ai.abc.ai_scenario_factory import AIScenarioFactory


class ScenarioFactory(AIScenarioFactory):
    def __init__(self, package_name: str):
        self.package_name = package_name

    def create_ai_scenario(
        self, ai_scenario_name: str, vector_db_path: str
    ) -> AIScenario:
        try:
            module = importlib.import_module(self.package_name)
            klass = getattr(module, ai_scenario_name)
            obj = klass(vector_db_path)
            if not isinstance(obj, AIScenario):
                raise Exception(
                    f"{ai_scenario_name} not found in package {self.package_name}"
                )
            return obj
        except Exception as e:
            raise e
