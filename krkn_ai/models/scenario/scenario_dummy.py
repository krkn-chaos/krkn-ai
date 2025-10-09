from krkn_ai.models.scenario.base import Scenario
from krkn_ai.models.scenario.parameters import *


class DummyScenario(Scenario):
    name: str = "dummy-scenario"
    end: DummyParameter = DummyParameter(name="END", value=10)
    exit_status: DummyParameter = DummyParameter(name="EXIT_STATUS", value=0)

    def __init__(self, **data):
        super().__init__(**data)

    @property
    def parameters(self):
        return [
            self.end,
            self.exit_status,
        ]

    def mutate(self):
        pass
