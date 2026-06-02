import json
import tempfile
import pytest
import os
from krkn_ai.checkpoint import save_checkpoint, load_checkpoint
from krkn_ai.algorithm.genetic import _load_population_from_yaml


def test_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        save_checkpoint(tmp, generation=2, run_uuid="abc-123")
        state = load_checkpoint(tmp)
        assert state["generation"] == 2
        assert state["run_uuid"] == "abc-123"


def test_returns_none_when_missing():
    with tempfile.TemporaryDirectory() as tmp:
        assert load_checkpoint(tmp) is None


def test_overwrites_previous():
    with tempfile.TemporaryDirectory() as tmp:
        save_checkpoint(tmp, generation=1, run_uuid="abc-123")
        save_checkpoint(tmp, generation=3, run_uuid="abc-123")
        assert load_checkpoint(tmp)["generation"] == 3


def test_corrupted_raises():
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/checkpoint.json", "w") as f:
            f.write("not valid json{{")
        with pytest.raises(json.JSONDecodeError):
            load_checkpoint(tmp)


def test_save_creates_directory():
    with tempfile.TemporaryDirectory() as tmp:
        nested = os.path.join(tmp, "a", "b", "c")
        save_checkpoint(nested, generation=0, run_uuid="abc-123")
        state = load_checkpoint(nested)
        assert state["generation"] == 0


def test_load_population_returns_empty_when_no_yaml(tmp_path):
    gen_dir = tmp_path / "yaml" / "generation_2"
    gen_dir.mkdir(parents=True)
    result = _load_population_from_yaml(str(gen_dir))
    assert result == []


def test_load_population_returns_empty_when_dir_missing(tmp_path):
    result = _load_population_from_yaml(str(tmp_path / "nonexistent"))
    assert result == []


def test_save_stores_generation_zero():
    """Generation 0 should be saved and loaded correctly (not falsy check bug)."""
    with tempfile.TemporaryDirectory() as tmp:
        save_checkpoint(tmp, generation=0, run_uuid="abc-123")
        state = load_checkpoint(tmp)
        assert state["generation"] == 0
