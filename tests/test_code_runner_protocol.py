import base64
import json
import threading
import time
from pathlib import Path

import pytest

from src.services.code_runner_protocol import run_isolated


def test_isolated_protocol_roundtrip_and_artifact(tmp_path):
    spool = tmp_path / 'spool'
    assets = tmp_path / 'assets'
    assets.mkdir()
    (assets / 'input.txt').write_text('source')
    seen = {}

    def runner():
        while not list(spool.glob('*.request')):
            time.sleep(.01)
        request = next(spool.glob('*.request'))
        seen.update(json.loads(request.read_text()))
        request.with_suffix('.response').write_text(json.dumps({
            'stdout': '4', 'stderr': '', 'exit_code': 0, 'elapsed_ms': 2,
            'files': {'plot.txt': base64.b64encode(b'artifact').decode()},
        }))

    thread = threading.Thread(target=runner)
    thread.start()
    assert run_isolated(spool, 'print(2+2)', 1, assets)[0] == '4'
    thread.join()
    assert seen['timeout'] == 1
    assert base64.b64decode(seen['files']['input.txt']) == b'source'
    assert (assets / 'plot.txt').read_text() == 'artifact'
    assert not list(spool.iterdir())


def test_isolated_protocol_rejects_excess_input(tmp_path):
    assets = tmp_path / 'assets'
    assets.mkdir()
    for i in range(33):
        (assets / str(i)).touch()
    with pytest.raises(ValueError, match='32 files'):
        run_isolated(tmp_path / 'spool', 'print(1)', 1, assets)


def test_production_never_runs_untrusted_code_in_backend(tmp_path, monkeypatch):
    from src.tools.code_executor import CodeExecutionEnvironment, CodeExecutionError
    monkeypatch.setenv('EDUNOTE_ENV', 'production')
    monkeypatch.delenv('RUN_CODE_RUNNER_SPOOL', raising=False)
    with pytest.raises(CodeExecutionError, match='isolated runner'):
        CodeExecutionEnvironment(None).run_python('print(1)', 1, None)


def test_production_cannot_send_settings_as_code_assets(tmp_path, monkeypatch):
    from src.tools.code_executor import WorkspaceManager
    monkeypatch.setenv('EDUNOTE_ENV', 'production')
    manager = WorkspaceManager()
    with pytest.raises(ValueError, match='artifact workspace'):
        manager.resolve_assets_dir(str(manager.base_dir.parent / 'settings'))
