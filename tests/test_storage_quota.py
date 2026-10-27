from pathlib import Path

import pytest

from src.services.storage.quota import QuotaExceededError, StorageQuotaService


def test_shared_workspace_rejects_path_traversal(tmp_path: Path):
    service = StorageQuotaService(tmp_path / "storage")

    destination = service.write_bytes("user-a", "documents/note.txt", b"hello")

    assert destination.read_bytes() == b"hello"
    assert service.user_root("user-a") == service.user_root("user-b")
    assert destination == (tmp_path / "storage" / "documents" / "note.txt").resolve()
    with pytest.raises(ValueError):
        service.safe_path("user-a", "../../outside.txt")


def test_storage_quota_blocks_write_before_file_creation(tmp_path: Path, monkeypatch):
    service = StorageQuotaService(tmp_path / "storage")
    monkeypatch.setenv("EDUNOTE_STORAGE_QUOTA_BYTES", "4")
    service.write_bytes("user-a", "small.bin", b"1234")

    with pytest.raises(QuotaExceededError):
        service.assert_can_write("user-a", 1, rank="free")

    assert (tmp_path / "storage" / "large.bin").exists() is False
