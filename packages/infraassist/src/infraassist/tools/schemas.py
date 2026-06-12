from openai.types.chat import ChatCompletionFunctionToolParam

TOOL_DESC = (
    "Получить текущее состояние кластера Proxmox VE, список узлов (нод), "
    "их сетевой статус (онлайн/оффлайн) и проверку кворума."
)

PARAM_INCLUDE_NODES_DESC = (
    "Нужно ли выводить детальный список всех узлов кластера с их IP-адресами."
)

PARAM_CHECK_QUORUM_DESC = (
    "Если true, функция вернет только статус кворума без деталей по каждой ноде."
)

PARAM_SPECIFIC_NODE_DESC = (
    "Имя конкретного узла (например, 'pve-01'), статус которого нужно проверить."
)

tools: list[ChatCompletionFunctionToolParam] = [
    {
        "type": "function",
        "function": {
            "name": "pve_status",
            "description": TOOL_DESC,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "include_nodes": {
                        "type": "boolean",
                        "description": PARAM_INCLUDE_NODES_DESC,
                        "default": True,
                    },
                    "check_quorum_only": {
                        "type": "boolean",
                        "description": PARAM_CHECK_QUORUM_DESC,
                        "default": False,
                    },
                    "specific_node": {
                        "type": "string",
                        "description": PARAM_SPECIFIC_NODE_DESC,
                    },
                },
                "required": ["include_nodes", "check_quorum_only", "specific_node"],
                "additionalProperties": False,
            },
        },
    }
]
