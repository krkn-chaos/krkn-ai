from typing import List, Optional
from pydantic import BaseModel, Field

class ScenarioTelemetry(BaseModel):
    exit_status: int
    scenario_name: Optional[str] = None

class TelemetryPayload(BaseModel):
    run_uuid: str
    scenarios: List[ScenarioTelemetry]

class KrknTelemetry(BaseModel):
    telemetry: TelemetryPayload
