"""
HealthCheckWatcher core functionality tests
"""

import time
from unittest.mock import Mock, patch

from krkn_ai.chaos_engines.health_check_watcher import HealthCheckWatcher
from krkn_ai.models.config import (
    HealthCheckConfig,
    HealthCheckApplicationConfig,
    HealthCheckResult,
    ParameterValue,
)


class TestHealthCheckWatcherInitialization:
    """Test HealthCheckWatcher initialization"""

    def test_init_with_empty_config(self):
        """Test initialization with empty health check config"""
        config = HealthCheckConfig(applications=[])
        watcher = HealthCheckWatcher(config)
        assert watcher.config == config
        assert not watcher._stop_event.is_set()


class TestHealthCheckWatcherRunAndStop:
    """Test HealthCheckWatcher run and stop behavior"""

    @patch("krkn_ai.chaos_engines.health_check_watcher.requests.get")
    def test_run_starts_threads_for_each_application(self, mock_get):
        """Test run starts a thread for each health check application"""
        # Mock successful health check response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_get.return_value = mock_response

        app_config = HealthCheckApplicationConfig(
            name="test-app",
            url="http://localhost:8080/health",
            timeout=5,
            interval=1,  # Short interval for testing
        )
        config = HealthCheckConfig(applications=[app_config])
        watcher = HealthCheckWatcher(config)

        watcher.run()

        # Verify thread was started
        assert len(watcher._threads) == 1
        assert watcher._threads[0].is_alive()
        assert watcher._threads[0].daemon is True

        # Stop and wait for thread to finish
        watcher.stop()
        watcher._threads[0].join(timeout=1.0)
        assert not watcher._threads[0].is_alive()

    @patch("krkn_ai.chaos_engines.health_check_watcher.requests.get")
    def test_stop_terminates_all_threads(self, mock_get):
        """Test stop method terminates all running health check threads"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_get.return_value = mock_response

        app_configs = [
            HealthCheckApplicationConfig(
                name=f"app-{i}", url=f"http://localhost:808{i}/health", interval=1
            )
            for i in range(3)
        ]
        config = HealthCheckConfig(applications=app_configs)
        watcher = HealthCheckWatcher(config)

        watcher.run()
        assert len(watcher._threads) == 3

        watcher.stop()

        # Wait for all threads to finish
        for thread in watcher._threads:
            thread.join(timeout=1.0)
            assert not thread.is_alive()

    def test_stop_uses_timeout_budget_and_logs_stuck_threads(self):
        """Test stop does not block forever on a stuck health check thread"""
        config = HealthCheckConfig(applications=[], stop_timeout=0.25)
        watcher = HealthCheckWatcher(config)
        stuck_thread = Mock()
        stuck_thread.name = "health-check-stuck"
        stuck_thread.is_alive.return_value = True
        watcher._threads = [stuck_thread]

        with patch(
            "krkn_ai.chaos_engines.health_check_watcher.logger.warning"
        ) as mock_warning:
            watcher.stop()

        stuck_thread.join.assert_called_once()
        actual_timeout = stuck_thread.join.call_args.kwargs["timeout"]
        assert actual_timeout is not None
        assert 0 <= actual_timeout <= 0.25
        mock_warning.assert_called_once_with(
            "Health check worker thread %s is still running after %.2f seconds; "
            "continuing shutdown",
            "health-check-stuck",
            0.25,
        )


class TestHealthCheckWatcherResults:
    """Test HealthCheckWatcher result collection and summarization"""

    @patch("krkn_ai.chaos_engines.health_check_watcher.requests.get")
    def test_get_results_aggregates_from_all_threads(self, mock_get):
        """Test get_results aggregates results from all health check threads"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_get.return_value = mock_response

        app_config = HealthCheckApplicationConfig(
            name="test-app",
            url="http://localhost:8080/health",
            interval=1,  # Short interval for testing
        )
        config = HealthCheckConfig(applications=[app_config])
        watcher = HealthCheckWatcher(config)

        watcher.run()
        time.sleep(0.3)  # Allow some health checks to run
        watcher.stop()

        results = watcher.get_results()

        assert len(results) == 1
        assert "http://localhost:8080/health" in results
        assert len(results["http://localhost:8080/health"]) > 0
        # Verify all results are successful
        for result in results["http://localhost:8080/health"]:
            assert isinstance(result, HealthCheckResult)
            assert result.success is True
            assert result.status_code == 200

    def test_get_results_returns_snapshot_copy(self):
        """Test get_results does not expose live worker result lists"""
        watcher = HealthCheckWatcher(HealthCheckConfig(applications=[]))
        first_result = HealthCheckResult(
            name="test-app",
            status_code=200,
            success=True,
            response_time=0.1,
        )
        late_result = HealthCheckResult(
            name="test-app",
            status_code=200,
            success=True,
            response_time=0.2,
        )

        with watcher._results_lock:
            watcher._thread_results[1] = (
                "http://localhost:8080/health",
                [first_result],
            )

        results = watcher.get_results()

        with watcher._results_lock:
            watcher._thread_results[1][1].append(late_result)

        assert results["http://localhost:8080/health"] == [first_result]

    @patch("krkn_ai.chaos_engines.health_check_watcher.requests.get")
    def test_summarize_success_rate_calculates_failure_score(self, mock_get):
        """Test summarize_success_rate calculates failure score correctly"""
        # Mock mix of successful and failed responses
        mock_responses = [
            Mock(status_code=200, elapsed=Mock(total_seconds=lambda: 0.1)),
            Mock(status_code=500, elapsed=Mock(total_seconds=lambda: 0.1)),
            Mock(status_code=200, elapsed=Mock(total_seconds=lambda: 0.1)),
        ]
        mock_get.side_effect = mock_responses

        app_config = HealthCheckApplicationConfig(
            name="test-app", url="http://localhost:8080/health", interval=1
        )
        config = HealthCheckConfig(applications=[app_config])
        watcher = HealthCheckWatcher(config)

        watcher.run()
        time.sleep(0.3)
        watcher.stop()

        results = watcher.get_results()
        score = watcher.summarize_success_rate(results)

        # Should have some failures, score should be > 0
        assert score >= 0
        # Score is (failed / total) * 10
        assert score <= 10

    @patch("krkn_ai.chaos_engines.health_check_watcher.requests.get")
    def test_summarize_success_rate_returns_zero_for_empty_results(self, mock_get):
        """Test summarize_success_rate returns 0 for empty results"""
        config = HealthCheckConfig(applications=[])
        watcher = HealthCheckWatcher(config)

        score = watcher.summarize_success_rate({})
        assert score == 0

    @patch("krkn_ai.chaos_engines.health_check_watcher.requests.get")
    def test_summarize_response_time_detects_outliers(self, mock_get):
        """Test summarize_response_time detects response time outliers"""
        # Mock responses with varying response times (some outliers)
        response_times = [0.1, 0.15, 0.2, 0.25, 2.0, 2.5]  # Last two are outliers
        mock_responses = [
            Mock(status_code=200, elapsed=Mock(total_seconds=lambda: rt))
            for rt in response_times
        ]
        mock_get.side_effect = mock_responses

        app_config = HealthCheckApplicationConfig(
            name="test-app", url="http://localhost:8080/health", interval=1
        )
        config = HealthCheckConfig(applications=[app_config])
        watcher = HealthCheckWatcher(config)

        watcher.run()
        time.sleep(0.5)  # Allow enough time for multiple checks
        watcher.stop()

        results = watcher.get_results()
        score = watcher.summarize_response_time(results)

        # Should detect outliers and return score > 0
        assert score >= 0
        assert score <= 10

    @patch("krkn_ai.chaos_engines.health_check_watcher.requests.get")
    def test_summarize_response_time_returns_zero_with_insufficient_data(
        self, mock_get
    ):
        """Test summarize_response_time returns 0 when there's insufficient data"""
        mock_response = Mock(status_code=200, elapsed=Mock(total_seconds=lambda: 0.1))
        mock_get.return_value = mock_response

        app_config = HealthCheckApplicationConfig(
            name="test-app", url="http://localhost:8080/health", interval=1
        )
        config = HealthCheckConfig(applications=[app_config])
        watcher = HealthCheckWatcher(config)

        watcher.run()
        time.sleep(0.1)  # Very short time, not enough for 4+ checks
        watcher.stop()

        results = watcher.get_results()
        score = watcher.summarize_response_time(results)

        # Should return 0 when less than 4 successful checks
        assert score == 0

    def test_summarize_response_time_skips_insufficient_first_url_continues_processing(
        self,
    ):
        """Test summarize_response_time skips URLs with <4 samples but processes remaining URLs.

        This tests the bug fix where previously return 0 would exit the entire function
        when the first URL had insufficient data, causing total data loss.
        """
        watcher = HealthCheckWatcher(HealthCheckConfig(applications=[]))

        # First URL has only 2 successful results (insufficient)
        first_url_results = [
            HealthCheckResult(
                name="app1", status_code=200, success=True, response_time=0.1
            ),
            HealthCheckResult(
                name="app1", status_code=200, success=True, response_time=0.15
            ),
        ]

        # Second URL has 5 successful results (sufficient - can detect outliers)
        second_url_results = [
            HealthCheckResult(
                name="app2", status_code=200, success=True, response_time=0.1
            ),
            HealthCheckResult(
                name="app2", status_code=200, success=True, response_time=0.12
            ),
            HealthCheckResult(
                name="app2", status_code=200, success=True, response_time=0.14
            ),
            HealthCheckResult(
                name="app2", status_code=200, success=True, response_time=0.16
            ),
            HealthCheckResult(
                name="app2", status_code=200, success=True, response_time=2.5
            ),  # outlier
        ]

        health_check_results = {
            "http://first-url": first_url_results,
            "http://second-url": second_url_results,
        }

        score = watcher.summarize_response_time(health_check_results)

        # Should NOT return 0 - second URL has sufficient data and should contribute
        # The outlier (2.5) should be detected, so score should be > 0
        assert score > 0

    def test_summarize_response_time_returns_zero_only_when_all_urls_have_insufficient_data(
        self,
    ):
        """Test summarize_response_time returns 0 only when ALL URLs have <4 samples."""
        watcher = HealthCheckWatcher(HealthCheckConfig(applications=[]))

        # All URLs have insufficient data
        first_url_results = [
            HealthCheckResult(
                name="app1", status_code=200, success=True, response_time=0.1
            ),
            HealthCheckResult(
                name="app1", status_code=200, success=True, response_time=0.15
            ),
        ]
        second_url_results = [
            HealthCheckResult(
                name="app2", status_code=200, success=True, response_time=0.1
            ),
            HealthCheckResult(
                name="app2", status_code=200, success=True, response_time=0.15
            ),
            HealthCheckResult(
                name="app2", status_code=200, success=True, response_time=0.2
            ),
        ]

        health_check_results = {
            "http://first-url": first_url_results,
            "http://second-url": second_url_results,
        }

        score = watcher.summarize_response_time(health_check_results)

        # Should return 0 since ALL URLs have insufficient data
        assert score == 0

    def test_summarize_response_time_middle_url_insufficient_does_not_stop_processing(
        self,
    ):
        """Test that an insufficient URL in the middle doesn't stop processing subsequent URLs."""
        watcher = HealthCheckWatcher(HealthCheckConfig(applications=[]))

        # Three URLs where the middle one has insufficient data
        first_url_results = [
            HealthCheckResult(
                name="app1", status_code=200, success=True, response_time=0.1
            ),
            HealthCheckResult(
                name="app1", status_code=200, success=True, response_time=0.12
            ),
            HealthCheckResult(
                name="app1", status_code=200, success=True, response_time=0.14
            ),
            HealthCheckResult(
                name="app1", status_code=200, success=True, response_time=0.16
            ),
        ]
        middle_url_results = [
            HealthCheckResult(
                name="app2", status_code=200, success=True, response_time=0.1
            ),
            HealthCheckResult(
                name="app2", status_code=200, success=True, response_time=0.15
            ),
        ]  # Only 2 - insufficient
        last_url_results = [
            HealthCheckResult(
                name="app3", status_code=200, success=True, response_time=0.1
            ),
            HealthCheckResult(
                name="app3", status_code=200, success=True, response_time=0.12
            ),
            HealthCheckResult(
                name="app3", status_code=200, success=True, response_time=0.14
            ),
            HealthCheckResult(
                name="app3", status_code=200, success=True, response_time=0.16
            ),
            HealthCheckResult(
                name="app3", status_code=200, success=True, response_time=3.0
            ),  # outlier
        ]

        health_check_results = {
            "http://first": first_url_results,
            "http://middle": middle_url_results,
            "http://last": last_url_results,
        }

        score = watcher.summarize_response_time(health_check_results)

        # Should NOT return 0 - first and last URLs have sufficient data
        assert score > 0

    @patch("krkn_ai.chaos_engines.health_check_watcher.requests.get")
    def test_handles_request_exceptions_gracefully(self, mock_get):
        """Test health check handles request exceptions gracefully"""
        # Mock request to raise exception
        mock_get.side_effect = Exception("Connection error")

        app_config = HealthCheckApplicationConfig(
            name="test-app", url="http://localhost:8080/health", interval=1
        )
        config = HealthCheckConfig(applications=[app_config])
        watcher = HealthCheckWatcher(config)

        watcher.run()
        time.sleep(0.2)
        watcher.stop()

        results = watcher.get_results()

        # Should have results with failure status
        assert len(results) > 0
        for url_results in results.values():
            for result in url_results:
                assert result.success is False
                assert result.status_code == -1
                assert result.error is not None


class TestHealthCheckWatcherHeaders:
    """Test header merging and env-var resolution"""

    @patch("krkn_ai.chaos_engines.health_check_watcher.requests.get")
    def test_global_headers_sent_when_no_endpoint_headers(self, mock_get):
        """Global headers are passed to requests.get when endpoint has none"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_get.return_value = mock_response

        config = HealthCheckConfig(
            headers={"X-Global": "global-value"},
            applications=[
                HealthCheckApplicationConfig(
                    name="api", url="http://localhost/health", interval=1
                )
            ],
        )
        watcher = HealthCheckWatcher(config)
        watcher.run()
        watcher.stop()

        assert mock_get.call_args.kwargs["headers"]["X-Global"] == "global-value"

    @patch("krkn_ai.chaos_engines.health_check_watcher.requests.get")
    def test_endpoint_headers_override_global(self, mock_get):
        """Per-endpoint header wins over global for the same key"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_get.return_value = mock_response

        config = HealthCheckConfig(
            headers={"Authorization": "Bearer global"},
            applications=[
                HealthCheckApplicationConfig(
                    name="api",
                    url="http://localhost/health",
                    headers={"Authorization": "Bearer endpoint"},
                    interval=1,
                )
            ],
        )
        watcher = HealthCheckWatcher(config)
        watcher.run()
        watcher.stop()

        assert (
            mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer endpoint"
        )

    @patch("krkn_ai.chaos_engines.health_check_watcher.requests.get")
    def test_global_and_endpoint_headers_merged(self, mock_get):
        """Both global and endpoint headers are present when keys differ"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_get.return_value = mock_response

        config = HealthCheckConfig(
            headers={"X-Global": "g"},
            applications=[
                HealthCheckApplicationConfig(
                    name="api",
                    url="http://localhost/health",
                    headers={"X-Endpoint": "e"},
                    interval=1,
                )
            ],
        )
        watcher = HealthCheckWatcher(config)
        watcher.run()
        watcher.stop()

        kwargs = mock_get.call_args.kwargs
        assert kwargs["headers"]["X-Global"] == "g"
        assert kwargs["headers"]["X-Endpoint"] == "e"

    @patch("krkn_ai.chaos_engines.health_check_watcher.requests.get")
    def test_param_in_header_value_is_resolved(self, mock_get):
        """$PARAM in a header value is resolved from the params dict passed to the watcher"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_get.return_value = mock_response

        config = HealthCheckConfig(
            applications=[
                HealthCheckApplicationConfig(
                    name="api",
                    url="http://localhost/health",
                    headers={"Authorization": "Bearer $__TOKEN"},
                    interval=1,
                )
            ],
        )
        params = {"__TOKEN": ParameterValue(value="resolved-token", is_private=True)}
        watcher = HealthCheckWatcher(config, params=params)
        watcher.run()
        watcher.stop()

        assert (
            mock_get.call_args.kwargs["headers"]["Authorization"]
            == "Bearer resolved-token"
        )

    @patch("krkn_ai.chaos_engines.health_check_watcher.requests.get")
    def test_missing_param_leaves_template_unchanged(self, mock_get):
        """$PARAM with no matching entry in params dict is passed through as-is"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_get.return_value = mock_response

        config = HealthCheckConfig(
            applications=[
                HealthCheckApplicationConfig(
                    name="api",
                    url="http://localhost/health",
                    headers={"Authorization": "Bearer $MISSING"},
                    interval=1,
                )
            ],
        )
        watcher = HealthCheckWatcher(config, params={})
        watcher.run()
        watcher.stop()

        assert (
            mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer $MISSING"
        )
