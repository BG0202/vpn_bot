import asyncio
import os
from dotenv import load_dotenv
import xray

load_dotenv()

async def test_server_connection():
    print("=== Тест подключения к серверу ===")
    
    # Проверяем переменные окружения
    print("Переменные окружения:")
    for i in (1, 2):
        p = f"SERVER{i}_"
        url = os.getenv(f"{p}PANEL_URL", "")
        print(f"  {p}PANEL_URL: {url}")
        if url:
            print(f"  {p}NAME: {os.getenv(f'{p}NAME', '')}")
            print(f"  {p}PANEL_USER: {os.getenv(f'{p}PANEL_USER', '')}")
            print(f"  {p}HOST: {os.getenv(f'{p}HOST', '')}")
    
    servers = xray.SERVERS
    print(f"\nЗагружено серверов: {len(servers)}")
    
    for server in servers:
        print(f"\nСервер {server.id}: {server.name}")
        print(f"  Panel URL: {server.panel_url}")
        print(f"  Host: {server.host}")
        print(f"  Port: {server.port}")
        print(f"  SNI: {server.sni}")
        print(f"  PBK: {server.pbk}")
        print(f"  SID: {server.sid}")
        
        client = xray.XRayClient(server)
        try:
            print("  Пробуем авторизоваться...")
            await client._login()
            print("  ✅ Авторизация успешна!")
        except Exception as e:
            print(f"  ❌ Ошибка авторизации: {e}")
        finally:
            await client.close()

if __name__ == "__main__":
    asyncio.run(test_server_connection())
