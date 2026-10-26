"""Тесты защиты от спама снапшотами (белый список VM + rate-limit).

Прототип ходит в реальный домашний Proxmox-кластер автора (см. README.md),
поэтому `_check_snapshot_allowed` — последний барьер перед настоящим
API-вызовом, независимый от HIL-подтверждения в графе.
"""

from types import SimpleNamespace

import pytest

from app.agents.tools_proxmox import (
    PVEGuardError,
    _check_snapshot_allowed,
    _snapshot_calls,
)


@pytest.fixture(autouse=True)
def _clear_snapshot_calls():
    """Общий in-memory deque — чистим между тестами, иначе они влияют друг на друга."""
    _snapshot_calls.clear()
    yield
    _snapshot_calls.clear()


def _fake_settings(node="pve-01", vmid=100, limit=3, window=600):
    return SimpleNamespace(
        pve_default_node=node,
        pve_default_vmid=vmid,
        pve_snapshot_rate_limit=limit,
        pve_snapshot_rate_window_seconds=window,
    )


def test_allowed_vm_within_limit_passes(monkeypatch):
    monkeypatch.setattr(
        "app.agents.tools_proxmox.get_settings", lambda: _fake_settings()
    )
    # Не должно бросать исключение.
    _check_snapshot_allowed("pve-01", 100)


def test_disallowed_node_or_vmid_rejected(monkeypatch):
    monkeypatch.setattr(
        "app.agents.tools_proxmox.get_settings", lambda: _fake_settings()
    )
    with pytest.raises(PVEGuardError):
        _check_snapshot_allowed("pve-02", 100)
    with pytest.raises(PVEGuardError):
        _check_snapshot_allowed("pve-01", 999)


def test_missing_default_vm_rejected(monkeypatch):
    monkeypatch.setattr(
        "app.agents.tools_proxmox.get_settings",
        lambda: _fake_settings(node="", vmid=0),
    )
    with pytest.raises(PVEGuardError):
        _check_snapshot_allowed("pve-01", 100)


def test_rate_limit_blocks_after_n_calls(monkeypatch):
    monkeypatch.setattr(
        "app.agents.tools_proxmox.get_settings",
        lambda: _fake_settings(limit=2, window=600),
    )
    _check_snapshot_allowed("pve-01", 100)
    _check_snapshot_allowed("pve-01", 100)
    with pytest.raises(PVEGuardError):
        _check_snapshot_allowed("pve-01", 100)


def test_rate_limit_window_expires(monkeypatch):
    monkeypatch.setattr(
        "app.agents.tools_proxmox.get_settings",
        lambda: _fake_settings(limit=1, window=600),
    )
    _check_snapshot_allowed("pve-01", 100)
    with pytest.raises(PVEGuardError):
        _check_snapshot_allowed("pve-01", 100)

    # Искусственно "состариваем" единственную запись — окно истекло.
    _snapshot_calls[0] -= 601
    _check_snapshot_allowed("pve-01", 100)  # теперь снова разрешено
