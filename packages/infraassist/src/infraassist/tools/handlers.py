from infraassist.infrastructure.config import settings
from proxmoxer import ProxmoxAPI


class PVEExeption(Exception):
    def __init__(self, message="PVEExeption"):
        self.message = message
        super().__init__(self.message)


def get_pve_client():
    return ProxmoxAPI(
        settings.pve_host,
        user=settings.pve_user,
        token_name=settings.pve_token_name,
        token_value=settings.pve_token_value,
        verify_ssl=settings.pve_verify_ssl,
    )


def handle_pve_status(
    include_nodes=True, check_quorum_only=False, specific_node=None, **kwargs
) -> str:
    try:
        proxmox = get_pve_client()
        cluster_status = proxmox.cluster.status.get()
        return str(cluster_status)
    except Exception as e:
        raise PVEExeption(str(e))
