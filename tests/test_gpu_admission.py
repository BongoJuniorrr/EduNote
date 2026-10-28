from types import SimpleNamespace
import sys
import pytest
from src.services.queue.gpu import GpuResourceManager


def test_embedding_residency_does_not_block_an_otherwise_available_gpu(tmp_path,monkeypatch):
    manager=GpuResourceManager(tmp_path/'gpu.lock')
    monkeypatch.setattr(manager,'_device_count',lambda:1)
    monkeypatch.setattr(manager,'_memory',lambda i:(16*1024**3,5*1024**3))
    with manager as lease:assert lease.index==0
    assert manager._lock_handle is None


def test_vram_budget_and_lease_lock_have_bounded_waits(tmp_path,monkeypatch):
    first=GpuResourceManager(tmp_path/'gpu.lock');second=GpuResourceManager(tmp_path/'gpu.lock')
    for manager in [first,second]:
        monkeypatch.setattr(manager,'_device_count',lambda:1)
        monkeypatch.setattr(manager,'_memory',lambda i:(16*1024**3,0))
    with first:
        with pytest.raises(TimeoutError):second.acquire(.02)
    assert second._lock_handle is None
    monkeypatch.setattr(second,'_memory',lambda i:(16*1024**3,15*1024**3))
    with pytest.raises(TimeoutError):second.acquire(.02)
    assert second._lock_handle is None


def test_admission_uses_logical_torch_devices_not_physical_nvml(tmp_path,monkeypatch):
    seen=[]
    fake=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True,device_count=lambda:1,mem_get_info=lambda index:(seen.append(index) or (12*1024**3,16*1024**3))))
    monkeypatch.setitem(sys.modules,'torch',fake)
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES','1')
    with GpuResourceManager(tmp_path/'gpu.lock') as lease:assert lease.index==0
    assert seen==[0]
