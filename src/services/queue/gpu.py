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
    def __init__(self, lock_path: str | Path | None = None, max_used_fraction: float | None = None, min_free_bytes: int | None = None):
        self.lock_path = Path(lock_path or os.getenv("EDUNOTE_GPU_LOCK", "/tmp/edunote-gpu.lock"))
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_used_fraction = float(os.getenv("EDUNOTE_GPU_MAX_USED_FRACTION", "0.85")) if max_used_fraction is None else max_used_fraction
        self.min_free_bytes = int(os.getenv("EDUNOTE_GPU_MIN_FREE_BYTES", str(4 * 1024**3))) if min_free_bytes is None else min_free_bytes
        if not 0 < self.max_used_fraction <= 1 or self.min_free_bytes < 0:
            raise ValueError("Invalid GPU admission budget")
        self._lock_handle = None

    def _memory(self, index: int) -> tuple[int, int]:
        # Torch uses the same logical CUDA indices as the handler, including
        # CUDA_VISIBLE_DEVICES remapping. Physical NVML indices do not.
        import torch
        if not torch.cuda.is_available():
            return 0, 0
        free, total = torch.cuda.mem_get_info(index)
        return int(total), int(total - free)

    def _device_count(self) -> int:
        try:
            import torch
            return torch.cuda.device_count() if torch.cuda.is_available() else 0
        except ImportError:
            return 0

    def acquire(self, timeout_seconds: float = 30.0) -> GpuLease:
        deadline = time.monotonic() + timeout_seconds
        self._lock_handle = self.lock_path.open("w")
        try:
            while True:
                try:
                    fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("GPU lease is held by another worker")
                    time.sleep(min(0.25, max(0, deadline - time.monotonic())))
            count = self._device_count()
            if not count:
                raise TimeoutError("No CUDA GPU is available. Enable the GPU profile or configure a remote provider.")
            while time.monotonic() <= deadline:
                for index in range(count):
                    total, used = self._memory(index)
                    if total and used / total < self.max_used_fraction and total - used >= self.min_free_bytes:
                        return GpuLease(index=index, total_bytes=total, used_bytes=used)
                time.sleep(min(0.25, max(0, deadline - time.monotonic())))
            raise TimeoutError("No GPU has enough free VRAM for the configured admission budget")
        except BaseException:
            self.release()
            raise

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
