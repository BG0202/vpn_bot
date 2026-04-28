"""
keyboards.py — клавиатуры для VPN бота.
"""
 
from dotenv import load_dotenv
load_dotenv()
 
import os
import database as db
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
 
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")   # например: support_guy (без @)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательная функция для кнопки поддержки
# ─────────────────────────────────────────────────────────────────────────────
 
def _support_button():
    """Возвращает кнопку поддержки или None если username не задан."""
    username = SUPPORT_USERNAME.lstrip("@")
    if username:
        return InlineKeyboardButton("🛠 Поддержка", url=f"https://t.me/{username}")
    return None
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Основные клавиатуры
# ─────────────────────────────────────────────────────────────────────────────
 
def main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """
    Главное меню пользователя.
    - Кнопка 'Создать конфиг' — только если конфига ещё нет.
    - Кнопка 'Добавить устройство' — только если конфиг уже есть.
    - Для незарегистрированных (нет подписки) показываем пробный период.
    """
    is_admin = user_id in ADMIN_IDS
    has_config = db.has_any_config(user_id)
    is_active = is_admin or db.is_subscription_active(user_id)
    user = db.get_user(user_id)
    trial_used = user["trial_used"] if user else False
 
    keyboard = []
 
    if is_admin:
        # Админу всегда доступны функции управления конфигами
        if not has_config:
            keyboard.append([InlineKeyboardButton("🔑 Создать конфиг", callback_data="generate_config")])
        else:
            keyboard.append([InlineKeyboardButton("📱 Устройства", callback_data="devices")])
            keyboard.append([InlineKeyboardButton("🔄 Заменить ссылку", callback_data="replace_link")])
        
        # Добавляем кнопку административной панели
        keyboard.append([InlineKeyboardButton("👑 Админ-панель", callback_data="admin_info")])
    else:
        if not is_active:
            # Нет подписки — предлагаем триал или оплату
            if not trial_used:
                keyboard.append([InlineKeyboardButton("🎁 Попробовать бесплатно (7 дней)", callback_data="activate_trial")])
            keyboard.append([InlineKeyboardButton("💳 Оплатить подписку", callback_data="pay")])
        else:
            # Подписка активна
            if not has_config:
                keyboard.append([InlineKeyboardButton("🔑 Создать конфиг", callback_data="generate_config")])
            else:
                keyboard.append([InlineKeyboardButton("📱 Устройства", callback_data="devices")])
                keyboard.append([InlineKeyboardButton("🔄 Заменить ссылку", callback_data="replace_link")])
            keyboard.append([InlineKeyboardButton("💳 Продлить подписку", callback_data="pay")])
 
    support_btn = _support_button()
    if support_btn:
        keyboard.append([support_btn])
 
    return InlineKeyboardMarkup(keyboard)
 
 
def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")]
    ])
 
 
def devices_keyboard(devices: list, user_id: int, device_limit: int) -> InlineKeyboardMarkup:
    """
    Клавиатура для раздела 'Устройства'.
    devices — список записей из clients (все, включая основной конфиг).
    Показывает кнопку 'Добавить устройство' если лимит не исчерпан.
    """
    named = [d for d in devices if d["device_name"] != "Основной конфиг"]
    buttons = []
 
    for dev in named:
        buttons.append([
            InlineKeyboardButton(
                f"❌ {dev['device_name']}",
                callback_data=f"del_device:{dev['id']}"
            )
        ])
 
    if len(named) < device_limit:
        buttons.append([InlineKeyboardButton("➕ Добавить устройство", callback_data="add_device")])
 
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)
 
 
def admin_back_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой возврата в админ-панель"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад в админ-панель", callback_data="admin_clients")]
    ])


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Клиенты", callback_data="admin_clients")],
        [InlineKeyboardButton("🔍 Найти конфиги", callback_data="admin_find_configs")],
        [InlineKeyboardButton(" Выдать конфиг", callback_data="admin_grant")],
        [InlineKeyboardButton("⏰ Продлить подписку", callback_data="admin_extend_manual")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
    ])
 
 
def payment_keyboard(payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Проверить оплату", callback_data=f"check_pay:{payment_id}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
    ])