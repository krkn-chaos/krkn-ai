import importlib

from krkn_ai.abc.ai_model import AIModel
from krkn_ai.abc.ai_scenario import AIScenario


class ScenarioFactory:

    def get_instance(
        self,
        ai_model: AIModel,
        ai_scenario_class_name: str,
        ai_scenario_package: str,
        vector_db_path: str,
    ) -> AIScenario:
        try:
            module = importlib.import_module(ai_scenario_package)
            klass = getattr(module, ai_scenario_class_name)
            obj = klass(ai_model, vector_db_path)
            if not isinstance(obj, AIScenario):
                raise TypeError(
                    f"{ai_scenario_class_name} does not implement AIScenario Abstract class"
                )
            return obj
        except AttributeError as e:
            raise AttributeError(
                f"{ai_scenario_class_name} scenario not found in {ai_scenario_package}"
            )
