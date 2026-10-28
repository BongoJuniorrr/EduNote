#!/usr/bin/env python3
"""Read-only route and service smoke checks; no provider keys or mutations."""
import argparse
import base64
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import urllib.error
import urllib.request

PAGES = ['/', '/history', '/knowledge', '/notebook', '/notebook/canvas', '/about',
         '/question', '/solver', '/guide', '/mission', '/ideagen', '/slide_pro',
         '/edu_studio', '/edu_studio/qwen_teacher', '/research', '/co_writer', '/settings',
         '/evidence', '/study-packs', '/review', '/jobs', '/settings/diagnostics']
API = ['/api/v1/config/status', '/api/v1/config/documents', '/api/v1/settings/sidebar',
       '/api/v1/edu-studio/templates', '/api/v1/knowledge/health', '/api/v1/notebook/health',
       '/slide_pro/_presenton/api/v1/ppt/presentation/all']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:3782')
    parser.add_argument('--password-file', type=Path, help='Private owner password file; secret is never printed')
    args = parser.parse_args()
    headers = {}
    if args.password_file:
        value = 'owner:' + args.password_file.read_text().strip()
        headers['Authorization'] = 'Basic ' + base64.b64encode(value.encode()).decode()

    def check(path):
        try:
            request = urllib.request.Request(args.base_url.rstrip('/') + path, headers=headers)
            with urllib.request.urlopen(request, timeout=20) as response:
                return {'path': path, 'status': response.status}
        except urllib.error.HTTPError as error:
            return {'path': path, 'status': error.code}
        except Exception as error:
            return {'path': path, 'status': 0, 'error': type(error).__name__}

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(check, PAGES + API))
    print(json.dumps({'checks': results, 'passed': all(r['status'] == 200 for r in results)}, indent=2))
    return 0 if all(r['status'] == 200 for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
