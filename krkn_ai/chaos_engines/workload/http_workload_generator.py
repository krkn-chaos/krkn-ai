import requests
from krkn_ai.chaos_engines.workload.base_workload_generator import (
    BaseWorkloadGenerator,
    WorkloadResult,
)


class HttpWorkloadGenerator(BaseWorkloadGenerator):
    """
    Default workload generator - performs a plain HTTP GET request.

    This is used automatically when no custom workload is
    specified in the health_checks config.

    Config keys:
        url (str): URL to send GET request to
        timeout (int): Request timeout in seconds (default: 4)
        status_code (int): Expected HTTP status code (default: 200)
    """

    def generate(self) -> WorkloadResult:
        url = self.config["url"]
        timeout = self.config.get("timeout", 4)
        expected_status = self.config.get("status_code", 200)

        try:
            headers = self.config.get("headers", {})
            resp = requests.get(url, timeout=timeout, headers=headers)
            success = resp.status_code == expected_status
            return WorkloadResult(
                success=success,
                response_time=resp.elapsed.total_seconds(),
                status_code=resp.status_code,
            )
        except Exception as e:
            return WorkloadResult(
                success=False,
                response_time=-1,
                status_code=-1,
                error=str(e),
            )
