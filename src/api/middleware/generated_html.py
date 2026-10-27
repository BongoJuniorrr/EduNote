"""Give generated HTML artifacts an opaque origin, including direct navigation."""
from starlette.middleware.base import BaseHTTPMiddleware

GENERATED_HTML_CSP = (
    "sandbox allow-scripts; default-src 'none'; "
    "script-src 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
    "style-src 'unsafe-inline' https:; font-src https: data:; img-src https: data:; "
    "media-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'"
)


class GeneratedHtmlIsolationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith('/api/outputs/') and (
            'text/html' in response.headers.get('content-type', '')
            or request.url.path.lower().endswith(('.html', '.htm'))
        ):
            response.headers['cache-control'] = 'no-store'
            response.headers['content-security-policy'] = GENERATED_HTML_CSP
            response.headers['x-frame-options'] = 'SAMEORIGIN'
            response.headers['x-content-type-options'] = 'nosniff'
            response.headers['referrer-policy'] = 'no-referrer'
        return response
