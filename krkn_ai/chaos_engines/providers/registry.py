from typing import Dict, Type
from krkn_ai.chaos_engines.base import ChaosProvider
from krkn_ai.chaos_engines.providers.kraken_cli import KrakenCliProvider
from krkn_ai.chaos_engines.providers.kraken_hub import KrakenHubProvider
from krkn_ai.chaos_engines.providers.mock import MockProvider
from krkn_ai.chaos_engines.providers.shell import ShellProvider


class ProviderRegistry:
    """
    Registry for all available chaos providers.
    """

    _providers: Dict[str, Type[ChaosProvider]] = {
        "kraken-cli": KrakenCliProvider,
        "kraken-hub": KrakenHubProvider,
        "mock": MockProvider,
        "shell": ShellProvider,
    }

    @classmethod
    def get_provider_class(cls, name: str) -> Type[ChaosProvider]:
        if name not in cls._providers:
            raise ValueError(f"Provider '{name}' not found in registry.")
        return cls._providers[name]

    @classmethod
    def list_providers(cls) -> list:
        return list(cls._providers.keys())
