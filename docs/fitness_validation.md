# Fitness Score Validation & Bypassing (DX)

## Overview
As part of the Krkn-ai initialization phase, the framework attempts to construct a Prometheus client to evaluate the fitness function of the cluster. During client creation, a dummy connection test (`client.process_query("1")`) is executed to ensure the endpoint is reachable.

## Bypassing the Connection Test
When developing unit tests or working in environments without a reachable Prometheus cluster, it is essential to bypass this dummy connection test to prevent initialization failures. Note that `PROMETHEUS_URL` must still be resolvable (e.g., set to a dummy URL).

You can bypass this network validation by setting the `MOCK_FITNESS` environment variable to `true` or `"1"`.

```python
import os
from unittest.mock import patch

def test_runner_execution():
    # Bypass Prometheus connection test
    with patch("krkn_ai.utils.prometheus.env_is_truthy", return_value=True):
        # Or alternatively: os.environ["MOCK_FITNESS"] = "true"
        # Ensure a dummy URL is set so the client constructor doesn't fail
        os.environ["PROMETHEUS_URL"] = "http://localhost:9090"
        os.environ["PROMETHEUS_TOKEN"] = "dummy"

        runner = KrknRunner(config, "output_dir")
        runner.run(scenario, 1)
```

## Internal Mechanism
Behind the scenes, `_validate_and_create_client` in `krkn_ai.utils.prometheus` checks `env_is_truthy("MOCK_FITNESS")`. If this evaluates to `True`, the `process_query("1")` connection test is skipped, allowing the `KrknPrometheus` client to initialize without hitting the network.
