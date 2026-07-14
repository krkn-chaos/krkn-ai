from enum import Enum
from pydantic import BaseModel, PrivateAttr
from krkn_ai.models.cluster_components import ClusterComponents
from typing import Any


class BaseParameter(BaseModel):
    krknctl_name: str = ""  # Name of parameter in krknctl
    krknhub_name: str = ""  # Name of parameter in krknhub

    value: Any  # Value of parameter that is going to be passed to krknctl or krknhub

    def get_name(self, return_krknhub_name: bool = False):
        if return_krknhub_name:
            return self.krknhub_name
        return self.krknctl_name

    def get_value(self):
        return self.value


class BaseScenario(BaseModel):
    name: str
    krknctl_name: str  # Name of the scenario in krknctl
    krknhub_image: str  # Image of the scenario in krknhub


class Scenario(BaseScenario):
    # Private attribute doesn't appear when serializing, but lets us keep referene
    _cluster_components: ClusterComponents = PrivateAttr()

    def __init__(self, **data):
        cluster_components = data.pop("cluster_components")
        super().__init__(**data)
        self._cluster_components = cluster_components

    def scenario_wait_duration(self, config_wait_duration: int) -> int:
        return config_wait_duration

    def __str__(self):
        param_value = ", ".join([str(x.value) for x in self.parameters])
        return f"{self.name}({param_value})"

    def __eq__(self, other):
        if not isinstance(other, Scenario):
            return NotImplemented
        self_params = ", ".join([str(x.value) for x in self.parameters])
        other_params = ", ".join([str(x.value) for x in other.parameters])
        return self.name == other.name and self_params == other_params

    def __hash__(self):
        self_params = ", ".join([str(x.value) for x in self.parameters])
        return hash((self.name, self_params))


class CompositeDependency(Enum):
    A_ON_B = 1
    B_ON_A = 2
    NONE = 0


class CompositeScenario(BaseScenario):
    name: str = "composite-scenario"
    # No associated krknctl and krknhub images as these are custom composite scenarios.
    krknctl_name: str = ""
    krknhub_image: str = ""
    scenario_a: BaseScenario
    scenario_b: BaseScenario
    dependency: CompositeDependency

    def __str__(self):
        return f"{self.name}"

    def __eq__(self, other):
        if not isinstance(other, CompositeScenario):
            return NotImplemented
        return self.name == other.name and hash(other) == hash(self)

    def __hash__(self):
        # `dependency` changes the execution graph, so it is part of identity.
        # __eq__ derives from this hash, so including it here fixes both. See #380.
        return hash((self.scenario_a, self.scenario_b, self.dependency))
