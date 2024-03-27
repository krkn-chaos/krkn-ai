import logging
import sys
import time
from multiprocessing import Lock
from typing import Callable

import yaml
from yaspin import yaspin
from yaspin.core import Yaspin
from yaspin.spinners import Spinners

from krkn_ai.data_retriever import DataRetriever
from krkn_ai.llm.model_factory import ModelFactory
from krkn_ai.scenarios.scenario_factory import ScenarioFactory


def update_callback(
    console: Yaspin,
    message: str,
    counter: list[int],
    total: int,
    lock: Lock,
):
    with lock:
        counter.append(1)
        console.text = f"{message}: {len(counter)}/{total}"


def error_callback(console: Yaspin, message: str, lock: Lock):
    with lock:
        console.fail(message)


def main():
    config = {}

    try:
        with open("config/config.yaml", "r") as stream:
            config = yaml.safe_load(stream)
    except Exception as e:
        logging.error(f"failed to load config file: {e}")
        sys.exit(1)
    download_counter = []
    parse_counter = []
    console_lock = Lock()
    model_factory = ModelFactory()
    scenario_factory = ScenarioFactory()
    data_retriever = DataRetriever(
        config["telemetry"]["api_url"],
        config["telemetry"]["username"],
        config["telemetry"]["password"],
        config["krkn_ai"]["threads"],
        config["krkn_ai"]["dataset_path"],
    )

    with yaspin(text="Noise spinner", color="red") as sp:
        update_callback_download: Callable[[int, Lock], None] = (
            lambda total, lock: update_callback(
                sp, "downloaded: ", download_counter, total, lock
            )
        )

        update_callback_normalize: Callable[[int, Lock], None] = (
            lambda total, lock: update_callback(
                sp, "file parsed: ", parse_counter, total, lock
            )
        )

        error_callback_global: Callable[[str, Lock], None] = (
            lambda message, lock: error_callback(sp, message, lock)
        )
        sp.text = "fetching telemetry download links from API..."
        urls = data_retriever.get_telemetry_urls()
        sp.write(f"{len(urls)} urls fetched ✅")
        # data_path = data_retriever.download_telemetry_data(
        #     urls, console_lock, update_callback_download, error_callback_global
        # )
        sp.write(f"{len(urls)} files downloaded ✅")
        parsed_file = data_retriever.normalize_scenario_exit_code_data(
            # data_path,
            "/tmp/1711549998",
            console_lock,
            update_callback_normalize,
            error_callback_global,
        )
        sp.write(f"{len(urls)} files parsed ✅")

        sp.text = f"parsed file: {parsed_file}"

        # for scenario in config["krkn_ai"]["scenarios"]:
        #
        #     model = model_factory.get_instance(
        #         scenario["model"]["class_name"],
        #         scenario["model"]["package"],
        #         scenario["model"]["endpoint"],
        #         scenario["model"]["name"],
        #     )
        #     scenario = scenario_factory.get_instance(
        #         model,
        #         scenario["class_name"],
        #         scenario["package"],
        #         scenario["vector_db_path"],
        #     )


if __name__ == "__main__":
    main()
