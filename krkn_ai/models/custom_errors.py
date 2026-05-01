class MissingScenarioError(Exception):
    pass


class ScenarioInitError(Exception):
    """
    Exception raised when there is an error initializing a scenario.
    """

    pass


class PopulationSizeError(Exception):
    pass


class PrometheusConnectionError(Exception):
    """
    Exception raised when there is an error connecting to Prometheus.
    """

    pass


class FitnessFunctionCalculationError(Exception):
    """
    Exception raised when there is an error calculating fitness function.
    """

    pass


class ScenarioParameterInitError(Exception):
    """
    Exception raised when there is an error initializing a scenario parameter.
    """

    pass


class UniqueScenariosError(Exception):
    """
    Exception raised when there are no unique scenarios found.
    """

    pass


class ShellCommandTimeoutError(Exception):
    """
    Exception raised when a shell command times out.
    """

    pass


class KubeconfigValidationError(Exception):
    """
    Exception raised when a kubeconfig cannot be used for containerized krkn
    scenarios (e.g., it references credential files by host path instead of
    embedding them).
    """

    pass
