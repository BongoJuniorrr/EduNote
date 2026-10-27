"""File protocol for a network-isolated numerical Python runner."""
import base64
import json
import os
from pathlib import Path
import time
import uuid

MAX_FILES = 32
MAX_BYTES = 10 * 1024 * 1024


def run_isolated(spool: Path, code: str, timeout: int, assets: Path | None):
    if len(code.encode()) > 512 * 1024:
        raise ValueError('Code exceeds 512 KiB')
    timeout = max(1, min(int(timeout), 120))
    spool.mkdir(parents=True, exist_ok=True, mode=0o700)
    files = {}
    size = 0
    if assets:
        for path in sorted(assets.iterdir()):
            if not path.is_file() or path.is_symlink():
                continue
            size += path.stat().st_size
            if len(files) >= MAX_FILES or size > MAX_BYTES:
                raise ValueError('Runner input exceeds 32 files / 10 MiB')
            files[path.name] = base64.b64encode(path.read_bytes()).decode('ascii')
    job = uuid.uuid4().hex
    request = spool / f'{job}.request'
    response = spool / f'{job}.response'
    temporary = spool / f'{job}.tmp'
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'code': code, 'timeout': timeout, 'files': files}, stream)
        temporary.replace(request)
        deadline = time.monotonic() + timeout + 30
        while not response.exists():
            if time.monotonic() > deadline:
                raise TimeoutError('Isolated code runner did not respond; check runner health')
            time.sleep(0.1)
        if response.stat().st_size > MAX_BYTES * 2:
            raise ValueError('Runner response exceeds the output limit')
        result = json.loads(response.read_text())
        if result.get('error'):
            raise RuntimeError(result['error'])
        outputs = result.get('files', {})
        if len(outputs) > MAX_FILES:
            raise ValueError('Too many runner output files')
        if assets:
            total = 0
            for name, encoded in outputs.items():
                if name != Path(name).name or name in {'.', '..'}:
                    raise ValueError('Invalid runner artifact path')
                data = base64.b64decode(encoded, validate=True)
                total += len(data)
                if total > MAX_BYTES:
                    raise ValueError('Runner outputs exceed 10 MiB')
                path = assets / name
                if path.is_symlink():
                    raise ValueError('Runner artifact destination must not be a symlink')
                # Replace rather than following hard links or truncating an existing file.
                part = assets / f'.{job}-{name}.tmp'
                try:
                    part.write_bytes(data)
                    part.replace(path)
                finally:
                    part.unlink(missing_ok=True)
        return (str(result.get('stdout', '')), str(result.get('stderr', '')),
                int(result['exit_code']), float(result['elapsed_ms']))
    finally:
        for path in (request, response, temporary):
            path.unlink(missing_ok=True)
