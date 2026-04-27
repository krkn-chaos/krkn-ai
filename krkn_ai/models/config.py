import datetime
from enum import Enum
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator
import krkn_ai.constants as const
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.utils import id_generator


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


class BaselineConfig(BaseModel):
    enable: bool = True
    duration: int = 60 * 2  # 2 minutes


class ScenarioConfig(BaseModel):
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


class FitnessFunctionType(str, Enum):
    point = "point"
    range = "range"


auto_id = id_generator()


class FitnessFunctionItem(BaseModel):
    id: int = Field(default_factory=lambda: next(auto_id))  # Auto-increment ID
    query: str  # PromQL
    type: FitnessFunctionType = FitnessFunctionType.point
    weight: float = 1.0

    @field_validator("weight", mode="after")
    @classmethod
    def is_percent(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError(f"{value} is outside the range [0.0, 1.0]")
        return value


class FitnessFunction(BaseModel):
    query: Union[str, None] = None  # PromQL
    type: FitnessFunctionType = FitnessFunctionType.point
    include_krkn_failure: bool = True
    include_health_check_failure: bool = True
    include_health_check_response_time: bool = True
    items: List[FitnessFunctionItem] = []

    @model_validator(mode="after")
    def check_fitness_definition_exists(self):
        """Validates whether there is at least one fitness function is defined."""
        if self.query is None and len(self.items) == 0:
            raise ValueError(
                "Please define at least one fitness function in query or items."
            )
        return self


class HealthCheckApplicationConfig(BaseModel):
    """
    Health check configuration for the application.
    This is used to check the health of the application.
    """

    name: str
    url: str
    status_code: int = 200  # Expected status code
    timeout: int = 4  # in seconds
    interval: int = 2  # in seconds


class HealthCheckConfig(BaseModel):
    stop_watcher_on_failure: bool = False
    applications: List[HealthCheckApplicationConfig] = []


class OutputConfig(BaseModel):
    """
    Configuration for output file naming formats.

    Supports parameterized string values:
    - %g: Generation ID
    - %s: Scenario ID
    - %c: Scenario Name (e.g: pod_scenarios)
    """

    result_name_fmt: str = "scenario_%s.yaml"
    graph_name_fmt: str = "scenario_%s.png"
    log_name_fmt: str = "scenario_%s.log"


class ElasticConfig(BaseModel):
    """
    Configuration for Elasticsearch integration.
    Stores Krkn-AI run results, fitness scores, and genetic algorithm configuration.
    """

    enable: bool = False  # Enable Elasticsearch integration
    server: str = ""  # Elasticsearch URL (e.g., https://elasticsearch.example.com)
    port: int = 9200  # Elasticsearch port
    username: str = ""  # Elasticsearch username
    password: str = Field(exclude=True, default="")  # Elasticsearch password
    index: str = "krkn-ai-metrics"  # Index name for storing Krkn-AI results
    verify_certs: bool = True  # Verify SSL certificates


class HealthCheckResult(BaseModel):
    name: str
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now().isoformat())
    response_time: float  # in seconds
    status_code: int  # actual status code
    success: bool  # True if status code is as expected
    error: Optional[str] = None  # Error message if the status code is not as expected


class AdaptiveMutation(BaseModel):
    enable: bool = False
    min: float = 0.05
    max: float = 0.9
    threshold: float = 0.1
    generations: int = 5


class StoppingCriteria(BaseModel):
    """
    Configuration for stopping criteria that control when the genetic algorithm terminates.

    Multiple criteria can be set simultaneously - the algorithm stops when ANY criterion is met.

    Attributes:
        fitness_threshold: Stop when best fitness score reaches or exceeds this value.
            Set to None to disable this criterion.
        generation_saturation: Stop if the best fitness score does not improve for this
            many consecutive generations. Set to None to disable this criterion.
        exploration_saturation: Stop if no new unique scenarios are discovered for this
            many consecutive generations (limit of exploration reached).
            Set to None to disable this criterion.
    """

    fitness_threshold: Optional[float] = None  # Stop when fitness score >= threshold
    generation_saturation: Optional[int] = (
        None  # Stop if no improvement for N generations
    )
    exploration_saturation: Optional[int] = (
        None  # Stop if no new scenarios for N generations
    )
    saturation_threshold: float = (
        0.0001  # Minimum improvement threshold for generation saturation
    )

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


class ConfigFile(BaseModel):
    kubeconfig_file_path: str  # Path to kubeconfig
    parameters: Dict[str, str] = {}

    seed: Optional[int] = None  # Optional: Random seed for reproducible runs

    generations: Optional[int] = (
        20  # Total number of generations to run. Ignored if duration is set.
    )
    population_size: int = 10  # Initial population size
    duration: Optional[int] = (
        None  # Maximum duration in seconds to run the algorithm. When set, generations is ignored and algorithm runs until duration is reached.
    )

    wait_duration: int = (
        const.WAIT_DURATION
    )  # Time to wait after each scenario run (Default: 120 seconds)

    mutation_rate: float = (
        const.MUTATION_RATE
    )  # How often mutation should occur for each scenario parameter (0.0-1.0)
    scenario_mutation_rate: float = (
        const.SCENARIO_MUTATION_RATE
    )  # How often scenario mutation should occur (0.0-1.0)
    crossover_rate: float = (
        const.CROSSOVER_RATE
    )  # How often crossover should occur for each scenario parameter (0.0-1.0)
    composition_rate: float = (
        0  # How often a crossover would lead to composition (0.0-1.0)
    )

    population_injection_rate: float = (
        const.POPULATION_INJECTION_RATE
    )  # How often a random samples gets added to new population (0.0-1.0)
    population_injection_size: int = (
        const.POPULATION_INJECTION_SIZE
    )  # What's the size of random samples that gets added to new population

    fitness_function: FitnessFunction
    health_checks: HealthCheckConfig = HealthCheckConfig()

    baseline: BaselineConfig = BaselineConfig()
    scenario: ScenarioConfig = ScenarioConfig()

    output: OutputConfig = OutputConfig()

    elastic: Optional[ElasticConfig] = Field(
        default_factory=ElasticConfig
    )  # Elasticsearch configuration

    cluster_components: ClusterComponents

    adaptive_mutation: AdaptiveMutation = AdaptiveMutation()

    stopping_criteria: StoppingCriteria = (
        StoppingCriteria()
    )  # Additional stopping criteria for the algorithm
