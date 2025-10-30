class MissingScenarioError(Exception):
    pass

class ScenarioInitError(Exception):
    pass

class PopulationSizeError(Exception):
    pass

class PrometheusConnectionError(Exception):
    """
    Exception raised when there is an error connecting to Prometheus.
    """
    pass
