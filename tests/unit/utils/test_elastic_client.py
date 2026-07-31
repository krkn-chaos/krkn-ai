from unittest.mock import Mock, patch
from krkn_ai.utils.elastic_client import ElasticSearchClient
from krkn_ai.models.config import ElasticConfig


class TestElasticSearchClient:
    def setup_method(self):
        self.config = ElasticConfig(
            server="https://example.com",
            port=9200,
            username="admin",
            password="password",
            enable=True,
            verify_certs=True,
        )

    @patch(
        "krkn_ai.utils.elastic_client.ElasticSearchClient._ElasticSearchClient__test_connection"
    )
    @patch("krkn_ai.utils.elastic_client.KrknElastic")
    def test_successful_connection_initializes_client(
        self, mock_krkn_elastic, mock_test_connection
    ):
        """Test that a successful connection initializes self.client"""
        mock_test_connection.return_value = True
        mock_instance = Mock()
        mock_krkn_elastic.return_value = mock_instance

        client = ElasticSearchClient(self.config)

        assert client.client is mock_instance
        mock_krkn_elastic.assert_called_once()

    @patch(
        "krkn_ai.utils.elastic_client.ElasticSearchClient._ElasticSearchClient__test_connection"
    )
    @patch("krkn_ai.utils.elastic_client.KrknElastic")
    def test_failed_connection_leaves_client_none(
        self, mock_krkn_elastic, mock_test_connection
    ):
        """Test that a failed connection ping leaves self.client as None"""
        mock_test_connection.return_value = False
        mock_krkn_elastic.return_value = Mock()

        client = ElasticSearchClient(self.config)

        # Client must be None — a failed ping must not silently retain the instance
        assert client.client is None
