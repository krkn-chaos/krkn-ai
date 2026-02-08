"""
Dashboard Generator for Krkn-AI

Generates interactive HTML dashboards from experiment results.
"""

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
from krkn_ai.utils.logger import get_logger
from krkn_ai.dashboard.aggregator import DataAggregator
from krkn_ai.dashboard.anomaly_detector import AnomalyDetector

logger = get_logger(__name__)


class DashboardGenerator:
    """Generates interactive HTML dashboards from Krkn-AI results."""

    def __init__(self, results_dir: str):
        """
        Initialize DashboardGenerator.

        Args:
            results_dir: Path to Krkn-AI results directory
        """
        self.results_dir = Path(results_dir)
        self.aggregator = DataAggregator(results_dir)
        self.data: Dict[str, Any] = {}
        self.anomalies: list = []

    def generate(self, output_path: str) -> str:
        """
        Generate interactive dashboard.

        Args:
            output_path: Path where HTML dashboard will be saved

        Returns:
            Path to generated dashboard
        """
        logger.info("Generating dashboard from %s", self.results_dir)

        # Aggregate data
        self.data = self.aggregator.aggregate_all()

        # Detect anomalies
        detector = AnomalyDetector(self.data)
        self.anomalies = detector.detect_all()

        # Generate HTML
        html_content = self._generate_html()

        # Write to file
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info("Dashboard generated: %s", output_file)
        return str(output_file)

    def _generate_html(self) -> str:
        """Generate complete HTML content."""
        template_path = Path(__file__).parent / "templates" / "dashboard.html"

        if template_path.exists():
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
        else:
            # Use embedded template
            template = self._get_embedded_template()

        # Inject data
        html = template.replace(
            "/*DATA_PLACEHOLDER*/",
            f"const dashboardData = {json.dumps(self.data, indent=2)};\n"
            f"const anomaliesData = {json.dumps(self.anomalies, indent=2)};"
        )

        return html

    def _get_embedded_template(self) -> str:
        """Get embedded HTML template."""
        # This will be replaced by the actual template file
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Krkn-AI Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/papaparse@5.4.1/papaparse.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js"></script>
    <style>
        /* Styles will be in template file */
    </style>
</head>
<body>
    <div id="dashboard">
        <h1>Krkn-AI Dashboard</h1>
        <div id="content">Loading...</div>
    </div>
    <script>
        /*DATA_PLACEHOLDER*/
        // Dashboard logic will be in template file
    </script>
</body>
</html>
"""
