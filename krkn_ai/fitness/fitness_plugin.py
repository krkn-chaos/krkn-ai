import abc
from krkn_ai.models.app import CommandRunResult, FitnessResult


class FitnessPlugin(abc.ABC):
    """Abstract base class for fitness plugins.

    Implementors should provide a ``compute_fitness`` method that takes the
    ``CommandRunResult`` of a scenario execution and returns a ``FitnessResult``
    containing any additional scores to be merged into the overall fitness.
    """

    @abc.abstractmethod
    def compute_fitness(self, scenario_result: CommandRunResult) -> FitnessResult:
        """Compute additional fitness information.

        Args:
            scenario_result: The result object produced by running a scenario.

        Returns:
            A ``FitnessResult`` containing plugin‑specific scores. The ``scores``
            list will be merged into the original result and the ``fitness_score``
            will be added to the existing overall score.
        """
        raise NotImplementedError
