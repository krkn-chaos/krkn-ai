import json
import logging
import os
import threading
from queue import Queue
from multiprocessing import Lock
from typing import Callable, TextIO

from langchain_community.document_loaders.csv_loader import CSVLoader
from langchain_community.vectorstores.chroma import Chroma
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

from krkn_ai.abc.ai_model import AIModel
from krkn_ai.abc.ai_scenario import AIScenario


class ExitCodeScenario(AIScenario):

    def __init__(self, model: AIModel, vector_db_path: str):
        self.model = model
        self.vector_db_path = vector_db_path
        self.csv_separator = ";"

    def get_vector_db_path(self) -> str:
        return self.vector_db_path

    def train(self, normalized_file_path: str):
        loader = CSVLoader(file_path=normalized_file_path)
        data = loader.load()
        self.vectorstore = Chroma.from_documents(
            data,
            self.model.get_embeddings(),
            persist_directory=self.vector_db_path,
        )

    def interactive_prompt(self):
        retriever = self.vectorstore.as_retriever()
        template = """Answer like a human, each of the items in the following JSON documents represents a latency test result,
        where each sample is surrounded by brackets. The lower average latency in the JSON represents the better result.
        context: {context}

        Question: {question}
        """

        prompt = ChatPromptTemplate.from_template(template)
        chain = (
            {"context": retriever, "question": RunnablePassthrough()}
            | prompt
            | self.model.get_llm()
            | StrOutputParser()
        )

        while True:
            query = input("Ask me anything about the metrics collected: ")
            output = chain.invoke(query)
            print(output)

    def normalize_data(
        self,
        data_path: str,
        threads: int,
        console_lock: Lock = None,
        console_update_callback: Callable[[int, Lock], None] = None,
        console_error_callback: [[str, Lock], None] = None,
    ) -> str:
        queue = Queue()
        file_lock = Lock()
        try:
            json_files = os.listdir(data_path)
            for file in json_files:
                queue.put(f"{data_path}/{file}")
            queue_size = queue.qsize()
            csv_file = f"{data_path}/scenario_exit_code_data.csv"
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

                for _ in range(threads):
                    worker = threading.Thread(
                        target=self.__normalize_scenario_exit_code_worker,
                        args=(
                            queue,
                            file_lock,
                            console_lock,
                            queue_size,
                            output_file_stream,
                            console_update_callback,
                            console_error_callback,
                        ),
                    )
                    worker.daemon = True
                    worker.start()
                queue.join()
            return csv_file

        except Exception as e:
            message = f"failed to parse telemetry data: {e}"
            if console_error_callback and console_lock:
                console_error_callback(message, console_lock)
            else:
                logging.error(message)

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
            filename = queue.get()
            try:
                with open(filename, "r") as stream:
                    json_object = json.load(stream)
                    for scenario in json_object["scenarios"]:
                        node_selector = None
                        namespace = None
                        if (
                            isinstance(scenario["parameters"], list)
                            and "config" in scenario["parameters"][0]
                            and (
                                "namespace"
                                in scenario["parameters"][0]["config"]
                                or "namespace_pattern"
                                in scenario["parameters"][0]["config"]
                            )
                        ):
                            if (
                                "namespace_pattern"
                                in scenario["parameters"][0]["config"]
                            ):
                                namespace = scenario["parameters"][0]["config"][
                                    "namespace_pattern"
                                ]
                            if (
                                "namespace"
                                in scenario["parameters"][0]["config"]
                            ):
                                namespace = scenario["parameters"][0]["config"][
                                    "namespace"
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
                            f'{scenario["exit_status"] if "exit_status" in scenario else scenario["exitStatus"]}{self.csv_separator}'
                            f'{namespace if namespace else "null"}{self.csv_separator}'
                            f'{node_selector if node_selector else "null"}'
                        )

                        with file_lock:
                            output_file_stream.write(f"{row}\n")
                            output_file_stream.flush()
                            if update_callback and console_lock:
                                update_callback(queue_size, console_lock)

            except Exception as e:
                message = f"impossible to parse file: {e} {filename}"
                if error_callback and console_lock:
                    error_callback(message, console_lock)
                else:
                    logging.error(message)
            finally:
                queue.task_done()
