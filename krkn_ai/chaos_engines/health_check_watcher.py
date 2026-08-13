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
            self._thread_results[thread_id] = (str(health_check.url), thread_results)

        resolved_headers = self._resolve_headers(health_check)

        # Simple polling loop, stops when stop() is called
        while not self._stop_event.is_set():
            try:
                resp = requests.get(
                    str(health_check.url),
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
        """Score combining failure rate and consecutive-failure streak severity.

        failure_rate captures breadth (what fraction failed) while max_streak
        captures depth (how sustained the worst outage was).  A service with
        5/100 failures all in a row scores higher than 5/100 scattered.
        """
        all_results: List[HealthCheckResult] = []
        for result_list in results.values():
            all_results.extend(result_list)

        total = len(all_results)
        if total == 0:
            return 0.0

        failed = sum(1 for r in all_results if not r.success)
        failure_rate = failed / total

        current_streak = 0
        max_streak = 0
        for r in all_results:
            if not r.success:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        streak_ratio = max_streak / total

        score = (failure_rate + streak_ratio) / 2.0
        logger.debug(
            "Health check failure score: %.3f (rate=%.3f, streak=%d/%d)",
            score,
            failure_rate,
            max_streak,
            total,
        )
        return score

    def summarize_response_time(
        self,
        health_check_results: Dict[str, List[HealthCheckResult]],
        baseline_stats: Optional[Dict[str, Tuple[float, float]]] = None,
    ) -> float:
        """Score response-time degradation using CV + jitter, with optional
        baseline degradation bonus.

        Primary signal (always computed):
          CV  = stddev / mean  (relative variability)
          jitter = mean(|rt[i+1] - rt[i]|) / mean  (oscillation)
          variability_score = min((CV + jitter) * 0.25, 1.0)

        Additive bonus (when baseline_stats has data for the URL):
          degradation = (scenario_median - baseline_median) / max(MAD, 0.001)
          bonus = clamp(degradation, 0, 1)

        Returns the average per-URL score, capped at [0, 1].
        """
        url_scores: List[float] = []

        for url, results in health_check_results.items():
            response_times = [
                r.response_time for r in results if r.success and r.response_time >= 0
            ]
            if len(response_times) < 2:
                continue

            arr = np.array(response_times, dtype=float)
            mean_rt = float(np.mean(arr))
            if mean_rt <= 0:
                url_scores.append(0.0)
                continue

            cv = float(np.std(arr)) / mean_rt
            diffs = np.abs(np.diff(arr))
            jitter = float(np.mean(diffs)) / mean_rt if len(diffs) > 0 else 0.0
            variability_score = min((cv + jitter) * 0.25, 1.0)

            url_score = variability_score

            if baseline_stats is not None and url in baseline_stats:
                bl_median, bl_mad = baseline_stats[url]
                effective_mad = max(bl_mad, 0.001)
                scenario_median = float(np.median(arr))
                degradation = (scenario_median - bl_median) / effective_mad
                degradation_bonus = min(max(degradation, 0.0), 1.0)
                url_score = min(variability_score + degradation_bonus, 1.0)

            url_scores.append(url_score)

        if not url_scores:
            return 0.0
        score = float(np.mean(url_scores))
        logger.debug("Response time score: %.3f (%d URLs)", score, len(url_scores))
        return score


def compute_baseline_response_stats(
    health_check_results: Dict[str, List[HealthCheckResult]],
) -> Dict[str, Tuple[float, float]]:
    """Compute per-URL (median, MAD) from a baseline run's health check results."""
    stats: Dict[str, Tuple[float, float]] = {}
    for url, results in health_check_results.items():
        response_times = [
            r.response_time for r in results if r.success and r.response_time >= 0
        ]
        if len(response_times) < 2:
            continue
        arr = np.array(response_times, dtype=float)
        median = float(np.median(arr))
        mad = float(np.median(np.abs(arr - median)))
        stats[url] = (median, mad)
    return stats
