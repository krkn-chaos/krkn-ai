from unittest.mock import MagicMock, patch
from krkn_ai.utils.elastic_client import ElasticSearchClient
from krkn_ai.models.config import ElasticConfig


def make_client():
    config = ElasticConfig(
        enable=True,
        server="http://localhost",
        port=9200,
        index="krkn-ai",
        username="",
        password="",
        verify_certs=False,
    )
    with patch("krkn_ai.utils.elastic_client.KrknElastic"):
        client = ElasticSearchClient(config)
        client.client = MagicMock()
        client.client.upload_data_to_elasticsearch.return_value = 1
        return client


def test_index_run_summary_returns_true_on_success():
    client = make_client()
    summary = {
        "run_id": "test-uuid-123",
        "status": "completed",
        "seed": 42,
        "start_time": "2026-01-01T00:00:00",
        "end_time": "2026-01-01T00:02:00",
        "duration_seconds": 120.0,
        "fitness_progression": [0.5, 0.7, 0.91],
        "summary": {
            "generations_completed": 3,
            "total_scenarios_executed": 15,
            "unique_scenarios": 12,
            "best_fitness_score": 0.91,
            "average_fitness_score": 0.75,
        },
    }
    result = client.index_run_summary(summary, "test-uuid-123")
    assert result is True
    client.client.upload_data_to_elasticsearch.assert_called_once()


def test_index_run_summary_uses_correct_index():
    client = make_client()
    summary = {"summary": {"best_fitness_score": 0.9}}
    client.index_run_summary(summary, "test-uuid")
    call_kwargs = client.client.upload_data_to_elasticsearch.call_args
    assert call_kwargs.kwargs["index"] == "krkn-ai-summary"


def test_index_run_summary_skips_when_disabled():
    config = ElasticConfig(
        enable=False,
        server="http://localhost",
        port=9200,
        index="krkn-ai",
        username="",
        password="",
        verify_certs=False,
    )
    with patch("krkn_ai.utils.elastic_client.KrknElastic"):
        client = ElasticSearchClient(config)
        result = client.index_run_summary({}, "test-uuid")
        assert result is False


def test_index_run_summary_fields_mapped_correctly():
    """Verify nested summary fields are extracted and mapped correctly."""
    client = make_client()
    summary = {
        "run_id": "abc",
        "status": "completed",
        "duration_seconds": 60.0,
        "summary": {
            "generations_completed": 5,
            "best_fitness_score": 0.88,
            "average_fitness_score": 0.65,
            "total_scenarios_executed": 20,
            "unique_scenarios": 18,
        },
        "fitness_progression": [],
    }
    client.index_run_summary(summary, "abc")
    call_kwargs = client.client.upload_data_to_elasticsearch.call_args
    indexed = call_kwargs.kwargs["item"]
    assert indexed["generations_completed"] == 5
    assert indexed["best_fitness_score"] == 0.88
    assert indexed["total_scenarios_executed"] == 20
