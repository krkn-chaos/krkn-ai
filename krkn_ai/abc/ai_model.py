from abc import ABC, abstractmethod

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseLLM


class AIModel(ABC):
    @abstractmethod
    def __init__(self, end_point: str, model_name: str):
        self.end_point = end_point
        self.model_name = model_name

    @abstractmethod
    def get_embeddings(self) -> Embeddings:
        pass

    @abstractmethod
    def get_llm(self) -> BaseLLM:
        pass
