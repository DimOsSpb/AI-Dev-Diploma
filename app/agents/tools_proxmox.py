"""Инструменты агента для Proxmox VE.

Прототип рассчитан на один узел (single-node datacenter, без настоящего
Proxmox-кластера/кворума) — см. README.md (K8s и Linux адаптеры, а также
многоузловой Proxmox-кластер, оставлены как направления развития). Три
инструмента:

- `pve_status` — безопасный read-only инструмент: статус узла(ов).
  `cluster.status.get()` в single-node сетапе возвращает только записи
  с `type == "node"` (без `type == "cluster"`/кворума) — форматтер это учитывает.
- `pve_list_vms` — безопасный read-only инструмент: список VM/CT на узле
  с их статусом (running/stopped), CPU/RAM.
- `pve_create_snapshot` — "опасное" действие (создаёт снапшот тестовой
  VM/CT). Вызов идёт через человека: сама функция инструмента НЕ делает
  реального запроса к API — она лишь объявляет намерение агенту. Настоящий
  вызов Proxmox происходит в HIL-узле `confirm_and_create_snapshot`
  (`app/services/agent_persistent.py`) ПОСЛЕ подтверждения пользователем.

`ProxmoxAPI` (proxmoxer) синхронный — обёрнут в `asyncio.to_thread`, чтобы
не блокировать event loop FastAPI.
"""

import asyncio
import time
from collections import deque

from langchain_core.tools import tool
from proxmoxer import ProxmoxAPI
from proxmoxer.tools.tasks import Tasks

from app.core.config import get_settings
from app.observability.logging import logger


class PVEException(Exception):
    def __init__(self, message: str = "PVEException") -> None:
        self.message = message
        super().__init__(self.message)


class PVEGuardError(PVEException):
    """Снапшот отклонён защитой стенда (не из-за ошибки Proxmox API)."""


# --------------------------------------------------------------------------
# Защита боевого Proxmox-кластера от спама снапшотами.
#
# Прототип ходит в РЕАЛЬНЫЙ домашний кластер автора (см. README.md, раздел
# «Сценарии для проверяющего»). Инструмент опасный по определению (создаёт
# снапшот), поэтому помимо HIL-подтверждения в графе (agent_persistent.py)
# здесь — ещё два независимых барьера перед самим API-вызовом:
#
# 1. Белый список: снапшот разрешён ТОЛЬКО для node+vmid из настроек
#    (PVE_DEFAULT_NODE/PVE_DEFAULT_VMID) — заранее выделенной демо-VM.
#    Любая другая пара node/vmid отклоняется ДО обращения к Proxmox API,
#    независимо от того, что попросил пользователь или модель.
# 2. Rate-limit: не больше `pve_snapshot_rate_limit` подтверждённых снапшотов
#    за скользящее окно `pve_snapshot_rate_window_seconds` на весь процесс
#    (не на пользователя — умышленно строже, т.к. это общий ресурс).
#    In-memory и per-process — осознанно простое решение для прототипа:
#    если понадобится многопроцессный деплой, то же окно нужно хранить в
#    Redis, в текущем single-instance docker compose стенде это избыточно.
_snapshot_calls: deque[float] = deque()


def _check_snapshot_allowed(node: str, vmid: int) -> None:
    settings = get_settings()

    allowed_node = settings.pve_default_node
    allowed_vmid = settings.pve_default_vmid
    if not allowed_node or not allowed_vmid:
        raise PVEGuardError(
            "Снапшоты временно отключены.\n"
            "Причина: не задана демонстрационная VM "
            "(PVE_DEFAULT_NODE/PVE_DEFAULT_VMID)."
        )
    if node != allowed_node or vmid != allowed_vmid:
        raise PVEGuardError(
            "Снапшот отклонён защитой демо-стенда.\n"
            f"Разрешена только демонстрационная VM {allowed_node}/{allowed_vmid}, "
            f"запрошено {node}/{vmid}."
        )

    now = time.monotonic()
    window = settings.pve_snapshot_rate_window_seconds
    limit = settings.pve_snapshot_rate_limit
    while _snapshot_calls and now - _snapshot_calls[0] > window:
        _snapshot_calls.popleft()
    if len(_snapshot_calls) >= limit:
        raise PVEGuardError(
            "Снапшот отклонён защитой демо-стенда.\n"
            f"Превышен лимит ({limit} за {window} сек.) — повторите попытку позже."
        )
    _snapshot_calls.append(now)


def get_pve_client() -> ProxmoxAPI:
    settings = get_settings()
    return ProxmoxAPI(
        settings.pve_host,
        user=settings.pve_user,
        token_name=settings.pve_token_name,
        token_value=settings.pve_token_value.get_secret_value(),
        verify_ssl=settings.pve_verify_ssl,
    )


def _format_cluster_status(
    cluster_status: list[dict],
    include_nodes: bool = True,
    check_quorum_only: bool = False,
    specific_node: str | None = None,
) -> str:
    """Форматирует сырой ответ `cluster.status.get()` в читаемый текст.

    В single-node сетапе (нет настоящего Proxmox-кластера) ответ содержит
    только записи `type == "node"`, без `type == "cluster"` и без кворума —
    в этом случае раздел кворума просто не выводится (он бессмыслен для
    одного узла).
    """
    cluster_info = next(
        (item for item in cluster_status if item.get("type") == "cluster"), None
    )

    result_text = ""
    if cluster_info is not None:
        is_quorate = cluster_info.get("quorate") == 1
        cluster_name = cluster_info.get("name", "Unknown")
        result_text += (
            f"Кластер: {cluster_name}\n"
            f"Кворум: {'Есть' if is_quorate else 'ОТСУТСТВУЕТ'}\n"
        )
        if check_quorum_only:
            return result_text
    else:
        # Нет кластера — это single-node Proxmox (датацентр без кворума).
        result_text += (
            "Режим: одиночный узел Proxmox (не кластер, кворум не применим)\n"
        )
        if check_quorum_only:
            return result_text

    result_text += "\nСостояние узлов:\n"
    nodes_found = False
    for item in cluster_status:
        if item.get("type") != "node":
            continue
        node_name = item.get("name")
        if specific_node and node_name != specific_node:
            continue
        nodes_found = True
        is_online = item.get("online") == 1
        ip_addr = item.get("ip", "unknown")
        status_icon = "🟢" if is_online else "🔴"
        if include_nodes:
            result_text += f"- {status_icon} {node_name} (IP: {ip_addr})\n"
        else:
            result_text += f"- {status_icon} {node_name}\n"
    if not nodes_found:
        result_text += "(узлы не найдены в ответе API)\n"
    return result_text


def _pve_status_sync(
    include_nodes: bool, check_quorum_only: bool, specific_node: str | None
) -> str:
    try:
        proxmox = get_pve_client()
        cluster_status = proxmox.cluster.status.get()
        return _format_cluster_status(
            cluster_status,  # pyright: ignore[reportArgumentType]
            include_nodes,
            check_quorum_only,
            specific_node,
        )
    except Exception as e:
        raise PVEException(str(e)) from e


@tool
async def pve_status(
    include_nodes: bool = True,
    check_quorum_only: bool = False,
    specific_node: str | None = None,
) -> str:
    """Возвращает текущее состояние кластера Proxmox VE: список узлов (нод),
    их сетевой статус (онлайн/оффлайн) и статус кворума.

    Безопасный read-only запрос — вызывать для любых вопросов про
    доступность/состояние кластера или конкретного узла.

    Args:
        include_nodes: вывести детальный список узлов с IP-адресами.
        check_quorum_only: вернуть только статус кворума без деталей по нодам.
        specific_node: имя конкретного узла (например, 'pve-01'), если нужен
            статус только по нему.
    """
    try:
        return await asyncio.to_thread(
            _pve_status_sync, include_nodes, check_quorum_only, specific_node
        )
    except PVEException as e:
        return f"Ошибка при запросе статуса Proxmox:\n{e.message}"


def _format_vm_list(qemu_list: list[dict], lxc_list: list[dict], node: str) -> str:
    """форматирует списои `nodes(node).qemu.get()` и `nodes(node).lxc.get()`
    в единый читаемый текст."""
    if not qemu_list and not lxc_list:
        return f"На узле '{node}' нет виртуальных машин/контейнеров."

    status_icons = {"running": "🟢", "stopped": "⚪", "paused": "🟡"}

    def _format_item(item: dict, kind: str) -> str:
        status = item.get("status", "unknown")
        icon = status_icons.get(status, "❓")
        name = item.get("name", "—")
        vmid = item.get("vmid")
        mem_mb = round(item.get("maxmem", 0) / (1024 * 1024))
        cpus = item.get("cpus", "?")
        return f"- {icon} [{kind}] {vmid} — {name} ({status}, {cpus} vCPU, {mem_mb} MB RAM)"

    lines = [f"Виртуальные машины/контейнеры на узле '{node}':".format(node=node)]
    for vm in sorted(qemu_list, key=lambda x: x.get("vmid", 0)):
        lines.append(_format_item(vm, "VM"))
    for ct in sorted(lxc_list, key=lambda x: x.get("vmid", 0)):
        lines.append(_format_item(ct, "CT"))
    return "\n".join(lines)


def _pve_list_vms_sync(node: str | None) -> str:
    settings = get_settings()
    target_node = node or settings.pve_default_node
    if not target_node:
        raise PVEException("узел не указан и PVE_DEFAULT_NODE не задан в настройках")
    try:
        proxmox = get_pve_client()
        qemu_list = proxmox.nodes(target_node).qemu.get()
        lxc_list = proxmox.nodes(target_node).lxc.get()
        return _format_vm_list(qemu_list, lxc_list, target_node)  # pyright: ignore[reportArgumentType]
    except Exception as e:
        raise PVEException(str(e)) from e


@tool
async def pve_list_vms(node: str | None = None) -> str:
    """Возвращает список виртуальных машин (QEMU) и контейнеров (LXC) на
    узле Proxmox VE с их текущим статусом (running/stopped), числом вCPU и
    выделенной памятью.

    Безопасный read-only запрос — вызывать для вопросов типа "какие VM
    есть", "что сейчас работает/остановлено".

    Args:
        node: имя узла Proxmox. Если не указано — используется узел из
            настроек `PVE_DEFAULT_NODE`.
    """
    try:
        return await asyncio.to_thread(_pve_list_vms_sync, node)
    except PVEException as e:
        return f"Ошибка при запросе списка VM:\n{e.message}"


@tool
def pve_create_snapshot(node: str, vmid: int, snapshot_name: str) -> str:
    """Создаёт снапшот виртуальной машины/контейнера в Proxmox VE.

    Опасное действие — меняет состояние кластера (хоть и безобидно,
    без простоя). Требует подтверждения человека перед выполнением.

    Args:
        node: имя узла Proxmox, на котором находится VM. Используй имя узла
            ровно так, как его называет пользователь или как оно пришло из
            pve_status/pve_list_vms (например, 'pve') — не дополняй и не
            изменяй его по своим предположениям.
        vmid: числовой идентификатор VM/CT, как указал пользователь.
        snapshot_name: имя снапшота (латиница/цифры/дефис, без пробелов).
    """
    # Тело не делает реального вызова: граф перехватывает этот tool_call и
    # проводит его через HIL-гейт (prepare_snapshot -> confirm_and_create_snapshot).
    # Настоящий API-вызов — только после Command(resume=...).
    return "queued-for-approval"


def _resolve_vm_kind(proxmox: ProxmoxAPI, node: str, vmid: int) -> str:
    """Определяет, это QEMU VM или LXC-контейнер.

    Нужно для выбора правильного эндпоинта снапшота: `qemu(vmid).snapshot`
    и `lxc(vmid).snapshot` — разные пути в Proxmox API. Раньше код всегда
    шёл в `qemu(...)`, и для LXC-контейнера API отвечал на несуществующий
    vmid в QEMU-дереве без явной ошибки видимой пользователю.
    """
    qemu_ids = {item.get("vmid") for item in (proxmox.nodes(node).qemu.get() or [])}
    if vmid in qemu_ids:
        return "qemu"
    lxc_ids = {item.get("vmid") for item in (proxmox.nodes(node).lxc.get() or [])}
    if vmid in lxc_ids:
        return "lxc"
    raise PVEException(f"VM/CT с vmid={vmid} не найден на узле '{node}'")


def _create_snapshot_sync(node: str, vmid: int, snapshot_name: str) -> str:
    """Создаёт снапшот и ЖДЁТ завершения фоновой задачи Proxmox.

    `snapshot.post()` в Proxmox API асинхронный: HTTP-ответ 200 с UPID
    приходит сразу же, как только задача поставлена в очередь, а не когда
    снапшот реально создан. Задача может упасть позже на ноде (диск, лок VM
    и т.п.) — без опроса `tasks(upid).status` это осталось бы незамеченным,
    и агент бы бодро репортовал "создан" для снапшота, которого нет.
    """
    _check_snapshot_allowed(node, vmid)
    try:
        proxmox = get_pve_client()
        kind = _resolve_vm_kind(proxmox, node, vmid)
        endpoint = (
            proxmox.nodes(node).qemu(vmid)
            if kind == "qemu"
            else proxmox.nodes(node).lxc(vmid)
        )
        upid = endpoint.snapshot.post(snapname=snapshot_name)

        status = Tasks.blocking_status(proxmox, upid, timeout=120, polling_interval=1)

        if status is None:
            raise PVEException(
                f"задача создания снапшота не завершилась за 120 сек (UPID={upid})"
            )
        if status.get("exitstatus") != "OK":
            raise PVEException(
                f"задача Proxmox завершилась с ошибкой: {status.get('exitstatus')}"
            )

        return f"Снапшот '{snapshot_name}' для {kind.upper()} {vmid} на узле {node} создан."
    except PVEException:
        raise
    except Exception as e:
        logger.app.exception(
            "pve_create_snapshot failed node=%s vmid=%s name=%s",
            node,
            vmid,
            snapshot_name,
        )
        raise PVEException(str(e)) from e


async def create_snapshot(draft: dict) -> str:
    """Реальный side-effect: вызывается ТОЛЬКО из HIL-узла после подтверждения.

    `draft` — `{"node", "vmid", "snapshot_name", "tool_call_id"}`, подготовленный
    узлом `prepare_snapshot` в `app/services/agent_persistent.py`.
    """
    try:
        return await asyncio.to_thread(
            _create_snapshot_sync,
            draft["node"],
            draft["vmid"],
            draft["snapshot_name"],
        )
    except PVEException as e:
        return f"Ошибка при создании снапшота:\n{e.message}"
