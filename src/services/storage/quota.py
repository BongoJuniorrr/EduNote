"""Personal workspace storage with path containment and a disk budget."""

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import threading

DEFAULT_QUOTA_BYTES = 2 * 1024 * 1024 * 1024


class QuotaExceededError(ValueError):
    """Raised before a write would exceed a user's storage quota."""


@dataclass(frozen=True)
class StorageUsage:
    user_id: str
    used_bytes: int
    quota_bytes: int

    @property
    def available_bytes(self) -> int:
        return max(0, self.quota_bytes - self.used_bytes)

    def as_dict(self) -> dict[str, int | str]:
        return {
            "user_id": self.user_id,
            "used_bytes": self.used_bytes,
            "quota_bytes": self.quota_bytes,
            "available_bytes": self.available_bytes,
        }


class StorageQuotaService:
    def __init__(self, root: Path | None = None):
        configured = os.getenv("EDUNOTE_STORAGE_ROOT", "")
        self.root = (
            root
            or (
                Path(configured)
                if configured
                else Path(__file__).resolve().parents[3] / "data" / "user"
            )
        ).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()

    def user_root(self, user_id: str) -> Path:
        """Compatibility alias: the application has exactly one workspace."""
        return self.root.resolve()

    def usage(self, user_id: str, rank: str = "free") -> StorageUsage:
        root = self.user_root(user_id)
        used = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        return StorageUsage(
            user_id, used, int(os.getenv("EDUNOTE_STORAGE_QUOTA_BYTES", str(DEFAULT_QUOTA_BYTES)))
        )

    def assert_can_write(self, user_id: str, size_bytes: int, rank: str = "free") -> StorageUsage:
        if size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        current = self.usage(user_id, rank)
        if current.used_bytes + size_bytes > current.quota_bytes:
            raise QuotaExceededError(
                f"Storage quota exceeded: {current.used_bytes + size_bytes} > {current.quota_bytes} bytes"
            )
        return current

    def safe_path(self, user_id: str, relative_path: str) -> Path:
        root = self.user_root(user_id).resolve()
        candidate = (root / relative_path).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("Path escapes user storage")
        return candidate

    def write_bytes(
        self,
        user_id: str,
        relative_path: str,
        content: bytes,
        rank: str = "free",
    ) -> Path:
        with self._write_lock:
            destination = self.safe_path(user_id, relative_path)
            self.assert_can_write(user_id, len(content), rank)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
                temporary.write(content)
                temporary_path = Path(temporary.name)
            temporary_path.replace(destination)
            return destination


_storage_service: StorageQuotaService | None = None


def get_storage_service() -> StorageQuotaService:
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageQuotaService()
    return _storage_service
