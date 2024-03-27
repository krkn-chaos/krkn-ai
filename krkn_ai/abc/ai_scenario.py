from abc import ABC, abstractmethod


class AIScenario(ABC):

    @abstractmethod
    def __init__(self, vector_db_path: str):
        pass

    @abstractmethod
    def train(self, normalized_data_path: str):
        pass

    @abstractmethod
    def prompt(self):
        pass

    @abstractmethod
    def get_vector_db_path(self) -> str:
        pass
