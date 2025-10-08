from enum import Enum
from pydantic import BaseModel, PrivateAttr
from krkn_ai.models.cluster_components import ClusterComponents
from typing import Any


class BaseParameter(BaseModel):
    name: str
    value: Any
    krknctl_name: str = ""

    def get_name(self):
        if self.krknctl_name != "":
            return self.krknctl_name
        return self.name

    def get_value(self):
        return self.value


class BaseScenario(BaseModel):
    name: str


class Scenario(BaseScenario):

    # Private attribute doesn't appear when serializing, but lets us keep referene 
    _cluster_components: ClusterComponents = PrivateAttr()

    def __init__(self, **data):
        cluster_components = data.pop("cluster_components")
        super().__init__(**data)
        self._cluster_components = cluster_components

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
        return hash(tuple([self.scenario_a, self.scenario_b]))
