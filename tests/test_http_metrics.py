from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api.middleware.metrics import HttpMetricsMiddleware, metrics_response, REQUESTS, DURATION


def test_metrics_use_route_template_and_exclude_private_ids():
    REQUESTS.clear(); DURATION.clear()
    app = FastAPI()
    app.add_middleware(HttpMetricsMiddleware)
    app.add_api_route('/metrics', metrics_response)

    @app.get('/items/{item_id}')
    def item(item_id: str):
        return {'ok': True}

    with TestClient(app) as client:
        assert client.get('/items/private-document-name').status_code == 200
        assert client.get('/not-a-route').status_code == 404
        result = client.get('/metrics')
    assert result.status_code == 200
    assert 'route="/items/{item_id}"' in result.text
    assert 'route="__unmatched__"' in result.text
    assert 'private-document-name' not in result.text
    assert 'route="/metrics"' not in result.text
