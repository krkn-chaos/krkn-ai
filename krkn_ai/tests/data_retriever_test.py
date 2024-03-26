import logging
import threading
import unittest
from multiprocessing import Lock
from typing import Callable

from krkn_ai.data_retriever import DataRetriever


class DataRetrieverTest(unittest.TestCase):
    downloaded = []

    def update_callback(
        self, message: str, counter: list[int], total: int, lock: Lock
    ):
        with lock:
            counter.append(1)
            print(f"{message} {len(counter)}/{total}")

    def error_callback(self, message: str, lock: Lock):
        print(f"[ERROR]: {message}")

    def test_data_download(self):
        retriever = DataRetriever("http://localhost:5000", "", "", 5, "/tmp")
        shared_lock = Lock()
        # lambda wrapper
        update_callback_download: Callable[[int, Lock], None] = (
            lambda total, lock: self.update_callback(
                "downloaded: ", self.downloaded, total, lock
            )
        )

        update_callback_normalize: Callable[[int, Lock], None] = (
            lambda total, lock: self.update_callback(
                "file parsed: ", self.downloaded, total, lock
            )
        )

        error_callback = self.error_callback
        urls = retriever.get_telemetry_urls(1710000000)
        print("starting test...")
        download_path = retriever.download_telemetry_data(
            urls, shared_lock, update_callback_download, error_callback
        )

        self.assertEqual(len(urls), len(self.downloaded))
        self.downloaded.clear()
        csv_file = retriever.normalize_scenario_exit_code_data(
            download_path,
            shared_lock,
            update_callback_normalize,
            error_callback,
        )

        print(csv_file)
