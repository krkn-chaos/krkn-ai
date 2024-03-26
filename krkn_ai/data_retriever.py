import datetime
import json
import logging
import os.path
import shutil
import threading
import time
from multiprocessing import Lock
from queue import Queue
from typing import Callable, Optional, TextIO

import requests
import shortuuid


class DataRetriever:
    def __init__(
        self,
        api_url: str,
        api_username: str,
        api_password: str,
        threads: int,
        dataset_path: str,
    ):
        self.api_url = api_url
        self.api_username = api_username
        self.api_password = api_password
        self.threads = threads
        self.dataset_path = dataset_path
        self.max_retries = 5
        self.csv_separator = ";"

    def get_telemetry_urls(self, lock_timestamp: int = None) -> list[str]:
        response = requests.get(
            url=f"{self.api_url}/ai/telemetry",
            auth=(self.api_username, self.api_password),
            params=(
                {"after_timestamp": lock_timestamp} if lock_timestamp else None
            ),
        )

        if response.status_code != 200:
            error_message = (
                f"failed to send telemetry to {self.api_url}/ai/telemetry"
                f"with error: {response.status_code} - "
                f"{str(response.content)}"
            )
            logging.error(error_message)
            raise Exception(error_message)

        urls = json.loads(response.content.decode("utf-8"))
        return urls

    def __download_telemetry_file_worker(
        self,
        queue: Queue,
        console_lock: Lock,
        queue_size: int,
        download_path: str,
        update_callback: Callable[[int, Lock], None] = None,
        error_callback: Callable[[str, Lock], None] = None,
    ):
        while not queue.empty():
            data_tuple = queue.get()
            file_url = data_tuple[0]
            retry = data_tuple[1]
            filename = f"{download_path}/telemetry-{shortuuid.uuid()}.json"
            try:
                with requests.get(file_url, stream=True) as r:
                    with open(filename, "wb") as f:
                        shutil.copyfileobj(r.raw, f)
                if update_callback:
                    update_callback(queue_size, console_lock)
            except Exception as e:
                if retry >= self.max_retries:
                    message = f"impossible to download {file_url}, error: {e}, retry later."
                else:
                    queue.put((file_url, retry + 1))
                    message = f"failed to download {file_url}, error: {e} retry number {retry}"

                if error_callback:
                    error_callback(
                        message,
                        console_lock,
                    )
                else:
                    logging.error(message)
            finally:
                queue.task_done()

    def get_lock_timestamp(self) -> Optional[int]:
        pass

    def lock(self):
        pass

    def download_telemetry_data(
        self,
        urls: list[str],
        console_lock: Lock,
        update_callback: Callable[[int, Lock], None] = None,
        error_callback: Callable[[str, Lock], None] = None,
    ) -> str:
        download_path = f"{self.dataset_path}/{int(time.time())}"
        if not os.path.exists(download_path):
            os.mkdir(download_path)
        queue = Queue()
        for url in urls:
            queue.put((url, 0))
        for _ in range(self.threads):
            worker = threading.Thread(
                target=self.__download_telemetry_file_worker,
                args=(
                    queue,
                    console_lock,
                    len(urls),
                    download_path,
                    update_callback,
                    error_callback,
                ),
            )
            worker.daemon = True
            worker.start()
        queue.join()
        return download_path

    def __normalize_scenario_exit_code_worker(
        self,
        queue: Queue,
        file_lock: Lock,
        console_lock: Lock,
        queue_size: int,
        output_file_stream: TextIO,
        update_callback: Callable[[int, Lock], None] = None,
        error_callback: [[str, Lock], None] = None,
    ):
        while not queue.empty():
            try:
                filename = queue.get()
                with open(filename, "r") as stream:
                    json_object = json.load(stream)
                    for scenario in json_object["scenarios"]:
                        node_selector = None
                        namespace = None
                        if (
                            isinstance(scenario["parameters"], list)
                            and "config" in scenario["parameters"][0]
                        ):
                            namespace = scenario["parameters"][0]["config"][
                                "namespace_pattern"
                            ]

                        elif "input_list" in scenario["parameters"]:
                            if (
                                "node_selector"
                                in scenario["parameters"]["input_list"][0]
                            ):
                                node_selector = ",".join(
                                    f'{k}="{v}"'
                                    for k, v in scenario["parameters"][
                                        "input_list"
                                    ][0]["node_selector"].items()
                                )

                            if (
                                "namespace"
                                in scenario["parameters"]["input_list"][0]
                            ):
                                namespace = scenario["parameters"][
                                    "input_list"
                                ][0]["namespace"]

                        row = (
                            f'{scenario["scenario"]}{self.csv_separator}'
                            f'{scenario["exit_status"]}{self.csv_separator}'
                            f'{namespace if namespace else "null"}{self.csv_separator}'
                            f'{node_selector if node_selector else "null"}'
                        )

                        with file_lock:
                            output_file_stream.write(f"{row}\n")
                            output_file_stream.flush()
                            if update_callback:
                                update_callback(queue_size, console_lock)

            except Exception as e:
                message = f"impossible to parse file: {e}"
                if error_callback:
                    error_callback(message, console_lock)
                else:
                    logging.error(message)
            finally:
                queue.task_done()

    def normalize_scenario_exit_code_data(
        self,
        file_path: str,
        console_lock: Lock,
        update_callback: Callable[[int, Lock], None] = None,
        error_callback: [[str, Lock], None] = None,
    ) -> str:
        queue = Queue()
        file_lock = Lock()
        try:
            json_files = os.listdir(file_path)
            [queue.put(f"{file_path}/{file}") for file in json_files]
            queue_size = queue.qsize()
            csv_file = f"{file_path}/scenario_exit_code_data.csv"
            with open(csv_file, "a") as output_file_stream:
                csv_columns = [
                    "Chaos Scenario",
                    "Exit Status",
                    "Cluster Namespace",
                    "Node Selector",
                ]

                csv_header = self.csv_separator.join(csv_columns)
                output_file_stream.write(f"{csv_header}\n")
                output_file_stream.flush()

                for _ in range(self.threads):
                    worker = threading.Thread(
                        target=self.__normalize_scenario_exit_code_worker,
                        args=(
                            queue,
                            file_lock,
                            console_lock,
                            queue_size,
                            output_file_stream,
                            update_callback,
                            error_callback,
                        ),
                    )
                    worker.daemon = True
                    worker.start()
                queue.join()
            return csv_file

        except Exception as e:
            message = f"failed to parse telemetry data: {e}"
            if error_callback:
                error_callback(message, console_lock)
            else:
                logging.error(message)
