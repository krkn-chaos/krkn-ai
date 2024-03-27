from langchain_community.embeddings.ollama import OllamaEmbeddings
from langchain_community.llms.ollama import Ollama
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseLLM

from krkn_ai.abc.ai_model import AIModel


class KrknOllama(AIModel):

    def __init__(self, end_point: str, model_name: str):
        self.end_point = end_point
        self.model_name = model_name

        self.embeddings = OllamaEmbeddings(
            base_url=self.end_point, model=self.model_name
        )

        self.llm = Ollama(base_url=self.end_point, model=self.model_name)

    def get_embeddings(self) -> Embeddings:
        return self.embeddings

    def get_llm(self) -> BaseLLM:
        return self.llm
