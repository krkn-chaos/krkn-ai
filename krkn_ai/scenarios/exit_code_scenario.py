from krkn_ai.abc.ai_scenario import AIScenario


class ExitCodeScenario(AIScenario):
    def __init__(self, vector_db_path: str):
        self.vector_db_path = vector_db_path

    def get_vector_db_path(self) -> str:
        return self.vector_db_path

    def prompt(self):
        pass

    def train(self, normalized_data_path: str):
        pass
