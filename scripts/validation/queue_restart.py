#!/usr/bin/env python3
"""Crash a real queue worker and verify leased work is recovered by a new process."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.services.queue.job_store import PersistentJobStore
from src.services.queue.worker import QueueWorker


def child(db, slow):
    worker=QueueWorker(PersistentJobStore(Path(db)));worker.lease_seconds=2
    def handler(payload, job):
        if slow: time.sleep(30)
        return {'recovered_value':payload['value']}
    worker.register('validation',handler)
    for _ in range(100):
        if worker.run_once() is not None:return
        time.sleep(.1)
    raise TimeoutError('No job recovered')


def main(output):
    started=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='edunote-queue-restart-') as directory:
        db=Path(directory)/'queue.sqlite3';store=PersistentJobStore(db);job=store.enqueue('local','validation',{'value':73})
        process=subprocess.Popen([sys.executable,__file__,'--child',str(db),'--slow'])
        try:
            for _ in range(100):
                if store.get(job.id).status=='running':break
                time.sleep(.1)
            else:raise AssertionError('Worker never claimed job')
            process.kill();process.wait(timeout=10)
            replacement=subprocess.run([sys.executable,__file__,'--child',str(db)],timeout=20,check=True)
            restored=store.get(job.id)
            assert restored.status=='completed' and restored.result=={'recovered_value':73},restored
            result={'passed':True,'scenario':'SIGKILL worker after claim; new process recovers expired lease and completes persisted payload','seconds':time.monotonic()-started,'status':restored.status,'recovered_value':restored.result['recovered_value'],'lease_seconds':2}
            output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=10)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);p.add_argument('--child');p.add_argument('--slow',action='store_true');a=p.parse_args()
    if a.child:child(a.child,a.slow)
    else:
        if a.output is None:p.error('--output required')
        main(a.output)
