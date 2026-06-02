import json
import os
from pathlib import Path
from typing import Optional

CHECKPOINT_FILENAME = "checkpoint.json"


def save_checkpoint(
    output_dir: str, generation: int, run_uuid: str, format: str = "yaml"
) -> None:
    """
    Save a lightweight checkpoint: just the generation index and run UUID.
    Population state is already fully persisted in results/<uuid>/<format>/generation_N/
    so we don't duplicate it — we just record where to find it.
    """
    path = Path(output_dir) / CHECKPOINT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "generation": generation,
        "run_uuid": run_uuid,
        "generation_output_dir": str(
            Path(output_dir) / format / f"generation_{generation}"
        ),
    }
    tmp_path = str(path) + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, path)  # atomic — safe if process is killed mid-write


def load_checkpoint(output_dir: str) -> Optional[dict]:
    """Load checkpoint. Returns None if no checkpoint exists."""
    path = Path(output_dir) / CHECKPOINT_FILENAME
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)
