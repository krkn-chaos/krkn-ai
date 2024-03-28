import logging
import os.path
import shutil
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
        console.write(f"🚨 {message}")


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

    with yaspin(color="red") as sp:
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

        if (
            not config["krkn_ai"]["reuse_dataset"]
            or not data_retriever.get_lock_path()
        ):
            sp.text = "fetching telemetry download links from API..."
            if not data_retriever.get_lock_path():
                sp.write(
                    f"lock file not found forced to download training data...."
                )
            if config["krkn_ai"]["dataset_starting_timestamp"] > 0:
                urls = data_retriever.get_telemetry_urls(
                    config["krkn_ai"]["dataset_starting_timestamp"]
                )
            else:
                urls = data_retriever.get_telemetry_urls(
                    config["krkn_ai"]["dataset_starting_timestamp"]
                )
            sp.ok(f"{len(urls)} urls fetched ✅")
            data_path = data_retriever.download_telemetry_data(
                urls,
                console_lock,
                update_callback_download,
                error_callback_global,
            )
            sp.ok(f"{len(urls)} files downloaded ✅")
        else:
            lock_path = data_retriever.get_lock_path()
            sp.text = f"reusing dataset from lockfile {lock_path} ✅"
            data_path = lock_path

        for scenario_config in config["krkn_ai"]["scenarios"]:
            try:

                model = model_factory.get_instance(
                    scenario_config["model"]["class_name"],
                    scenario_config["model"]["package"],
                    scenario_config["model"]["endpoint"],
                    scenario_config["model"]["name"],
                )
                scenario = scenario_factory.get_instance(
                    model,
                    scenario_config["class_name"],
                    scenario_config["package"],
                    scenario_config["vector_db_path"],
                )
            except (TypeError, AttributeError) as e:
                sp.fail(
                    f"🚨 failed to run scenario {scenario_config['class_name']} : {e}"
                )
                continue
            if scenario_config["retrain"]:

                if os.path.exists(scenario.get_vector_db_path()):
                    sp.text = "deleting vector db..."
                    shutil.rmtree(scenario.get_vector_db_path())
                    sp.ok("vector db deleted ✅")

                parsed_file = scenario.normalize_data(
                    data_path,
                    config["krkn_ai"]["threads"],
                    console_lock,
                    update_callback_normalize,
                    error_callback_global,
                )
                sp.text = "creating embeddings and writing in the vectordb...."
                scenario.train(parsed_file)
                sp.ok(f"documents written in the vectordb ✅")

            try:
                sp.text = "starting llm interactive prompt..."
                scenario.interactive_prompt()
            except ValueError as e:
                sp.fail(f"🚨 failed to start interactive prompt : {e}")
                continue


if __name__ == "__main__":
    main()
