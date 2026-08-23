from fastapi import status


class TestSearchEndpoint:
    def test_search_returns_200(self, test_client):
        response = test_client.get("/search", params={"q": "maple syrup"})
        assert response.status_code == status.HTTP_200_OK

    def test_search_returns_search_response_schema(self, test_client):
        response = test_client.get("/search", params={"q": "maple syrup"})
        data = response.json()
        assert "total" in data
        assert "hits" in data
        assert "query" in data
        assert "took_ms" in data

    def test_search_requires_q_param(self, test_client):
        response = test_client.get("/search")
        assert response.status_code == 422

    def test_search_respects_size_param(self, test_client):
        response = test_client.get("/search", params={"q": "test", "size": 50})
        assert response.status_code == status.HTTP_200_OK

    def test_search_rejects_invalid_size(self, test_client):
        response = test_client.get("/search", params={"q": "test", "size": 200})
        assert response.status_code == 422

    def test_search_rejects_an_unbounded_query_payload(self, test_client):
        response = test_client.get("/search", params={"q": "x" * 501})
        assert response.status_code == 422

    def test_search_rejects_an_unbounded_offset(self, test_client):
        response = test_client.get("/search", params={"q": "test", "from": 10_001})
        assert response.status_code == 422


class TestHealthEndpoints:
    def test_health_is_a_liveness_probe(self, test_client):
        response = test_client.get("/health")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "ok"}
        assert response.headers["X-Request-ID"]

    def test_ready_reports_search_backend_state(self, test_client):
        response = test_client.get("/ready")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "ready"
        assert response.json()["opensearch_connected"] is True

    def test_ready_returns_503_when_opensearch_is_unavailable(self, test_app, mock_search_engine):
        mock_search_engine.repository.client.ping.return_value = False
        from fastapi.testclient import TestClient

        response = TestClient(test_app).get("/ready")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["reason"] == "opensearch_unavailable"

    def test_opensearch_error_response_does_not_leak_connection_details(
        self, test_app, mock_search_engine
    ):
        from fastapi.testclient import TestClient
        from opensearchpy.exceptions import ConnectionError

        mock_search_engine.search.side_effect = ConnectionError(
            "password=unsafe http://internal-opensearch:9200", "", None
        )
        response = TestClient(test_app).get("/search", params={"q": "milk"})
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["detail"] == "Search is temporarily unavailable."
        assert "internal-opensearch" not in response.text


class TestProductEndpoint:
    def test_get_product_returns_200(self, test_client):
        response = test_client.get("/product/0008577002786")
        assert response.status_code == status.HTTP_200_OK

    def test_get_product_returns_product_schema(self, test_client):
        response = test_client.get("/product/0008577002786")
        data = response.json()
        assert "id" in data
        assert "product_name" in data
        assert "brand" in data
        assert "category" in data
        assert "metadata" in data

    def test_get_product_returns_404_for_missing(
        self, test_client, mock_search_engine
    ):
        mock_search_engine.get_product.return_value = None
        response = test_client.get("/product/nonexistent")
        assert response.status_code == 404

    def test_legacy_product_endpoint_works(self, test_client):
        response = test_client.get("/products/0008577002786")
        assert response.status_code == status.HTTP_200_OK


class TestBrandEndpoint:
    def test_search_brand_returns_200(self, test_client):
        response = test_client.get("/brand/Butternut")
        assert response.status_code == status.HTTP_200_OK

    def test_search_brand_returns_search_response(self, test_client):
        response = test_client.get("/brand/Butternut")
        data = response.json()
        assert "hits" in data
        assert "total" in data

    def test_legacy_brand_endpoint_works(self, test_client):
        response = test_client.get("/brands/Butternut")
        assert response.status_code == status.HTTP_200_OK


class TestCategoryEndpoint:
    def test_search_category_returns_200(self, test_client):
        response = test_client.get("/category/Sweeteners")
        assert response.status_code == status.HTTP_200_OK

    def test_search_category_returns_search_response(self, test_client):
        response = test_client.get("/category/Sweeteners")
        data = response.json()
        assert "hits" in data
        assert "total" in data

    def test_legacy_category_endpoint_works(self, test_client):
        response = test_client.get("/categories/Sweeteners")
        assert response.status_code == status.HTTP_200_OK


class TestOpenSearchUnavailable:
    def test_search_returns_503_when_opensearch_down(
        self, test_app, mock_search_engine
    ):
        from opensearchpy.exceptions import ConnectionError

        mock_search_engine.search.side_effect = ConnectionError(
            "Connection refused", "", None
        )
        from fastapi.testclient import TestClient

        client = TestClient(test_app)
        response = client.get("/search", params={"q": "test"})
        assert response.status_code == 503
        data = response.json()
        assert "search_engine_unavailable" in data.get("error", "")
