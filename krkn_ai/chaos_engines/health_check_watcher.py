"""
This module is used to run health checks for the application URLs and keep track of the results.

Working Details:
1. Asynchronous health check for each URL.
2. Keep track of the results in a list.
3. Once there is signal from main thread that the test is complete, or in case the api status check fails, then the watcher stops.
4. Return the results to the main thread by seperate method.
"""

from collections import defaultdict
import threading
import time
import requests
from typing import Dict, List, Optional, Tuple
import numpy as np

from krkn_ai.utils.logger import get_logger
from krkn_ai.utils.fs import preprocess_param_string
from krkn_ai.models.config import (
    HealthCheckApplicationConfig,
    HealthCheckConfig,
    HealthCheckResult,
    ParameterValue,
)

logger = get_logger(__name__)


class HealthCheckWatcher:
    def __init__(
        self,
        config: HealthCheckConfig,
        params: Optional[Dict[str, ParameterValue]] = None,
    ):
        self.config = config
        self._params = {k: v.value for k, v in (params or {}).items()}
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self._results_lock = threading.Lock()
        self._thread_results: Dict[int, Tuple[str, List[HealthCheckResult]]] = {}

    def run(self):
        # Start a thread for each health check
        logger.debug(
            f"Starting health check watcher for {len(self.config.applications)} applications"
        )
        for health_check in self.config.applications:
            t = threading.Thread(
                target=self.run_health_check,
                args=(health_check,),
                daemon=True,
                name=f"health-check-{health_check.name}",
            )
            t.start()
            self._threads.append(t)

    def _resolve_headers(self, app: HealthCheckApplicationConfig) -> dict:
        merged = {**(self.config.headers or {}), **(app.headers or {})}
        return {k: preprocess_param_string(v, self._params) for k, v in merged.items()}

    def run_health_check(self, health_check: HealthCheckApplicationConfig):
        # Each thread gets its own private results list
        thread_id = threading.current_thread().ident
        if thread_id is None:
            return  # Skip if thread ID is None (should not happen in normal operation)
        thread_results: List[HealthCheckResult] = []
        with self._results_lock:
            self._thread_results[thread_id] = (health_check.url, thread_results)

        resolved_headers = self._resolve_headers(health_check)

        # Simple polling loop, stops when stop() is called
        while not self._stop_event.is_set():
            try:
                resp = requests.get(
                    health_check.url,
                    headers=resolved_headers,
                    timeout=health_check.timeout,
                )
                status = resp.status_code
                success = status == health_check.status_code
                error = None
            except Exception as e:
                status = -1
                success = False
                resp = None
                error = str(e)

            result = HealthCheckResult(
                name=health_check.name,
                status_code=status,
                success=success,
                error=error,
                response_time=resp.elapsed.total_seconds() if resp is not None else -1,
            )

            with self._results_lock:
                thread_results.append(result)

            if not success and self.config.stop_watcher_on_failure:
                self._stop_event.set()
                break

            if self._stop_event.wait(health_check.interval):
                break

    def stop(self):
        logger.debug("Stopping health check watcher")
        self._stop_event.set()
        deadline = time.monotonic() + self.config.stop_timeout
        for t in self._threads:
            timeout = max(0.0, deadline - time.monotonic())
            t.join(timeout=timeout)
            if t.is_alive():
                logger.warning(
                    "Health check worker thread %s is still running after %.2f seconds; "
                    "continuing shutdown",
                    t.name,
                    self.config.stop_timeout,
                )

    def get_results(self) -> Dict[str, List[HealthCheckResult]]:
        """Aggregate a stable snapshot of collected health check results."""
        results = defaultdict(list)

        with self._results_lock:
            snapshots = [
                (url, list(thread_results))
                for url, thread_results in self._thread_results.values()
            ]

        for url, thread_results in snapshots:
            results[url].extend(thread_results)

        return dict(results)

    def summarize_success_rate(
        self, results: Dict[str, List[HealthCheckResult]]
    ) -> float:
        """
        Overall fail score across different URL results
        """
        # Flatten all results from all URLs into a single list
        all_results = []
        for result_list in results.values():
            all_results.extend(result_list)

        total = len(all_results)
        if total == 0:
            return 0
        failed = sum(1 for r in all_results if not r.success)
        score = (failed / total) * 10
        logger.debug(f"Health check failure rate score: {score}")
        return score

    def summarize_response_time(
        self, health_check_results: Dict[str, List[HealthCheckResult]]
    ) -> float:
        score: float = 0.0
        total = 0
        for _, results in health_check_results.items():
            response_times = []
            for result in results:
                if result.success:
                    response_times.append(result.response_time)

            if len(response_times) < 4:  # Not enough data to calculate outliers
                continue  # Skip this URL, but continue processing remaining URLs

            q1 = np.percentile(response_times, 25)
            q3 = np.percentile(response_times, 75)
            iqr = q3 - q1
            upper_bound = q3 + (1.5 * iqr)

            outliers = [t for t in response_times if t > upper_bound]
            score += len(outliers)
            total += len(response_times)
        if total == 0:
            return 0.0
        score = (score / total) * 10.0
        logger.debug(f"Response time outlier score: {score}")
        return score
