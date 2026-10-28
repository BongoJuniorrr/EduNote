"""Private queue child entrypoint. No credentials or raw tracebacks in job results."""

import asyncio
import inspect
import json
import os
from pathlib import Path
import sys


def main():
    from scripts.run_queue_worker import build_worker
    from src.services.queue.gpu import GpuResourceManager

    worker = build_worker()
    job = worker.store.get(sys.argv[1])
    os.environ["EDUNOTE_ACTIVE_JOB"] = job.id
    output = Path(sys.argv[2])
    try:
        if job.status != "running":
            return
        handler, gpu = worker.handlers[job.kind]

        def invoke(payload):
            value = handler(payload, job)
            return asyncio.run(value) if inspect.isawaitable(value) else value

        if gpu:
            with GpuResourceManager() as lease:
                value = invoke({**job.payload, "gpu_index": lease.index})
        else:
            value = invoke(job.payload)
        result = {"result": value if isinstance(value, dict) else {}}
    except Exception as error:
        from src.services.learning.workflows import safe_error

        result = {"error": safe_error(error)}
    output.write_text(json.dumps(result, ensure_ascii=False, default=str))
    output.chmod(0o600)


if __name__ == "__main__":
    main()
