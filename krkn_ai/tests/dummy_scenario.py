from krkn_ai.abc.ai_scenario import AIScenario


class DummyScenario(AIScenario):

    def get_vector_db_path(self) -> str:
        return self.vector_db_path

    def __init__(self, vector_db_path: str):
        self.vector_db_path = vector_db_path

    def train(self, normalized_file_path: str):
        print("training on : {vectordb_path}")

    def interactive_prompt(self):
        print("hello!")
