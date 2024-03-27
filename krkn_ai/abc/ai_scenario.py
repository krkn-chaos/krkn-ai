from abc import ABC, abstractmethod
from multiprocessing import Lock
from typing import Callable

from krkn_ai.abc.ai_model import AIModel


class AIScenario(ABC):

    @abstractmethod
    def __init__(self, model: AIModel, vector_db_path: str):
        pass

    @abstractmethod
    def normalize_data(
        self,
        data_path: str,
        threads: int,
        console_lock: Lock = None,
        console_update_callback: Callable[[int, Lock], None] = None,
        console_error_callback: [[str, Lock], None] = None,
    ) -> str:
        pass

    @abstractmethod
    def train(self, normalized_file_path: str):
        pass

    @abstractmethod
    def interactive_prompt(self):
        pass

    @staticmethod
    def query(self, question: str) -> str:
        pass

    @abstractmethod
    def get_vector_db_path(self) -> str:
        pass
