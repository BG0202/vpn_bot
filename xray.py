import os
import uuid
import logging
import httpx
import json
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

@dataclass
class ServerConfig:
    id: int
    name: str
    panel_url: str
    user: str
    password: str
    inbound_id: int
    host: str
    port: int
    sni: str
    pbk: str
    sid: str
    fp: str

def load_servers() -> list[ServerConfig]:
    servers = []
    for i in (1, 2):
        p = f"SERVER{i}_"
        url = os.getenv(f"{p}PANEL_URL", "").strip().rstrip("/")
        if not url: continue
        
        servers.append(ServerConfig(
            id=i,
            name=os.getenv(f"{p}NAME", f"Сервер {i}"),
            panel_url=url,
            user=os.getenv(f"{p}PANEL_USER", "admin"),
            password=os.getenv(f"{p}PANEL_PASS", ""),
            inbound_id=int(os.getenv(f"{p}INBOUND_ID", "1")),
            host=os.getenv(f"{p}HOST", ""),
            port=int(os.getenv(f"{p}PORT", "443")),
            sni=os.getenv(f"{p}SNI", ""),
            pbk=os.getenv(f"{p}PBK", ""),
            sid=os.getenv(f"{p}SID", ""),
            fp=os.getenv(f"{p}FP", "chrome"),
        ))
    return servers

class XRayClient:
    def __init__(self, server: ServerConfig):
        self.server = server
        # Гарантируем, что URL заканчивается на слэш для корректной склейки путей
        base_url = self.server.panel_url
        if not base_url.endswith('/'):
            base_url += '/'
            
        self._client = httpx.AsyncClient(
            base_url=base_url,
            verify=False,
            timeout=15.0,
            follow_redirects=True
        )
        self._logged_in = False

    async def _login(self):
        # Запрос на авторизацию по относительному пути (приклеится к base_url)
        r = await self._client.post("login", data={
            "username": self.server.user,
            "password": self.server.password,
        })
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            logger.error(f"Login failed: {data}")
            raise RuntimeError(f"3x-ui login failed: {data}")
        self._logged_in = True

    async def _ensure_auth(self):
        if not self._logged_in:
            await self._login()

    async def add_client(self, client_uuid: str, email: str, total_gb: int = 0) -> dict:
        await self._ensure_auth()
        
        # Настройки клиента для протокола VLESS Reality
        client_settings = {
            "id": client_uuid,
            "email": email,
            "limitIp": 0,
            "totalGB": total_gb * 1024 ** 3,
            "expiryTime": 0,
            "enable": True,
            "tgId": "",
            "subId": "",
            "flow": "xtls-rprx-vision" # Обязательно для Reality в новых панелях
        }

        payload = {
            "id": self.server.inbound_id,
            "settings": json.dumps({
                "clients": [client_settings]
            })
        }
        
        # Путь panel/api актуален для версий 2.x.x
        r = await self._client.post("panel/api/inbounds/addClient", json=payload)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            logger.error(f"Add client failed server {self.server.id}: {data}")
            raise RuntimeError(f"add_client failed: {data}")
        return data

    async def delete_client(self, client_uuid: str) -> bool:
        """Удаляет клиента из панели"""
        await self._ensure_auth()
        r = await self._client.post(f"panel/api/inbounds/{self.server.inbound_id}/delClient/{client_uuid}")
        r.raise_for_status()
        return r.json().get("success", False)

    async def close(self):
        await self._client.aclose()

def build_vless_link(server: ServerConfig, uuid: str, remark: str) -> str:
    # Собираем ссылку с правильными параметрами для Reality
    link = (
        f"vless://{uuid}@{server.host}:{server.port}"
        f"?type=tcp"
        f"&security=reality"
        f"&sni={server.sni}"
        f"&fp={server.fp}"
        f"&pbk={server.pbk}"
        f"&sid={server.sid}"
        f"&flow=xtls-rprx-vision"
        f"&spx=%2F"
        f"#{remark}"
    )
    return link

def get_server_by_id(server_id: int) -> Optional[ServerConfig]:
    servers = load_servers()
    for s in servers:
        if s.id == server_id:
            return s
    return None

async def provision_user_on_server(server: ServerConfig, user_id: int, server_index: int) -> tuple[str, str, str]:
    client_uuid = str(uuid.uuid4())
    email = f"tg{user_id}_s{server_index}"
    client = XRayClient(server)
    try:
        await client.add_client(client_uuid, email)
    finally:
        await client.close()
    vless_link = build_vless_link(server, client_uuid, email)
    return client_uuid, email, vless_link

async def remove_user_from_server(server: ServerConfig, client_uuid: str) -> bool:
    client = XRayClient(server)
    try:
        return await client.delete_client(client_uuid)
    finally:
        await client.close()

# Загружаем серверы при импорте модуля
SERVERS = load_servers()