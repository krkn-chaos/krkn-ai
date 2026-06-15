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
        "status": "completed",
        "completed_generations": 3,
        "best_fitness_score": 0.91,
        "average_fitness_score": 0.75,
        "duration_seconds": 120.0,
        "total_scenarios_evaluated": 15,
        "unique_scenarios": 12,
        "start_time": "2026-01-01T00:00:00",
        "end_time": "2026-01-01T00:02:00",
        "seed": 42,
        "fitness_progression": [0.5, 0.7, 0.91],
    }
    result = client.index_run_summary(summary, "test-uuid-123")
    assert result is True
    client.client.upload_data_to_elasticsearch.assert_called_once()


def test_index_run_summary_uses_correct_index():
    client = make_client()
    summary = {"best_fitness_score": 0.9}
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
