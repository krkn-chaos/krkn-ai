from unittest.mock import Mock, patch
from krkn_ai.utils.elastic_client import ElasticSearchClient
from krkn_ai.models.config import ElasticConfig


class TestElasticSearchClient:
    def setup_method(self):
        # Clear pool before each test
        ElasticSearchClient.clear_connection_pool()
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
    def test_connection_pooling(self, mock_krkn_elastic, mock_test_connection):
        """Test that identical connection params reuse the same client"""
        mock_test_connection.return_value = True
        mock_instance = Mock()
        mock_krkn_elastic.return_value = mock_instance

        # First connection
        client1 = ElasticSearchClient(self.config)
        assert len(ElasticSearchClient._connection_pool) == 1

        # Second connection with same params
        client2 = ElasticSearchClient(self.config)

        # Should reuse the client instance
        assert client1.client is client2.client
        assert len(ElasticSearchClient._connection_pool) == 1
        mock_krkn_elastic.assert_called_once()

    @patch(
        "krkn_ai.utils.elastic_client.ElasticSearchClient._ElasticSearchClient__test_connection"
    )
    @patch("krkn_ai.utils.elastic_client.KrknElastic")
    def test_connection_pool_different_params(
        self, mock_krkn_elastic, mock_test_connection
    ):
        """Test that different connection params create new clients"""
        mock_test_connection.return_value = True
        mock_instance1 = Mock()
        mock_instance2 = Mock()
        mock_krkn_elastic.side_effect = [mock_instance1, mock_instance2]

        # First connection
        client1 = ElasticSearchClient(self.config)

        # Second connection with different verify_certs
        config2 = self.config.model_copy()
        config2.verify_certs = False
        client2 = ElasticSearchClient(config2)

        # Should create a new instance
        assert client1.client is not client2.client
        assert len(ElasticSearchClient._connection_pool) == 2
        assert mock_krkn_elastic.call_count == 2
