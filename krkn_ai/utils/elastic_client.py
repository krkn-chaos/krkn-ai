"""
Elasticsearch integration utilities for Krkn-AI.
Handles sending run results, fitness scores, and genetic algorithm data to Elasticsearch.
"""

import logging
from krkn_ai.models.config import ElasticConfig
from krkn_ai.models.app import CommandRunResult
from krkn_ai.models.config import ConfigFile
from krkn_ai.utils.logger import get_logger

from krkn_lib.elastic.krkn_elastic import KrknElastic

logger = get_logger(__name__)


class ElasticSearchClient:
    """
    Client for sending Krkn-AI data to Elasticsearch.
    """

    def __init__(self, config: ElasticConfig):
        """
        Initialize Elasticsearch client.

        Args:
            config: Elasticsearch configuration
        """
        self.config = config

        # Hack to prevent any logging from KrknElastic client
        null_logger = logging.getLogger("null")
        null_logger.addHandler(logging.NullHandler())

        self.client = None
        if self.config.enable:
            try:
                self.client = KrknElastic(
                    safe_logger=null_logger,
                    elastic_url=self.config.server,
                    elastic_port=self.config.port,
                    username=self.config.username,
                    password=self.config.password,
                    verify_certs=self.config.verify_certs,
                )
                self.__test_connection()
                logger.info(
                    "Elasticsearch client initialized: %s:%s",
                    self.config.server,
                    self.config.port,
                )
            except Exception as e:
                logger.error("Failed to initialize Elasticsearch client: %s", e)
                logger.warning("Skipping Elasticsearch indexing")
                self.client = None
        else:
            logger.info("Elasticsearch indexing is disabled")

    def __test_connection(self) -> bool:
        if self.client is None:
            return False
        es_info = self.client.es.info()
        return es_info is not None and "version" in es_info

    def __handle_index_status(self, value: int):
        if value == -1 or value == 0:
            logger.error("Failed to index Krkn-AI data into Elasticsearch.")
            return False
        logger.debug("Elasticsearch data indexed successfully in %s seconds.", value)
        return True

    def index_config(self, config: ConfigFile, run_uuid: str) -> bool:
        """
        Index the configuration file into krkn-ai "config" index in Elasticsearch.

        Args:
            config: Configuration file to index

        Returns:
            True if successful, False otherwise
        """

        if not self.config.enable or self.client is None:
            logger.debug(
                "Elasticsearch indexing is disabled. Skipping indexing of test configuration info."
            )
            return False

        INDEX_NAME = f"{self.config.index}-config"

        config_data = config.model_dump(
            mode="json",
            include={
                "generations",
                "population_size",
                "duration",
                "wait_duration",
                "mutation_rate",
                "scenario_mutation_rate",
                "crossover_rate",
                "composition_rate",
                "population_injection_rate",
                "population_injection_size",
                "fitness_function",
                "health_checks",
                "scenario",
                "cluster_components",
            },
        )
        config_data["run_uuid"] = run_uuid

        status = self.client.upload_data_to_elasticsearch(
            item=config_data, index=INDEX_NAME
        )
        return self.__handle_index_status(status)

    def index_run_summary(self, summary: dict, run_uuid: str) -> bool:
        """
        Index the end-of-run summary into the krkn-ai "summary" index in Elasticsearch.

        Args:
            summary: Dict produced by JSONSummaryReporter.generate_summary()
            run_uuid: Unique identifier for this run

        Returns:
            True if successful, False otherwise
        """
        if not self.config.enable or self.client is None:
            logger.debug(
                "Elasticsearch indexing is disabled. Skipping indexing of run summary."
            )
            return False

        INDEX_NAME = f"{self.config.index}-summary"
        summary["run_uuid"] = run_uuid

        status = self.client.upload_data_to_elasticsearch(
            item=summary, index=INDEX_NAME
        )
        return self.__handle_index_status(status)

    def index_run_result(self, result: CommandRunResult, run_uuid: str) -> bool:
        """
        Index the run result into krkn-ai "results" index in Elasticsearch.

        Args:
            result: Run result to index
            run_uuid: Unique identifier for the entire Krkn-AI run

        Returns:
            True if successful, False otherwise
        """

        if not self.config.enable or self.client is None:
            logger.debug(
                "Elasticsearch indexing is disabled. Skipping indexing of run result."
            )
            return False

        INDEX_NAME = f"{self.config.index}-results"

        result_data = result.model_dump(
            mode="json",
            include={
                "generation_id",
                "scenario_id",
                "cmd",
                "returncode",
                "start_time",
                "end_time",
                "fitness_result",
                "health_check_results",
                "run_uuid",
            },
        )
        result_data["krkn_ai_run_uuid"] = run_uuid  # Link to parent config for the test
        result_data["scenario"] = result.scenario.name

        status = self.client.upload_data_to_elasticsearch(
            item=result_data, index=INDEX_NAME
        )
        return self.__handle_index_status(status)
