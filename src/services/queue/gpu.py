"""Single-GPU resource lease with VRAM admission control."""

from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import time


@dataclass(frozen=True)
class GpuLease:
    index: int
    total_bytes: int
    used_bytes: int


class GpuResourceManager:
    def __init__(self, lock_path: str | Path | None = None, max_used_fraction: float = 0.20):
        self.lock_path = Path(lock_path or os.getenv("EDUNOTE_GPU_LOCK", "/tmp/edunote-gpu.lock"))
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_used_fraction = max_used_fraction
        self._lock_handle = None
        self._nvml_initialized = False

    def _memory(self, index: int) -> tuple[int, int]:
        try:
            import pynvml

            if not self._nvml_initialized:
                pynvml.nvmlInit()
                self._nvml_initialized = True
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            return int(info.total), int(info.used)
        except ImportError:
            import torch

            if not torch.cuda.is_available():
                return 0, 0
            free, total = torch.cuda.mem_get_info(index)
            return int(total), int(total - free)

    def _device_count(self) -> int:
        try:
            import pynvml

            if not self._nvml_initialized:
                pynvml.nvmlInit()
                self._nvml_initialized = True
            return int(pynvml.nvmlDeviceGetCount())
        except ImportError:
            import torch

            return torch.cuda.device_count() if torch.cuda.is_available() else 0

    def acquire(self, timeout_seconds: float = 30.0) -> GpuLease:
        deadline = time.monotonic() + timeout_seconds
        self._lock_handle = self.lock_path.open("w")
        fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX)
        while time.monotonic() <= deadline:
            for index in range(self._device_count()):
                total, used = self._memory(index)
                if total and used / total < self.max_used_fraction:
                    return GpuLease(index=index, total_bytes=total, used_bytes=used)
            time.sleep(0.25)
        self.release()
        raise TimeoutError("No GPU is below the configured VRAM admission threshold")

    def release(self) -> None:
        if self._lock_handle is not None:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
            self._lock_handle.close()
            self._lock_handle = None

    def __enter__(self) -> GpuLease:
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


__all__ = ["GpuLease", "GpuResourceManager"]
