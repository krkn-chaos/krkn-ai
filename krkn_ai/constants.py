WAIT_DURATION = 120  # 2 minutes

# Run status constants (written to results.json)
STATUS_STARTED = "started"
STATUS_IN_PROGRESS = "in progress"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

SCENARIO_MUTATION_RATE = 0.6
MUTATION_RATE = 0.7
CROSSOVER_RATE = 0.6

POPULATION_INJECTION_RATE = 0
POPULATION_INJECTION_SIZE = 2

# Stopping Criteria Defaults
# These are set to None by default to maintain backward compatibility
# Users can enable them via config file
DEFAULT_FITNESS_THRESHOLD = None  # No fitness threshold by default
DEFAULT_GENERATION_SATURATION = None  # No saturation check by default
