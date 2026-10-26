from proxmoxer import ProxmoxAPI

def get_pve_client():
    """Вспомогательная функция для создания клиента API Proxmox.
    В реальном проекте данные берутся из env-переменных или конфига.
    """
    return ProxmoxAPI(
        "192.168.1.100",
        user="root@pam",
        token_name="llm_agent",
        token_value="xxxx-xxxx-xxxx",
        verify_ssl=False
    )

def handle_pve_status(include_nodes=True, check_quorum_only=False, specific_node=None, **kwargs):
    """Реализация обработчика статуса кластера."""
    try:
        proxmox = get_pve_client()
        cluster_status = proxmox.cluster.status.get()

        # 1. Проверяем кворум кластера
        cluster_info = next((item for item in cluster_status if item.get("type") == "cluster"), {})  # pyright: ignore[reportOptionalIterable]
        is_quorate = cluster_info.get("quorate") == 1
        cluster_name = cluster_info.get("name", "Unknown")

        result_text = f"Кластер: {cluster_name}\nКворум: {'Есть' if is_quorate else 'ОТСУТСТВУЕТ'}\n"

        if check_quorum_only:
            return result_text

        # 2. Собираем данные по узлам (нодам)
        result_text += "\nСостояние узлов:\n"
        for item in cluster_status:  # pyright: ignore[reportOptionalIterable]
            if item.get("type") == "node":
                node_name = item.get("name")

                # Если запрашивали конкретную ноду — игнорируем остальные
                if specific_node and node_name != specific_node:
                    continue

                is_online = item.get("online") == 1
                ip_addr = item.get("ip", "unknown")
                status_icon = "🟢" if is_online else "🔴"

                if include_nodes:
                    result_text += f"- {status_icon} {node_name} (IP: {ip_addr})\n"
                else:
                    result_text += f"- {status_icon} {node_name}\n"

        return result_text

    except Exception as e:
        return f"Ошибка при выполнении запроса к Proxmox: {str(e)}"
