"""Small bounded-cardinality HTTP metrics exporter without optional ML imports."""
from collections import defaultdict
import json
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

REQUESTS = defaultdict(int)
DURATION = defaultdict(float)


class HttpMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == '/metrics':
            return await call_next(request)
        started = time.monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get('route')
            path = getattr(route, 'path', '__unmatched__')
            method = request.method if request.method in {'GET','POST','PUT','PATCH','DELETE','OPTIONS','HEAD'} else 'OTHER'
            key = (method, path, str(status))
            REQUESTS[key] += 1
            DURATION[key] += time.monotonic() - started


def metrics_response():
    lines = ['# HELP edunote_http_requests_total Completed HTTP requests.',
             '# TYPE edunote_http_requests_total counter',
             '# HELP edunote_http_request_duration_seconds HTTP request duration.',
             '# TYPE edunote_http_request_duration_seconds summary']
    for (method, route, status), count in list(REQUESTS.items()):
        labels = ','.join(f'{k}={json.dumps(v)}' for k,v in [('method',method),('route',route),('status',status)])
        lines.append(f'edunote_http_requests_total{{{labels}}} {count}')
        lines.append(f'edunote_http_request_duration_seconds_count{{{labels}}} {count}')
        lines.append(f'edunote_http_request_duration_seconds_sum{{{labels}}} {DURATION[(method,route,status)]:.6f}')
    return Response('\n'.join(lines)+'\n', media_type='text/plain; version=0.0.4')
