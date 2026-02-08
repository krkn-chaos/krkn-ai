"""
Anomaly Detector for Krkn-AI Dashboard

Automatically detects anomalies in experiment results.
"""

from typing import Dict, List, Any
import statistics
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


class AnomalyDetector:
    """Detects anomalies in Krkn-AI experiment data."""

    def __init__(self, data: Dict[str, Any], sensitivity: float = 2.0):
        """
        Initialize AnomalyDetector.

        Args:
            data: Aggregated experiment data
            sensitivity: Standard deviation multiplier for anomaly detection (default: 2.0)
        """
        self.data = data
        self.sensitivity = sensitivity
        self.anomalies: List[Dict[str, Any]] = []

    def detect_all(self) -> List[Dict[str, Any]]:
        """
        Detect all types of anomalies.

        Returns:
            List of detected anomalies
        """
        logger.info("Detecting anomalies with sensitivity=%.1f", self.sensitivity)

        self.anomalies = []
        self._detect_fitness_drops()
        self._detect_health_check_failures()
        self._detect_response_time_spikes()
        self._detect_success_rate_drops()

        logger.info("Detected %d anomalies", len(self.anomalies))
        return sorted(self.anomalies, key=lambda x: x.get("severity", 0), reverse=True)

    def _detect_fitness_drops(self):
        """Detect sudden drops in fitness scores."""
        gen_stats = self.data.get("statistics", {}).get("generation_stats", [])
        if len(gen_stats) < 2:
            return

        for i in range(1, len(gen_stats)):
            prev_best = gen_stats[i - 1]["best"]
            curr_best = gen_stats[i]["best"]

            if prev_best > 0:
                drop_percent = ((prev_best - curr_best) / prev_best) * 100

                if drop_percent > 10:  # More than 10% drop
                    self.anomalies.append({
                        "type": "fitness_drop",
                        "severity": min(10, int(drop_percent / 5)),
                        "generation": gen_stats[i]["generation"],
                        "message": f"Fitness score dropped by {drop_percent:.1f}% in generation {gen_stats[i]['generation']}",
                        "details": {
                            "previous_score": prev_best,
                            "current_score": curr_best,
                            "drop_percentage": drop_percent,
                        },
                    })

    def _detect_health_check_failures(self):
        """Detect health check failures."""
        health_checks = self.data.get("health_checks", [])
        if not health_checks:
            return

        # Group by application
        app_stats = {}
        for check in health_checks:
            app = check["application"]
            if app not in app_stats:
                app_stats[app] = {"total_success": 0, "total_failure": 0}

            app_stats[app]["total_success"] += check.get("success_count", 0)
            app_stats[app]["total_failure"] += check.get("failure_count", 0)

        # Report applications with high failure rates
        for app, stats in app_stats.items():
            total = stats["total_success"] + stats["total_failure"]
            if total > 0:
                failure_rate = (stats["total_failure"] / total) * 100
                if failure_rate > 20:  # More than 20% failure rate
                    self.anomalies.append({
                        "type": "health_check_failure",
                        "severity": min(10, int(failure_rate / 10)),
                        "application": app,
                        "message": f"Health check failures detected for '{app}' ({failure_rate:.1f}% failure rate)",
                        "details": {
                            "success_count": stats["total_success"],
                            "failure_count": stats["total_failure"],
                            "failure_rate": failure_rate,
                        },
                    })

    def _detect_response_time_spikes(self):
        """Detect unusual response time spikes."""
        health_checks = self.data.get("health_checks", [])
        if len(health_checks) < 10:
            return

        response_times = [h["response_time"] for h in health_checks if h["success"]]
        if not response_times:
            return

        mean_rt = statistics.mean(response_times)
        try:
            stdev_rt = statistics.stdev(response_times)
        except statistics.StatisticsError:
            return

        threshold = mean_rt + (self.sensitivity * stdev_rt)

        # Find spikes
        spikes = [h for h in health_checks if h["response_time"] > threshold]

        if spikes:
            # Group by application
            app_spikes = {}
            for spike in spikes:
                app = spike["application"]
                if app not in app_spikes:
                    app_spikes[app] = []
                app_spikes[app].append(spike)

            for app, spike_list in app_spikes.items():
                max_spike = max(spike_list, key=lambda x: x["response_time"])
                self.anomalies.append({
                    "type": "response_time_spike",
                    "severity": min(10, int((max_spike["response_time"] / mean_rt) * 2)),
                    "application": app,
                    "message": f"Response time spike detected for '{app}' ({max_spike['response_time']:.2f}s vs avg {mean_rt:.2f}s)",
                    "details": {
                        "max_response_time": max_spike["response_time"],
                        "average_response_time": mean_rt,
                        "spike_count": len(spike_list),
                        "threshold": threshold,
                    },
                })

    def _detect_success_rate_drops(self):
        """Detect drops in overall success rate."""
        stats = self.data.get("statistics", {})
        success_rate = stats.get("success_rate", 100)

        if success_rate < 90:  # Less than 90% success rate
            severity = int((100 - success_rate) / 5)
            self.anomalies.append({
                "type": "low_success_rate",
                "severity": min(10, severity),
                "message": f"Low experiment success rate: {success_rate:.1f}%",
                "details": {
                    "success_rate": success_rate,
                    "total_scenarios": stats.get("total_scenarios", 0),
                },
            })
