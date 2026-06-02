import signal
import sys
from typing import Callable
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


def register_signal_handlers(
    get_state_fn: Callable, output_dir: str, run_uuid: str
) -> None:
    """
    Register SIGINT/SIGTERM handlers to checkpoint before exit.
    get_state_fn: callable returning (generation,) tuple
    """
    from krkn_ai.checkpoint import save_checkpoint

    def handler(signum, frame):
        generation, _ = get_state_fn()
        if generation is not None:
            save_checkpoint(output_dir, generation, run_uuid)
            logger.info("Checkpoint saved at generation %d. Exiting.", generation)
        else:
            logger.warning(
                "Interrupted before any generation completed — no checkpoint saved."
            )
        sys.exit(0)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
