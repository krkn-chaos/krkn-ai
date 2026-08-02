import datetime
from enum import Enum
from typing import Dict, List, Optional, Union
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
    AnyHttpUrl,
)
import krkn_ai.constants as const
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.utils import id_generator


class ParameterValue(BaseModel):
    value: str
    is_private: bool = False

    @model_serializer
    def serialize(self) -> str:
        return "***" if self.is_private else self.value

    @classmethod
    def from_cli(cls, key: str, raw: str) -> "ParameterValue":
        return cls(value=raw, is_private=key.startswith("__"))


class PodScenarioConfig(BaseModel):
    enable: bool = False


class AppOutageScenarioConfig(BaseModel):
    enable: bool = False


class ContainerScenarioConfig(BaseModel):
    enable: bool = False


class NodeHogScenarioConfig(BaseModel):
    enable: bool = False


class TimeScenarioConfig(BaseModel):
    enable: bool = False


class NetworkScenarioConfig(BaseModel):
    enable: bool = False


class DnsOutageScenarioConfig(BaseModel):
    enable: bool = False


class SynFloodScenarioConfig(BaseModel):
    enable: bool = False


class PVCScenarioConfig(BaseModel):
    enable: bool = False


class KubevirtScenarioConfig(BaseModel):
    enable: bool = False


class StorageThrottleScenarioConfig(BaseModel):
    enable: bool = False


class ServiceDisruptionScenarioConfig(BaseModel):
    enable: bool = False


class BaselineConfig(BaseModel):
    enable: bool = True
    duration: int = Field(default=60 * 2, gt=0)


class ScenarioConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    application_outages: Optional[AppOutageScenarioConfig] = Field(
        alias="application-outages", default=None
    )
    pod_scenarios: Optional[PodScenarioConfig] = Field(
        alias="pod-scenarios", default=None
    )
    container_scenarios: Optional[ContainerScenarioConfig] = Field(
        alias="container-scenarios", default=None
    )
    node_cpu_hog: Optional[NodeHogScenarioConfig] = Field(
        alias="node-cpu-hog", default=None
    )
    node_memory_hog: Optional[NodeHogScenarioConfig] = Field(
        alias="node-memory-hog", default=None
    )
    node_io_hog: Optional[NodeHogScenarioConfig] = Field(
        alias="node-io-hog", default=None
    )
    time_scenarios: Optional[TimeScenarioConfig] = Field(
        alias="time-scenarios", default=None
    )
    network_scenarios: Optional[NetworkScenarioConfig] = Field(
        alias="network-scenarios", default=None
    )
    dns_outage: Optional[DnsOutageScenarioConfig] = Field(
        alias="dns-outage", default=None
    )
    syn_flood: Optional[SynFloodScenarioConfig] = Field(alias="syn-flood", default=None)
    pvc_scenarios: Optional[PVCScenarioConfig] = Field(
        alias="pvc-scenarios", default=None
    )
    kubevirt_scenarios: Optional[KubevirtScenarioConfig] = Field(
        alias="kubevirt-scenarios", default=None
    )
    storage_throttle: Optional[StorageThrottleScenarioConfig] = Field(
        alias="storage-throttle", default=None
    )
    service_disruption: Optional[ServiceDisruptionScenarioConfig] = Field(
        alias="service-disruption", default=None
    )


class FitnessFunctionType(str, Enum):
    point = "point"
    range = "range"


class SelectionStrategy(str, Enum):
    roulette = "roulette"
    tournament = "tournament"


auto_id = id_generator()


class FitnessFunctionItem(BaseModel):
    id: int = Field(default_factory=lambda: next(auto_id))
    query: str
    type: FitnessFunctionType = FitnessFunctionType.point
    weight: float = 1.0

    @field_validator("weight", mode="after")
    @classmethod
    def is_percent(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError(f"{value} is outside the range [0.0, 1.0]")
        return value


class FitnessFunction(BaseModel):
    query: Union[str, None] = None
    type: FitnessFunctionType = FitnessFunctionType.point
    include_krkn_failure: bool = True
    include_health_check_failure: bool = True
    include_health_check_response_time: bool = True
    items: List[FitnessFunctionItem] = []

    @model_validator(mode="after")
    def check_fitness_definition_exists(self):
        if self.query is None and len(self.items) == 0:
            raise ValueError(
                "Please define at least one fitness function in query or items."
            )
        return self


class HealthCheckApplicationConfig(BaseModel):
    name: str
    url: AnyHttpUrl
    status_code: int = 200
    timeout: int = 4
    interval: int = 2
    headers: Optional[Dict[str, str]] = None


class HealthCheckConfig(BaseModel):
    stop_watcher_on_failure: bool = False
    stop_timeout: float = Field(default=5.0, ge=0)
    applications: List[HealthCheckApplicationConfig] = []
    headers: Optional[Dict[str, str]] = None


class OutputConfig(BaseModel):
    result_name_fmt: str = "scenario_%s.yaml"
    graph_name_fmt: str = "scenario_%s.png"
    log_name_fmt: str = "scenario_%s.log"

    @field_validator("result_name_fmt", "graph_name_fmt", "log_name_fmt", mode="after")
    @classmethod
    def requires_scenario_id_placeholder(cls, value: str, info) -> str:
        if "%s" not in value:
            field_name = info.field_name
            raise ValueError(
                f"{field_name} must include the %s (scenario ID) placeholder "
                f"so every scenario produces a uniquely named file. "
                f"Got: '{value}'. Please check the '{field_name}' parameter "
                f"in your krkn-ai config file."
            )
        return value


class ElasticConfig(BaseModel):
    enable: bool = False
    server: Optional[AnyHttpUrl] = None
    port: int = 9200
    username: str = ""
    password: str = Field(exclude=True, default="")
    index: str = "krkn-ai-metrics"
    verify_certs: bool = True

    @model_validator(mode="after")
    def server_required_when_enabled(self) -> "ElasticConfig":
        if self.enable and self.server is None:
            raise ValueError(
                "ElasticConfig.server must be set when enable=True. "
                "Please provide a valid Elasticsearch URL."
            )
        return self


class HealthCheckResult(BaseModel):
    name: str
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now().isoformat())
    response_time: float
    status_code: int
    success: bool
    error: Optional[str] = None


class AdaptiveMutation(BaseModel):
    enable: bool = False
    min: float = Field(default=0.05, ge=0.0, le=1.0)
    max: float = Field(default=0.9, ge=0.0, le=1.0)
    threshold: float = 0.1
    generations: int = Field(default=5, gt=0)

    @model_validator(mode="after")
    def validate_min_less_than_max(self):
        if self.enable and self.min >= self.max:
            raise ValueError(
                f"adaptive_mutation.min ({self.min}) must be less than "
                f"adaptive_mutation.max ({self.max})"
            )
        return self


class StoppingCriteria(BaseModel):
    fitness_threshold: Optional[float] = None
    generation_saturation: Optional[int] = None
    exploration_saturation: Optional[int] = None
    saturation_threshold: float = 0.0001

    @field_validator("generation_saturation", "exploration_saturation", mode="after")
    @classmethod
    def validate_positive_int(cls, value: Optional[int], info) -> Optional[int]:
        if value is not None and value <= 0:
            field_name = info.field_name
            raise ValueError(
                f"{field_name} must be a positive integer greater than 0. "
                f"Please check the '{field_name}' parameter in your krkn-ai config file."
            )
        return value


class AlgorithmType(str, Enum):
    genetic = "genetic"


class GeneticAlgorithmConfig(BaseModel):
    generations: Optional[int] = 20
    duration: Optional[int] = None
    population_size: int = Field(default=10, ge=2)
    elitism_count: int = Field(default=1, ge=0)
    mutation_rate: float = Field(default=const.MUTATION_RATE, ge=0.0, le=1.0)
    scenario_mutation_rate: float = Field(
        default=const.SCENARIO_MUTATION_RATE, ge=0.0, le=1.0
    )
    crossover_rate: float = Field(default=const.CROSSOVER_RATE, ge=0.0, le=1.0)
    composition_rate: float = Field(default=0, ge=0.0, le=1.0)
    selection_strategy: SelectionStrategy = SelectionStrategy.roulette
    tournament_size: int = Field(default=3, ge=1)
    population_injection_rate: float = Field(
        default=const.POPULATION_INJECTION_RATE, ge=0.0, le=1.0
    )
    population_injection_size: int = Field(
        default=const.POPULATION_INJECTION_SIZE, ge=1
    )
    adaptive_mutation: AdaptiveMutation = AdaptiveMutation()
    stopping_criteria: StoppingCriteria = StoppingCriteria()

    @field_validator("generations", "duration", mode="after")
    @classmethod
    def validate_positive_when_set(cls, value: Optional[int], info) -> Optional[int]:
        if value is not None and value <= 0:
            raise ValueError(
                f"{info.field_name} must be a positive integer when set, got {value}"
            )
        return value

    @model_validator(mode="after")
    def validate_elitism_count(self):
        if self.elitism_count > self.population_size:
            raise ValueError("elitism_count cannot exceed population_size")
        return self


class ConfigFile(BaseModel):
    kubeconfig_file_path: str
    parameters: Dict[str, ParameterValue] = {}
    seed: Optional[int] = None
    wait_duration: int = Field(default=const.WAIT_DURATION, ge=0)
    fitness_function: FitnessFunction
    health_checks: HealthCheckConfig = HealthCheckConfig()
    baseline: BaselineConfig = BaselineConfig()
    scenario: ScenarioConfig = ScenarioConfig()
    allow_dangerous_scenarios: bool = False
    output: OutputConfig = OutputConfig()
    elastic: Optional[ElasticConfig] = Field(default_factory=ElasticConfig)
    cluster_components: ClusterComponents
    algorithm: AlgorithmType = AlgorithmType.genetic
    genetic: GeneticAlgorithmConfig = GeneticAlgorithmConfig()

    @model_validator(mode="before")
    @classmethod
    def migrate_flat_algorithm_fields(cls, data):
        if not isinstance(data, dict):
            return data
        if "algorithm" not in data:
            data["algorithm"] = "genetic"
        if "genetic" not in data:
            ga_data = {}
            for field in GeneticAlgorithmConfig.model_fields:
                if field in data:
                    ga_data[field] = data.pop(field)
            if ga_data:
                data["genetic"] = ga_data
        return data
