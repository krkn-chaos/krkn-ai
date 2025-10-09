'''
This module is used to run health checks for the application URLs and keep track of the results.

Working Details:
1. Asynchronous health check for each URL.
2. Keep track of the results in a list.
3. Once there is signal from main thread that the test is complete, or in case the api status check fails, then the watcher stops.
4. Return the results to the main thread by seperate method.
'''

from collections import defaultdict
import threading
import time
import requests
from typing import List, Dict
import numpy as np

from krkn_ai.utils.logger import get_module_logger
from krkn_ai.models.config import HealthCheckApplicationConfig, HealthCheckConfig, HealthCheckResult

logger = get_module_logger(__name__)

class HealthCheckWatcher:
    def __init__(self, config: HealthCheckConfig):
        self.config = config
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        # Each thread stores results in its own list - ZERO contention!
        self._thread_results = {}

    def run(self):
        # Start a thread for each health check
        logger.debug(f"Starting health check watcher for {len(self.config.applications)} applications")
        for health_check in self.config.applications:
            t = threading.Thread(target=self.run_health_check, args=(health_check,))
            t.start()
            self._threads.append(t)

    def run_health_check(self, health_check: HealthCheckApplicationConfig):
        # Each thread gets its own private results list
        thread_id = threading.current_thread().ident
        thread_results = []
        self._thread_results[thread_id] = (health_check.url, thread_results)
        
        # Simple polling loop, stops when stop() is called
        while not self._stop_event.is_set():
            try:
                resp = requests.get(health_check.url, timeout=health_check.timeout)
                status = resp.status_code
                success = (status == 200)
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
                response_time=resp.elapsed.total_seconds() if resp is not None else -1
            )
            
            # Store in thread-private list - NO LOCKS, NO CONTENTION!
            thread_results.append(result)

            if not success and self.config.stop_watcher_on_failure:
                self._stop_event.set()
                break

            time.sleep(health_check.interval)

    def stop(self):
        logger.debug(f"Stopping health check watcher")
        self._stop_event.set()
        for t in self._threads:
            t.join()

    def get_results(self) -> Dict[str, List[HealthCheckResult]]:
        """Aggregate results from all threads - called after threads complete"""
        results = defaultdict(list)
        
        # Each thread has its own URL and results list
        for url, thread_results in self._thread_results.values():
            results[url].extend(thread_results)
                
        return dict(results)

    def summarize_success_rate(self, results: Dict[str, List[HealthCheckResult]]) -> float:
        '''
        Overall fail score across different URL results
        '''
        # Flatten all results from all URLs into a single list
        all_results = []
        for result_list in results.values():
            all_results.extend(result_list)
        
        total = len(all_results)
        if total == 0:
            return 0
        failed = sum(1 for r in all_results if not r.success)
        score = (failed / total) * 10 
        logger.debug(f"Success rate score: {score}")
        return score
    
    def summarize_response_time(self, health_check_results: Dict[str, List[HealthCheckResult]]) -> float:
        score = 0
        total = 0
        for _, results in health_check_results.items():
            response_times = []
            for result in results:
                if result.success:
                    response_times.append(result.response_time)
            
            if len(response_times) < 4: # Not enough data to calculate outliers
                return 0

            q1 = np.percentile(response_times, 25)
            q3 = np.percentile(response_times, 75)
            iqr = q3 - q1
            upper_bound = q3 + (1.5 * iqr)
            
            outliers = [t for t in response_times if t > upper_bound]
            score += len(outliers)
            total += len(results)
        if total == 0:
            return 0
        score = (score / total) * 10
        logger.debug(f"Response time score: {score}")
        return score
