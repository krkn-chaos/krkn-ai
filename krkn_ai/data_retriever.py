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
    lock_file = "krkn-ai.lock"

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
        self.lock(download_path)
        return download_path

    def get_lock_path(self) -> Optional[str]:
        if not os.path.exists(self.lock_file):
            return None
        with open(self.lock_file, "r") as file:
            lock = file.read()
            return lock.strip()

    def lock(self, lock_path: str):
        with open(self.lock_file, "w") as file:
            file.write(lock_path)
