"""
utils.py — вспомогательные функции для VPN бота.
"""
 
import logging
import os
from datetime import datetime
 
from dotenv import load_dotenv
from telegram import InputFile
from telegram.constants import ParseMode
 
load_dotenv()
 
import database as db
import xray
from keyboards import main_keyboard, back_keyboard, admin_keyboard, devices_keyboard
from qr import make_qr_bytes
 
logger = logging.getLogger(__name__)
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Работа с серверами
# ─────────────────────────────────────────────────────────────────────────────
 
def get_server_by_id(server_id: int):
    for server in xray.SERVERS:
        if server.id == server_id:
            return server
    return None
 
 
def device_icon(name: str) -> str:
    name = name.lower()
    if any(x in name for x in ["iphone", "ios", "ipad"]):
        return "📱"
    if any(x in name for x in ["android", "samsung", "xiaomi", "huawei"]):
        return "📱"
    if any(x in name for x in ["windows", "pc", "notebook", "ноут", "win"]):
        return "💻"
    if any(x in name for x in ["mac", "macbook"]):
        return "🖥"
    if any(x in name for x in ["router", "роутер"]):
        return "📡"
    if any(x in name for x in ["linux", "ubuntu"]):
        return "🐧"
    if any(x in name for x in ["tv", "телевизор"]):
        return "📺"
    return "📲"
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Работа с клиентами на сервере
# ─────────────────────────────────────────────────────────────────────────────
 
async def provision_user_on_server(server: xray.ServerConfig, user_id: int, server_id: int):
    """Создаёт клиента на сервере и возвращает (uuid, email, vless_link)."""
    import uuid as _uuid
    client_uuid = str(_uuid.uuid4())
    email = f"tg{user_id}_s{server_id}"
 
    xray_client = xray.XRayClient(server)
    try:
        await xray_client.add_client(client_uuid, email)
    finally:
        await xray_client.close()
 
    vless_link = xray.build_vless_link(server, client_uuid, f"{server.name}")
    return client_uuid, email, vless_link
 
 
async def remove_user_from_server(server: xray.ServerConfig, client_uuid: str):
    """Удаляет клиента с сервера."""
    xray_client = xray.XRayClient(server)
    try:
        await xray_client.delete_client(client_uuid)
    except Exception as e:
        logger.warning(f"Could not remove client {client_uuid} from server {server.id}: {e}")
    finally:
        await xray_client.close()
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Форматирование даты
# ─────────────────────────────────────────────────────────────────────────────
 
def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return iso
 
 
def _days_left(iso: str | None) -> int:
    if not iso:
        return 0
    try:
        return max(0, (datetime.fromisoformat(iso) - datetime.utcnow()).days)
    except Exception:
        return 0
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Отправка профиля
# ─────────────────────────────────────────────────────────────────────────────
 
async def send_profile(update, context, edit: bool = False):
    """Отправляет/редактирует профиль — без приветствия."""
    user_id = update.effective_user.id

    # Админы видят обычное главное меню с доп. кнопками
    # if user_id in ADMIN_IDS:
    #     await send_admin_profile(update, context, edit)
    #     return
 
    user = db.get_user(user_id)
    if not user:
        # Пользователь не зарегистрирован — сюда не должно доходить, но на всякий случай
        msg = update.message or update.callback_query.message
        await msg.reply_text("Используйте /start для начала работы.")
        return
 
    text = f"👤 *Ваш профиль*\n\n"
    text += f"🆔 ID: `{user_id}`\n"
 
    # Статус подписки
    if user["expires_at"] and db.is_subscription_active(user_id):
        days = _days_left(user["expires_at"])
        text += f"✅ Подписка активна до *{_fmt_date(user['expires_at'])}* ({days} дн.)\n"
    elif user["expires_at"]:
        text += f"❌ Подписка истекла *{_fmt_date(user['expires_at'])}*\n"
    else:
        text += "❌ Нет активной подписки\n"
 
    # Конфиги
    clients = db.get_clients_for_user(user_id)
    if clients:
        # Показываем только основной конфиг (уникальные uuid/сервер)
        shown = set()
        config_lines = []
        for c in clients:
            key = (c["server_id"], c["uuid"])
            if key not in shown:
                shown.add(key)
                srv = get_server_by_id(c["server_id"])
                srv_name = srv.name if srv else f"Сервер {c['server_id']}"
                config_lines.append(f"🌐 *{srv_name}*\n`{c['vless_link']}`")
        text += f"\n📱 *Ваши конфиги ({len(config_lines)}):*\n\n"
        text += "\n\n".join(config_lines)
 
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_keyboard(user_id)
        )
    else:
        msg = update.message or update.callback_query.message
        await msg.reply_text(
            text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_keyboard(user_id)
        )
 
 
async def send_admin_profile(update, context, edit: bool = False):
    """Показывает профиль/панель администратора."""
    user_id = update.effective_user.id
 
    all_users = db.get_all_users()
    active_count = sum(1 for u in all_users if db.is_subscription_active(u["user_id"]))
 
    text = f"👑 *Административная панель*\n\n"
    text += f"🆔 Ваш ID: `{user_id}`\n"
    text += f"👥 Пользователей: {len(all_users)} (активных: {active_count})\n"
 
    # Показываем конфиги самого админа
    clients = db.get_clients_for_user(user_id)
    if clients:
        shown = set()
        for c in clients:
            key = (c["server_id"], c["uuid"])
            if key not in shown:
                shown.add(key)
                srv = get_server_by_id(c["server_id"])
                srv_name = srv.name if srv else f"Сервер {c['server_id']}"
                text += f"\n🌐 *{srv_name}*\n`{c['vless_link']}`"
    else:
        text += "\n📭 У вас нет конфигов."
 
    keyboard = admin_keyboard()
 
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
        )
    else:
        msg = update.message or update.callback_query.message
        await msg.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
        )
 
 
async def send_configs(update, context):
    """Отправляет все конфиги пользователя с QR-кодами (команда /configs)."""
    user_id = update.effective_user.id
    clients = db.get_clients_for_user(user_id)
 
    if not clients:
        msg = update.message or update.callback_query.message
        await msg.reply_text(
            "❌ У вас нет конфигов.\n\nСначала создайте конфиг через главное меню.",
            reply_markup=back_keyboard()
        )
        return
 
    msg = update.message or update.callback_query.message
    await msg.reply_text("📱 *Ваши VPN конфиги:*", parse_mode=ParseMode.MARKDOWN)
 
    # Дедупликация по uuid
    shown = set()
    for c in clients:
        if c["uuid"] in shown:
            continue
        shown.add(c["uuid"])
 
        srv = get_server_by_id(c["server_id"])
        srv_name = srv.name if srv else f"Сервер {c['server_id']}"
 
        caption = f"🌐 *{srv_name}*\n`{c['vless_link']}`"
 
        try:
            qr_bytes = make_qr_bytes(c["vless_link"])
            await msg.reply_photo(qr_bytes, caption=caption, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"QR generation error: {e}")
            await msg.reply_text(caption, parse_mode=ParseMode.MARKDOWN)