from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from src.api.middleware.generated_html import GeneratedHtmlIsolationMiddleware


def test_direct_generated_html_is_sandboxed_and_cannot_access_application_origin():
    app = FastAPI()
    app.add_middleware(GeneratedHtmlIsolationMiddleware)

    @app.get('/api/outputs/guide/example.html')
    def artifact():
        return HTMLResponse('<script>parent.document.body.innerHTML="unsafe"</script>')

    @app.get('/health')
    def health():
        return {'ok': True}

    with TestClient(app) as client:
        response = client.get('/api/outputs/guide/example.html')
        assert response.status_code == 200
        assert response.headers['x-frame-options'] == 'SAMEORIGIN'
        csp = response.headers['content-security-policy']
        assert 'sandbox allow-scripts;' in csp
        assert 'allow-same-origin' not in csp
        assert "connect-src 'none'" in csp
        assert 'content-security-policy' not in client.get('/health').headers


def test_conditional_html_responses_keep_sandbox_headers():
    from fastapi.responses import Response
    app = FastAPI()
    app.add_middleware(GeneratedHtmlIsolationMiddleware)
    @app.get('/api/outputs/guide/cached.html')
    def cached():
        return Response(status_code=304, headers={'x-frame-options': 'DENY'})
    with TestClient(app) as client:
        response = client.get('/api/outputs/guide/cached.html')
        assert response.headers['x-frame-options'] == 'SAMEORIGIN'
        assert 'sandbox allow-scripts' in response.headers['content-security-policy']
        assert response.headers['cache-control'] == 'no-store'
