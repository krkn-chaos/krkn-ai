import asyncio
import threading
import time
from typing import Dict, List, Optional
import numpy as np
import httpx

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
        self._results: Dict[str, List[HealthCheckResult]] = {
            app.url: [] for app in self.config.applications
        }
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._stop_requested = False
        self._lock = threading.Lock()

    def _resolve_headers(self, app: HealthCheckApplicationConfig) -> dict:
        merged = {**(self.config.headers or {}), **(app.headers or {})}
        return {k: preprocess_param_string(v, self._params) for k, v in merged.items()}

    async def _run_health_check(self, app_config: HealthCheckApplicationConfig):
        assert self._stop_event is not None
        resolved_headers = self._resolve_headers(app_config)
        async with httpx.AsyncClient() as client:
            while not self._stop_event.is_set():
                start_time = time.monotonic()
                try:
                    resp = await client.get(
                        app_config.url,
                        headers=resolved_headers,
                        timeout=app_config.timeout,
                    )
                    elapsed = time.monotonic() - start_time
                    status = resp.status_code
                    success = status == app_config.status_code
                    error = None
                except httpx.RequestError as e:
                    elapsed = time.monotonic() - start_time
                    status = -1
                    success = False
                    error = str(e)
                except Exception as e:
                    elapsed = time.monotonic() - start_time
                    status = -1
                    success = False
                    error = f"Unexpected error: {str(e)}"

                result = HealthCheckResult(
                    name=app_config.name,
                    status_code=status,
                    success=success,
                    error=error,
                    response_time=elapsed,
                )

                with self._lock:
                    self._results[app_config.url].append(result)

                if not success and self.config.stop_watcher_on_failure:
                    logger.warning(
                        f"Health check failed for {app_config.name} ({app_config.url}). Stopping watcher."
                    )
                    self._stop_event.set()
                    break

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=app_config.interval
                    )
                    break
                except asyncio.TimeoutError:
                    continue

    async def _run_all(self):
        tasks = [self._run_health_check(app) for app in self.config.applications]
        if tasks:
            await asyncio.gather(*tasks)

    def _start_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()
        if self._stop_requested:
            self._stop_event.set()
        try:
            self._loop.run_until_complete(self._run_all())
        finally:
            self._loop.close()

    def run(self):
        """Starts the health check watcher in a background thread with an asyncio loop."""
        logger.debug(
            f"Starting health check watcher for {len(self.config.applications)} applications"
        )
        self._thread = threading.Thread(target=self._start_loop)
        self._thread.start()

    def stop(self):
        """Stops the health check watcher and waits for the thread to finish."""
        self._stop_requested = True
        if self._loop and self._stop_event and self._loop.is_running():
            logger.debug("Stopping health check watcher")
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread:
            self._thread.join(timeout=5)

    def get_results(self) -> Dict[str, List[HealthCheckResult]]:
        """Returns the collected results."""
        with self._lock:
            return dict(self._results)

    def summarize_success_rate(
        self, results: Dict[str, List[HealthCheckResult]]
    ) -> float:
        """Overall fail score across different URL results"""
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
        """Calculates response time outlier score using IQR."""
        score: float = 0.0
        total = 0
        for _, results in health_check_results.items():
            response_times = [r.response_time for r in results if r.success]

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
