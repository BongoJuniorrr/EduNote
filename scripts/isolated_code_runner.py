#!/usr/bin/env python3
"""Poll a private spool in a network=none, read-only, resource-limited container.

The controller owns the spool. Untrusted children run as a separate UID with
no capabilities, provider credentials, app data mounts, or network interface.
"""
import base64
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile
import time

MAX_BYTES = 10 * 1024 * 1024
MAX_FILES = 32
SPOOL = Path(os.getenv('RUN_CODE_RUNNER_SPOOL', '/runner_spool'))


def child_limits():
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))


def execute(payload):
    timeout = max(1, min(int(payload.get('timeout', 10)), 120))
    code = str(payload.get('code', ''))
    if len(code.encode()) > 512 * 1024:
        raise ValueError('Code exceeds 512 KiB')
    files = payload.get('files') or {}
    if len(files) > MAX_FILES:
        raise ValueError('Too many input files')
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='run-', dir='/tmp') as directory:
        root = Path(directory)
        root.chmod(0o777)
        size = 0
        for name, encoded in files.items():
            if name != Path(name).name or name in {'.', '..'}:
                raise ValueError('Invalid input filename')
            data = base64.b64decode(encoded, validate=True)
            size += len(data)
            if size > MAX_BYTES:
                raise ValueError('Input files exceed 10 MiB')
            (root / name).write_bytes(data)
            (root / name).chmod(0o666)
        code_path = root / '_edunote_code.py'
        code_path.write_text(code)
        code_path.chmod(0o444)
        env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': directory,
               'TMPDIR': directory, 'PYTHONIOENCODING': 'utf-8',
               'MPLBACKEND': 'Agg', 'MPLCONFIGDIR': str(root / '.matplotlib'),
               'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2'}
        # Store logs outside the child-writable work directory and bound disk writes.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            proc = subprocess.Popen([sys.executable, str(code_path)], cwd=root,
                                    env=env, stdout=out, stderr=err,
                                    start_new_session=True, preexec_fn=child_limits)
            timed_out = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                # Also reap descendants left behind after a successful main process.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                # A child may create a new session; reap every untrusted UID in this PID namespace.
                for status_file in Path('/proc').glob('[0-9]*/status'):
                    try:
                        uid_line = next(line for line in status_file.read_text().splitlines() if line.startswith('Uid:'))
                        if int(uid_line.split()[1]) == 65534:
                            os.kill(int(status_file.parent.name), signal.SIGKILL)
                    except (OSError, StopIteration, ValueError):
                        pass
            out.seek(0); err.seek(0)
            stdout = out.read(256 * 1024).decode('utf-8', 'replace')
            stderr = err.read(256 * 1024).decode('utf-8', 'replace')
        if timed_out:
            stderr += '\nExecution timed out.'
        outputs = {}
        size = 0
        for path in sorted(root.iterdir()):
            if not path.is_file() or path.is_symlink() or path == code_path:
                continue
            size += path.stat().st_size
            if len(outputs) >= MAX_FILES or size > MAX_BYTES:
                raise ValueError('Output exceeds 32 files / 10 MiB')
            encoded = base64.b64encode(path.read_bytes()).decode('ascii')
            if files.get(path.name) != encoded:
                outputs[path.name] = encoded
        return {'stdout': stdout, 'stderr': stderr, 'exit_code': 124 if timed_out else proc.returncode,
                'elapsed_ms': (time.monotonic() - started) * 1000, 'files': outputs}


def serve():
    if os.getuid() != 0:
        raise RuntimeError('Controller must own the spool and drop child privileges')
    SPOOL.mkdir(parents=True, exist_ok=True, mode=0o700)
    SPOOL.chmod(0o700)
    while True:
        (SPOOL / 'heartbeat').touch(mode=0o600)
        for request in sorted(SPOOL.glob('*.request')):
            response = request.with_suffix('.response')
            try:
                if request.is_symlink() or request.stat().st_size > MAX_BYTES * 2:
                    raise ValueError('Invalid runner request')
                result = execute(json.loads(request.read_text()))
            except Exception as error:
                result = {'error': str(error)}
            if request.exists():
                tmp = request.with_suffix('.tmp-response')
                tmp.write_text(json.dumps(result))
                tmp.chmod(0o600)
                tmp.replace(response)
                request.unlink(missing_ok=True)
        # Remove abandoned responses; no application data is stored here.
        for response in SPOOL.glob('*.response'):
            if time.time() - response.stat().st_mtime > 300:
                response.unlink(missing_ok=True)
        time.sleep(0.1)


if __name__ == '__main__':
    serve()
