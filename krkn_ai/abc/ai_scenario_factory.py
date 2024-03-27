from abc import ABC, abstractmethod

from krkn_ai.abc.ai_scenario import AIScenario


class AIScenarioFactory(ABC):

    @abstractmethod
    def __init__(self, package_name: str):
        pass

    @abstractmethod
    def create_ai_scenario(
        self, ai_scenario_name: str, vector_db_path: str
    ) -> AIScenario:
        pass
