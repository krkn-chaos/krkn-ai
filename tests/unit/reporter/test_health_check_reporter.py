"""
HealthCheckReporter unit tests
"""

import os
import pandas as pd
import datetime
from unittest.mock import patch, MagicMock

from krkn_ai.reporter.health_check_reporter import HealthCheckReporter
from krkn_ai.models.app import CommandRunResult, FitnessResult
from krkn_ai.models.config import HealthCheckResult
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.cluster_components import ClusterComponents


class TestHealthCheckReporter:
    """Test HealthCheckReporter core functionality"""

    def test_init_creates_output_directory(self, temp_output_dir):
        """Test that initialization creates output directory"""
        reporter = HealthCheckReporter(output_dir=temp_output_dir)
        assert reporter.output_dir == os.path.join(temp_output_dir, "reports")
        assert os.path.exists(reporter.output_dir)

    def test_save_report_with_health_check_results(self, temp_output_dir):
        """Test saving health check report with multiple components and results"""
        reporter = HealthCheckReporter(output_dir=temp_output_dir)
        scenario = DummyScenario(cluster_components=ClusterComponents())
        now = datetime.datetime.now()

        fitness_results = [
            CommandRunResult(
                generation_id=0,
                scenario_id=1,
                scenario=scenario,
                cmd="test-cmd",
                log="test-log",
                returncode=0,
                start_time=now,
                end_time=now,
                fitness_result=FitnessResult(fitness_score=10.0),
                health_check_results={
                    "app1": [
                        HealthCheckResult(
                            name="app1",
                            response_time=0.1,
                            status_code=200,
                            success=True,
                        ),
                        HealthCheckResult(
                            name="app1",
                            response_time=0.2,
                            status_code=200,
                            success=True,
                        ),
                    ],
                    "app2": [
                        HealthCheckResult(
                            name="app2",
                            response_time=0.15,
                            status_code=200,
                            success=True,
                        )
                    ],
                },
            )
        ]

        reporter.save_report(fitness_results)

        report_path = os.path.join(
            temp_output_dir, "reports", "health_check_report.csv"
        )
        assert os.path.exists(report_path)

        df = pd.read_csv(report_path)
        assert len(df) == 2
        assert set(df["component_name"].values) == {"app1", "app2"}
        app1_row = df[df["component_name"] == "app1"].iloc[0]
        assert app1_row["min_response_time"] == 0.1
        assert app1_row["max_response_time"] == 0.2
        assert app1_row["success_count"] == 2
        assert app1_row["failure_count"] == 0

    def test_save_report_skips_empty_results_and_continues(
        self, temp_output_dir, caplog
    ):
        """Test that an empty component results list does not break the loop, missing subsequent components."""
        import logging

        reporter = HealthCheckReporter(output_dir=temp_output_dir)
        scenario = DummyScenario(cluster_components=ClusterComponents())
        now = datetime.datetime.now()

        fitness_results = [
            CommandRunResult(
                generation_id=0,
                scenario_id=1,
                scenario=scenario,
                cmd="test-cmd",
                log="test-log",
                returncode=0,
                start_time=now,
                end_time=now,
                fitness_result=FitnessResult(fitness_score=10.0),
                health_check_results={
                    "app1": [
                        HealthCheckResult(
                            name="app1",
                            response_time=0.1,
                            status_code=200,
                            success=True,
                        )
                    ],
                    "broken_app_2": [],  # Empty result! This used to break the loop.
                    "app3": [
                        HealthCheckResult(
                            name="app3",
                            response_time=0.3,
                            status_code=200,
                            success=True,
                        )
                    ],
                },
            )
        ]

        with caplog.at_level(
            logging.WARNING, logger="krkn_ai.reporter.health_check_reporter"
        ):
            reporter.save_report(fitness_results)

        report_path = os.path.join(
            temp_output_dir, "reports", "health_check_report.csv"
        )
        assert os.path.exists(report_path)

        df = pd.read_csv(report_path)
        # Should contain app1 and app3, skipping broken_app_2 but NOT terminating the loop
        assert len(df) == 2
        assert set(df["component_name"].values) == {"app1", "app3"}

        # Assert the skip was logged so operators can debug silent gaps
        assert any("zero health-check samples" in msg for msg in caplog.messages)

    def test_save_report_with_empty_results(self, temp_output_dir):
        """Test saving report with empty fitness results"""
        reporter = HealthCheckReporter(output_dir=temp_output_dir)

        reporter.save_report([])

        report_path = os.path.join(
            temp_output_dir, "reports", "health_check_report.csv"
        )
        assert os.path.exists(report_path)

        # Empty results create a CSV file with headers but no data rows
        # Verify file exists and can be read (may be empty or have headers only)
        try:
            df = pd.read_csv(report_path)
            assert len(df) == 0
        except pd.errors.EmptyDataError:
            # Empty file is acceptable behavior for empty results
            pass

    def test_plot_report_with_health_check_data(self, temp_output_dir):
        """Test plotting health check report with valid data"""
        reporter = HealthCheckReporter(output_dir=temp_output_dir)
        scenario = DummyScenario(cluster_components=ClusterComponents())
        now = datetime.datetime.now()

        result = CommandRunResult(
            generation_id=0,
            scenario_id=1,
            scenario=scenario,
            cmd="test-cmd",
            log="test-log",
            returncode=0,
            start_time=now,
            end_time=now,
            fitness_result=FitnessResult(fitness_score=10.0),
            health_check_results={
                "app1": [
                    HealthCheckResult(
                        name="app1",
                        timestamp=now.isoformat(),
                        response_time=0.1,
                        status_code=200,
                        success=True,
                    )
                ]
            },
        )

        with (
            patch("krkn_ai.reporter.health_check_reporter.plt") as mock_plt,
            patch("krkn_ai.reporter.health_check_reporter.sns") as mock_sns,
        ):
            # Mock subplots to return fig and axes
            mock_fig = MagicMock()
            mock_axes = [MagicMock(), MagicMock()]
            mock_plt.subplots.return_value = (mock_fig, mock_axes)

            reporter.plot_report(result)

            graph_dir = os.path.join(temp_output_dir, "reports", "graphs")
            assert os.path.exists(graph_dir)
            mock_plt.subplots.assert_called_once_with(2, 1, figsize=(15, 10))
            mock_sns.lineplot.assert_called_once()
            mock_sns.heatmap.assert_called_once()
            mock_plt.tight_layout.assert_called_once()
            mock_plt.savefig.assert_called_once()
            mock_plt.close.assert_called_once()

    def test_plot_report_with_empty_health_check_results(self, temp_output_dir):
        """Test that empty health check results does not generate plot"""
        reporter = HealthCheckReporter(output_dir=temp_output_dir)
        scenario = DummyScenario(cluster_components=ClusterComponents())
        now = datetime.datetime.now()

        result = CommandRunResult(
            generation_id=0,
            scenario_id=1,
            scenario=scenario,
            cmd="test-cmd",
            log="test-log",
            returncode=0,
            start_time=now,
            end_time=now,
            fitness_result=FitnessResult(fitness_score=10.0),
            health_check_results={},
        )

        with patch("krkn_ai.reporter.health_check_reporter.plt") as mock_plt:
            reporter.plot_report(result)

            # Should not call savefig for empty results
            mock_plt.savefig.assert_not_called()

    def test_write_fitness_result_creates_and_appends_csv(self, temp_output_dir):
        """Test writing fitness result creates CSV and appends subsequent results"""
        reporter = HealthCheckReporter(output_dir=temp_output_dir)
        scenario = DummyScenario(cluster_components=ClusterComponents())
        now = datetime.datetime.now()

        result1 = CommandRunResult(
            generation_id=0,
            scenario_id=1,
            scenario=scenario,
            cmd="test-cmd-1",
            log="test-log-1",
            returncode=0,
            start_time=now,
            end_time=now,
            fitness_result=FitnessResult(fitness_score=10.0),
        )

        result2 = CommandRunResult(
            generation_id=1,
            scenario_id=2,
            scenario=scenario,
            cmd="test-cmd-2",
            log="test-log-2",
            returncode=0,
            start_time=now,
            end_time=now,
            fitness_result=FitnessResult(fitness_score=20.0),
        )

        reporter.write_fitness_result(result1)
        reporter.write_fitness_result(result2)

        report_path = os.path.join(temp_output_dir, "reports", "all.csv")
        assert os.path.exists(report_path)

        df = pd.read_csv(report_path)
        assert len(df) == 2
        assert df.iloc[0]["generation_id"] == 0
        assert df.iloc[0]["fitness_score"] == 10.0
        assert df.iloc[1]["generation_id"] == 1
        assert df.iloc[1]["fitness_score"] == 20.0

    def test_sort_fitness_result_csv_sorts_by_fitness_score(self, temp_output_dir):
        """Test sorting CSV file by fitness score in descending order"""
        reporter = HealthCheckReporter(output_dir=temp_output_dir)
        scenario = DummyScenario(cluster_components=ClusterComponents())
        now = datetime.datetime.now()

        # Write results in non-sorted order
        results = [
            CommandRunResult(
                generation_id=i,
                scenario_id=i + 1,
                scenario=scenario,
                cmd=f"cmd-{i}",
                log=f"log-{i}",
                returncode=0,
                start_time=now,
                end_time=now,
                fitness_result=FitnessResult(
                    fitness_score=float(10 - i * 2)
                ),  # 10, 8, 6, 4, 2
            )
            for i in range(5)
        ]

        for result in results:
            reporter.write_fitness_result(result)

        reporter.sort_fitness_result_csv()

        report_path = os.path.join(temp_output_dir, "reports", "all.csv")
        df = pd.read_csv(report_path)

        # Should be sorted descending by fitness_score
        assert df.iloc[0]["fitness_score"] == 10.0
        assert df.iloc[-1]["fitness_score"] == 2.0
        assert all(
            df.iloc[i]["fitness_score"] >= df.iloc[i + 1]["fitness_score"]
            for i in range(len(df) - 1)
        )

    def test_sort_fitness_result_csv_with_nonexistent_file(self, temp_output_dir):
        """Test sorting when CSV file does not exist"""
        reporter = HealthCheckReporter(output_dir=temp_output_dir)

        # Should not raise error when file doesn't exist
        reporter.sort_fitness_result_csv()

        report_path = os.path.join(temp_output_dir, "reports", "all.csv")
        assert not os.path.exists(report_path)
