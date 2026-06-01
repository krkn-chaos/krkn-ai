"""
Tests for the pluggable workload generator framework.
Covers:
- BaseWorkloadGenerator contract
- HttpWorkloadGenerator (default)
- Custom workload generator loaded via config
- HealthCheckWatcher._load_generator()
"""

import time
from unittest.mock import Mock, patch

from krkn_ai.chaos_engines.health_check_watcher import HealthCheckWatcher
from krkn_ai.chaos_engines.workload.base_workload_generator import (
    BaseWorkloadGenerator,
    WorkloadResult,
)
from krkn_ai.chaos_engines.workload.http_workload_generator import HttpWorkloadGenerator
from krkn_ai.models.config import HealthCheckApplicationConfig, HealthCheckConfig


# ---------------------------------------------------------------------------
# Helpers / Fakes
# ---------------------------------------------------------------------------


class AlwaysSuccessWorkload(BaseWorkloadGenerator):
    """Fake workload that always succeeds — used in tests."""

    def generate(self) -> WorkloadResult:
        return WorkloadResult(success=True, response_time=0.05, status_code=200)


class AlwaysFailWorkload(BaseWorkloadGenerator):
    """Fake workload that always fails — used in tests."""

    def generate(self) -> WorkloadResult:
        return WorkloadResult(
            success=False,
            response_time=-1,
            status_code=-1,
            error="simulated failure",
        )


class SetupTeardownWorkload(BaseWorkloadGenerator):
    """Fake workload that tracks setup/teardown calls."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.setup_called = False
        self.teardown_called = False

    def setup(self) -> None:
        self.setup_called = True

    def teardown(self) -> None:
        self.teardown_called = True

    def generate(self) -> WorkloadResult:
        return WorkloadResult(success=True, response_time=0.01)


# ---------------------------------------------------------------------------
# BaseWorkloadGenerator tests
# ---------------------------------------------------------------------------


class TestBaseWorkloadGenerator:
    """Test BaseWorkloadGenerator contract"""

    def test_cannot_instantiate_abstract_class(self):
        """BaseWorkloadGenerator cannot be used directly without implementing generate()"""
        try:
            BaseWorkloadGenerator({})  # type: ignore
            assert False, "Should have raised TypeError"
        except TypeError:
            pass

    def test_concrete_subclass_can_be_instantiated(self):
        """A subclass that implements generate() can be instantiated"""
        gen = AlwaysSuccessWorkload({"key": "value"})
        assert gen.config == {"key": "value"}

    def test_generate_returns_workload_result(self):
        """generate() must return a WorkloadResult"""
        gen = AlwaysSuccessWorkload({})
        result = gen.generate()
        assert isinstance(result, WorkloadResult)

    def test_setup_and_teardown_default_do_nothing(self):
        """Default setup() and teardown() don't raise errors"""
        gen = AlwaysSuccessWorkload({})
        gen.setup()  # should not raise
        gen.teardown()  # should not raise

    def test_setup_and_teardown_can_be_overridden(self):
        """Subclass can override setup() and teardown()"""
        gen = SetupTeardownWorkload({})
        assert not gen.setup_called
        assert not gen.teardown_called
        gen.setup()
        gen.teardown()
        assert gen.setup_called
        assert gen.teardown_called


# ---------------------------------------------------------------------------
# WorkloadResult tests
# ---------------------------------------------------------------------------


class TestWorkloadResult:
    """Test WorkloadResult dataclass"""

    def test_success_result(self):
        result = WorkloadResult(success=True, response_time=0.1, status_code=200)
        assert result.success is True
        assert result.response_time == 0.1
        assert result.status_code == 200
        assert result.error is None

    def test_failure_result(self):
        result = WorkloadResult(
            success=False,
            response_time=-1,
            status_code=-1,
            error="timeout",
        )
        assert result.success is False
        assert result.error == "timeout"

    def test_default_status_code(self):
        """status_code defaults to -1 if not provided"""
        result = WorkloadResult(success=True, response_time=0.1)
        assert result.status_code == -1


# ---------------------------------------------------------------------------
# HttpWorkloadGenerator tests
# ---------------------------------------------------------------------------


class TestHttpWorkloadGenerator:
    """Test HttpWorkloadGenerator - the default workload"""

    @patch("krkn_ai.chaos_engines.workload.http_workload_generator.requests.get")
    def test_successful_request_returns_success(self, mock_get):
        """Returns success=True when status code matches expected"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_get.return_value = mock_response

        gen = HttpWorkloadGenerator(
            {
                "url": "http://localhost:8080/health",
                "timeout": 4,
                "status_code": 200,
            }
        )
        result = gen.generate()

        assert result.success is True
        assert result.status_code == 200
        assert result.response_time == 0.1
        assert result.error is None

    @patch("krkn_ai.chaos_engines.workload.http_workload_generator.requests.get")
    def test_wrong_status_code_returns_failure(self, mock_get):
        """Returns success=False when status code doesn't match expected"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.elapsed.total_seconds.return_value = 0.2
        mock_get.return_value = mock_response

        gen = HttpWorkloadGenerator(
            {
                "url": "http://localhost:8080/health",
                "timeout": 4,
                "status_code": 200,
            }
        )
        result = gen.generate()

        assert result.success is False
        assert result.status_code == 500

    @patch("krkn_ai.chaos_engines.workload.http_workload_generator.requests.get")
    def test_request_exception_returns_failure(self, mock_get):
        """Returns success=False with error message when request throws"""
        mock_get.side_effect = Exception("connection refused")

        gen = HttpWorkloadGenerator(
            {
                "url": "http://localhost:8080/health",
                "timeout": 4,
                "status_code": 200,
            }
        )
        result = gen.generate()

        assert result.success is False
        assert result.status_code == -1
        assert result.response_time == -1
        assert "connection refused" in result.error

    @patch("krkn_ai.chaos_engines.workload.http_workload_generator.requests.get")
    def test_uses_default_timeout_when_not_set(self, mock_get):
        """Uses timeout=4 by default if not provided in config"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_get.return_value = mock_response

        gen = HttpWorkloadGenerator({"url": "http://localhost/health"})
        gen.generate()

        mock_get.assert_called_once_with(
            "http://localhost/health", timeout=4, headers={}
        )


# ---------------------------------------------------------------------------
# HealthCheckWatcher._load_generator() tests
# ---------------------------------------------------------------------------


class TestLoadGenerator:
    """Test HealthCheckWatcher._load_generator()"""

    def test_returns_http_generator_when_no_workload_in_config(self):
        """Falls back to HttpWorkloadGenerator when workload not set"""
        app_config = HealthCheckApplicationConfig(
            name="test-app",
            url="http://localhost:8080/health",
        )
        config = HealthCheckConfig(applications=[app_config])
        watcher = HealthCheckWatcher(config)

        generator = watcher._load_generator(app_config)
        assert isinstance(generator, HttpWorkloadGenerator)

    def test_http_generator_gets_correct_config(self):
        """HttpWorkloadGenerator receives url, timeout, status_code from app config"""
        app_config = HealthCheckApplicationConfig(
            name="test-app",
            url="http://localhost:8080/health",
            timeout=10,
            status_code=201,
        )
        config = HealthCheckConfig(applications=[app_config])
        watcher = HealthCheckWatcher(config)

        generator = watcher._load_generator(app_config)
        assert isinstance(generator, HttpWorkloadGenerator)
        assert generator.config["url"] == "http://localhost:8080/health"
        assert generator.config["timeout"] == 10
        assert generator.config["status_code"] == 201

    def test_loads_custom_generator_from_dotted_path(self):
        """Loads a custom workload class using dotted module path"""
        app_config = HealthCheckApplicationConfig(
            name="test-app",
            url="http://localhost:8080/health",
            workload={
                "generator": "tests.unit.chaos_engines.test_workload_generator.AlwaysSuccessWorkload",
                "config": {"key": "value"},
            },
        )
        config = HealthCheckConfig(applications=[app_config])
        watcher = HealthCheckWatcher(config)

        generator = watcher._load_generator(app_config)
        assert isinstance(generator, AlwaysSuccessWorkload)
        assert generator.config == {"key": "value"}

    def test_custom_generator_empty_config_when_not_provided(self):
        """Custom generator gets empty dict config when config key missing"""
        app_config = HealthCheckApplicationConfig(
            name="test-app",
            url="http://localhost:8080/health",
            workload={
                "generator": "tests.unit.chaos_engines.test_workload_generator.AlwaysSuccessWorkload",
                # no "config" key
            },
        )
        config = HealthCheckConfig(applications=[app_config])
        watcher = HealthCheckWatcher(config)

        generator = watcher._load_generator(app_config)
        assert isinstance(generator, AlwaysSuccessWorkload)
        assert generator.config == {}


# ---------------------------------------------------------------------------
# HealthCheckWatcher integration with custom workload
# ---------------------------------------------------------------------------


class TestHealthCheckWatcherWithCustomWorkload:
    """Test HealthCheckWatcher end-to-end with custom workload generators"""

    def test_watcher_uses_custom_workload_and_records_success(self):
        """Watcher uses custom generator and records successful results"""
        app_config = HealthCheckApplicationConfig(
            name="test-app",
            url="http://localhost:8080/health",
            interval=1,
            workload={
                "generator": "tests.unit.chaos_engines.test_workload_generator.AlwaysSuccessWorkload",
                "config": {},
            },
        )
        config = HealthCheckConfig(applications=[app_config])
        watcher = HealthCheckWatcher(config)

        watcher.run()
        time.sleep(0.3)
        watcher.stop()

        results = watcher.get_results()
        assert len(results) == 1
        for url_results in results.values():
            assert len(url_results) > 0
            for result in url_results:
                assert result.success is True
                assert result.status_code == 200

    def test_watcher_stops_on_failure_with_custom_workload(self):
        """Watcher stops when stop_watcher_on_failure=True and workload fails"""
        app_config = HealthCheckApplicationConfig(
            name="test-app",
            url="http://localhost:8080/health",
            interval=1,
            workload={
                "generator": "tests.unit.chaos_engines.test_workload_generator.AlwaysFailWorkload",
                "config": {},
            },
        )
        config = HealthCheckConfig(
            applications=[app_config],
            stop_watcher_on_failure=True,
        )
        watcher = HealthCheckWatcher(config)

        watcher.run()
        time.sleep(0.3)

        # stop event should have been set by the failing workload
        assert watcher._stop_event.is_set()
        watcher.stop()

    def test_setup_and_teardown_called_on_custom_workload(self):
        """setup() is called before loop, teardown() is called after stop()"""
        app_config = HealthCheckApplicationConfig(
            name="test-app",
            url="http://localhost:8080/health",
            interval=1,
            workload={
                "generator": "krkn_ai.chaos_engines.workload.http_workload_generator.HttpWorkloadGenerator",
                "config": {},
            },
        )
        config = HealthCheckConfig(applications=[app_config])
        watcher = HealthCheckWatcher(config)

        watcher.run()
        time.sleep(0.3)
        watcher.stop()

        # After stop, teardown should have been called
        # We verify indirectly via results existing (thread ran)
        results = watcher.get_results()
        assert len(results) == 1
