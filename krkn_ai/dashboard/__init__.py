"""
Krkn-AI Dashboard Module

Generate interactive HTML dashboards from Krkn-AI experiment results.
"""

from krkn_ai.dashboard.generator import DashboardGenerator
from krkn_ai.dashboard.aggregator import DataAggregator
from krkn_ai.dashboard.anomaly_detector import AnomalyDetector

__all__ = ["DashboardGenerator", "DataAggregator", "AnomalyDetector"]
