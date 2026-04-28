"""
handlers.py — все обработчики команд и callback'ов VPN бота.
"""
 
import logging
import os
 
from dotenv import load_dotenv
load_dotenv()
 
import database as db
import payments as pay
import texts as T
import xray
from keyboards import back_keyboard, payment_keyboard, admin_keyboard, admin_back_keyboard, devices_keyboard
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler, CommandHandler,
    MessageHandler, filters, ContextTypes
)
from utils import (
    get_server_by_id, device_icon,
    provision_user_on_server, remove_user_from_server,
    send_profile, send_admin_profile, send_configs
)
from qr import make_qr_bytes
 
logger = logging.getLogger(__name__)
 
ADMIN_IDS     = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
TRIAL_DAYS    = int(os.getenv("TRIAL_DAYS", "7"))
SUB_DAYS      = int(os.getenv("SUBSCRIPTION_DAYS", "30"))
SUB_PRICE     = int(os.getenv("SUBSCRIPTION_PRICE", "100"))
DEVICE_LIMIT  = 5          # лимит устройств для обычного пользователя
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Команды
# ─────────────────────────────────────────────────────────────────────────────
 
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — регистрирует пользователя и показывает профиль.
    Приветствие намеренно убрано (настроено через BotFather).
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    first_name = update.effective_user.first_name or ""
    db.register_user(user_id, username, first_name)
    await send_profile(update, context)
 
 
async def cmd_configs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /configs — выдаёт все конфиги с QR."""
    await send_configs(update, context)
 
 
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin — вход в админ-панель (только для админов)."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Доступ запрещено.")
        return
    
    # Показываем админ-панель с кнопками
    all_users = db.get_all_users()
    active = sum(1 for u in all_users if db.is_subscription_active(u["user_id"]))

    text = (
        f"ℹ️ *Информация о боте*\n\n"
        f"👥 Пользователей: {len(all_users)}\n"
        f"✅ Активных подписок: {active}\n"
        f"🌐 Серверов: {len(xray.SERVERS)}\n"
        f"👑 Админов: {len(ADMIN_IDS)}\n"
    )
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_keyboard()
    )


async def cmd_admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin_list — список пользователей (только для админов)."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Доступ запрещено.")
        return

    users = db.get_all_users()
    text = f"👥 *Пользователи ({len(users)})*\n\n"
    for u in users[:20]:
        status = "✅" if db.is_subscription_active(u["user_id"]) else "❌"
        uname = f"@{u['username']}" if u["username"] else f"id{u['user_id']}"
        text += f"{status} {uname} — `{u['user_id']}`\n"
    if len(users) > 20:
        text += f"\n_и еще {len(users) - 20}_"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                    reply_markup=admin_back_keyboard())
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Навигация
# ─────────────────────────────────────────────────────────────────────────────
 
async def cb_back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Сбрасываем любое ожидание ввода
    context.user_data.pop("waiting_for_device_name", None)
    context.user_data.pop("main_client_id", None)
    context.user_data.pop("admin_action", None)
    
    try:
        await send_profile(update, context, edit=True)
    except Exception as e:
        # Если сообщение не изменилось, просто игнорируем ошибку
        logger.warning(f"Back button error: {e}")
        pass
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Конфиги
# ─────────────────────────────────────────────────────────────────────────────
 
async def cb_generate_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создаёт основной конфиг для пользователя."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS
 
    # Проверяем: конфиг уже есть?
    if db.has_any_config(user_id):
        await query.answer("У вас уже есть конфиг.", show_alert=True)
        await send_profile(update, context, edit=True)
        return
 
    # Проверяем подписку (для не-админов)
    if not is_admin and not db.is_subscription_active(user_id):
        await query.answer("Подписка не активна.", show_alert=True)
        await send_profile(update, context, edit=True)
        return
 
    await query.edit_message_text("⏳ Создаём конфиг, подождите...")
 
    try:
        for server in xray.SERVERS:
            c_uuid, email, vless = await provision_user_on_server(server, user_id, server.id)
            db.add_client(user_id, server.id, c_uuid, email, vless, device_name="Основной конфиг")
 
        await query.message.reply_text(
            "✅ *Конфиг создан!*\n\n"
            "Нажмите «📱 Устройства» чтобы добавить устройство и получить QR-код.\n"
            "Или используйте команду /configs.",
            parse_mode=ParseMode.MARKDOWN
        )
        await send_profile(update, context)
 
    except Exception as e:
        logger.exception(f"Generate config error for {user_id}: {e}")
        await query.message.reply_text(
            "❌ Не удалось создать конфиг. Попробуйте позже или обратитесь в поддержку.",
            reply_markup=back_keyboard()
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Устройства
# ─────────────────────────────────────────────────────────────────────────────
 
async def cb_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список устройств и кнопку добавления."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS
    limit = 999 if is_admin else DEVICE_LIMIT
 
    # Проверяем подписку
    if not is_admin and not db.is_subscription_active(user_id):
        await query.answer("Подписка не активна.", show_alert=True)
        await send_profile(update, context, edit=True)
        return
 
    clients = db.get_clients_for_user(user_id)
    named = [c for c in clients if c["device_name"] != "Основной конфиг"]
 
    text = "📱 *Ваши устройства*\n\n"
    if named:
        for i, dev in enumerate(named, 1):
            srv = get_server_by_id(dev["server_id"])
            srv_name = srv.name if srv else f"Сервер {dev['server_id']}"
            icon = device_icon(dev["device_name"])
            text += f"{i}. {icon} *{dev['device_name']}* — {srv_name}\n"
        text += "\nНажмите на устройство чтобы удалить его:\n"
    else:
        text += "У вас пока нет добавленных устройств.\n"
 
    if len(named) >= limit and not is_admin:
        text += f"\n⚠️ Достигнут лимит устройств ({DEVICE_LIMIT})."
 
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=devices_keyboard(clients, user_id, limit)
    )
 
 
async def cb_add_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Нажатие «Добавить устройство»:
    отправляет существующий конфиг и просит назвать устройство.
    """
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS
    limit = 999 if is_admin else DEVICE_LIMIT
 
    # Проверяем подписку
    if not is_admin and not db.is_subscription_active(user_id):
        await query.answer("Подписка не активна.", show_alert=True)
        return
 
    # Проверяем что основной конфиг есть
    main_config = db.get_main_client(user_id)
    if not main_config:
        await query.answer("Сначала создайте конфиг!", show_alert=True)
        return
 
    # Проверяем лимит
    named_count = db.count_named_devices(user_id)
    if named_count >= limit:
        await query.answer(
            f"Лимит устройств ({DEVICE_LIMIT}) исчерпан!" if not is_admin else "Лимит исчерпан.",
            show_alert=True
        )
        return
 
    srv = get_server_by_id(main_config["server_id"])
    srv_name = srv.name if srv else "Сервер"
    vless = main_config["vless_link"]
 
    text = (
        f"📱 *Добавление устройства*\n\n"
        f"🔗 *Конфиг для {srv_name}:*\n`{vless}`\n\n"
        f"1️⃣ Скопируйте ссылку или отсканируйте QR-код ниже.\n"
        f"2️⃣ Импортируйте в приложение (v2rayNG, Hiddify, Streisand и др.).\n"
        f"3️⃣ Подключитесь.\n\n"
        f"✍️ *Теперь напишите название этого устройства:*\n"
        f"_(например: iPhone 15, Windows ноутбук)_"
    )
 
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=back_keyboard())
 
    # Отправляем QR
    try:
        qr_bytes = make_qr_bytes(vless)
        await query.message.reply_photo(qr_bytes, caption="📷 QR-код для импорта")
    except Exception as e:
        logger.error(f"QR error for user {user_id}: {e}")
 
    # Включаем режим ожидания названия
    context.user_data["waiting_for_device_name"] = True
    context.user_data["main_client_id"] = main_config["id"]
 
 
async def handle_device_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает название устройства и сохраняет запись."""
    if not context.user_data.get("waiting_for_device_name"):
        return  # Не в режиме ожидания — игнорируем
 
    user_id = update.effective_user.id
    device_name = update.message.text.strip()
 
    if len(device_name) > 50:
        await update.message.reply_text(
            "❌ Название слишком длинное (максимум 50 символов). Попробуйте ещё раз."
        )
        return
 
    if not device_name:
        await update.message.reply_text("❌ Название не может быть пустым. Попробуйте ещё раз.")
        return
 
    # Сбрасываем флаг
    context.user_data.pop("waiting_for_device_name", None)
    main_client_id = context.user_data.pop("main_client_id", None)
 
    if not main_client_id:
        await update.message.reply_text(
            "❌ Не найден основной конфиг. Попробуйте заново.",
            reply_markup=back_keyboard()
        )
        return
 
    try:
        db.update_device_name(main_client_id, user_id, device_name)
        icon = device_icon(device_name)
        await update.message.reply_text(
            f"✅ Устройство {icon} *{device_name}* добавлено!\n\n"
            f"Используйте ту же ссылку для подключения на этом устройстве.",
            parse_mode=ParseMode.MARKDOWN
        )
        await send_profile(update, context)
    except Exception as e:
        logger.exception(f"Error saving device name for {user_id}: {e}")
        await update.message.reply_text(
            "❌ Не удалось сохранить устройство. Попробуйте позже.",
            reply_markup=back_keyboard()
        )
 
 
async def cb_del_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет именованное устройство (запись в clients)."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
 
    try:
        client_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.", show_alert=True)
        return
 
    client = db.get_client_by_id(client_id)
    if not client or client["user_id"] != user_id:
        await query.answer("Устройство не найдено.", show_alert=True)
        return
 
    # Если это единственная запись с данным uuid — удаляем с сервера
    all_clients = db.get_clients_for_user(user_id)
    same_uuid = [c for c in all_clients if c["uuid"] == client["uuid"]]
 
    if len(same_uuid) <= 1:
        # Последняя запись с этим uuid — удаляем клиента с сервера
        server = get_server_by_id(client["server_id"])
        if server:
            await remove_user_from_server(server, client["uuid"])
 
    db.delete_client_by_id(client_id, user_id)
 
    await query.answer("✅ Устройство удалено.")
    # Обновляем экран устройств
    await cb_devices(update, context)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Замена ссылки
# ─────────────────────────────────────────────────────────────────────────────
 
async def cb_replace_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пересоздаёт конфиги пользователя."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
 
    clients = db.get_clients_for_user(user_id)
    if not clients:
        await query.answer("Нет конфигов для замены.", show_alert=True)
        await send_profile(update, context, edit=True)
        return
 
    await query.edit_message_text("⏳ Обновляем ссылки...")
 
    try:
        # Получаем уникальные uuid для удаления
        seen_uuid = set()
        for c in clients:
            if c["uuid"] not in seen_uuid:
                seen_uuid.add(c["uuid"])
                server = get_server_by_id(c["server_id"])
                if server:
                    await remove_user_from_server(server, c["uuid"])
 
        # Удаляем все записи из БД
        db.delete_all_clients_for_user(user_id)
 
        # Создаём новые конфиги
        for server in xray.SERVERS:
            c_uuid, email, vless = await provision_user_on_server(server, user_id, server.id)
            db.add_client(user_id, server.id, c_uuid, email, vless, device_name="Основной конфиг")
 
        await query.message.reply_text(
            "✅ Ссылки обновлены!\n\nИспользуйте /configs чтобы получить новые QR-коды.",
        )
        await send_profile(update, context)
 
    except Exception as e:
        logger.exception(f"Replace link error for {user_id}: {e}")
        await query.message.reply_text(
            "❌ Не удалось обновить ссылки. Попробуйте позже.",
            reply_markup=back_keyboard()
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Триал и оплата
# ─────────────────────────────────────────────────────────────────────────────
 
async def cb_activate_trial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активирует пробный период."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
 
    user = db.get_user(user_id)
    if not user:
        await query.answer("Пользователь не найден.", show_alert=True)
        return
 
    if user["trial_used"]:
        await query.answer("Пробный период уже использован.", show_alert=True)
        return
 
    if db.is_subscription_active(user_id):
        await query.answer("У вас уже активная подписка.", show_alert=True)
        return
 
    db.activate_trial(user_id, TRIAL_DAYS)
    await query.message.reply_text(
        T.TRIAL_ACTIVATED, parse_mode=ParseMode.MARKDOWN
    )
    await send_profile(update, context)
 
 
async def cb_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создаёт платёж YooKassa."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
 
    try:
        payment_id, payment_url = pay.create_payment(user_id)
        text = T.PAYMENT_CREATED.format(price=SUB_PRICE, url=payment_url)
        await query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=payment_keyboard(payment_id)
        )
    except Exception as e:
        logger.exception(f"Payment creation error for {user_id}: {e}")
        await query.edit_message_text(
            "❌ Ошибка при создании платежа. Попробуйте позже.",
            reply_markup=back_keyboard()
        )
 
 
async def cb_check_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет статус платежа."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    payment_id = query.data.split(":", 1)[1]
 
    try:
        if pay.confirm_if_succeeded(payment_id):
            db.extend_subscription(user_id, SUB_DAYS)
            await query.edit_message_text(T.PAYMENT_OK, parse_mode=ParseMode.MARKDOWN)
            await send_profile(update, context)
        else:
            await query.edit_message_text(
                T.PAYMENT_PENDING,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Проверить ещё раз",
                                         callback_data=f"check_pay:{payment_id}")],
                    [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
                ])
            )
    except Exception as e:
        logger.exception(f"Payment check error: {e}")
        await query.edit_message_text(T.PAYMENT_ERROR, reply_markup=admin_back_keyboard())
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Администрирование
# ─────────────────────────────────────────────────────────────────────────────
 
async def cb_admin_clients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ Доступ запрещено.", reply_markup=admin_back_keyboard())
        return
 
    users = db.get_all_users()
    text = f"👥 *Клиенты ({len(users)})*\n\n"
    for u in users[:20]:
        status = "✅" if db.is_subscription_active(u["user_id"]) else "❌"
        configs_count = len(db.get_clients_for_user(u["user_id"]))
        
        if u["username"]:
            # Если есть username - делаем кликабельную ссылку
            user_link = f"[@{u['username']}](https://t.me/{u['username']})"
            text += f"{status} {user_link} — `{u['user_id']}` ({configs_count} конфигов)\n"
        else:
            # Если нет username - показываем имя и делаем ссылку по ID
            display_name = u.get('first_name', 'Пользователь')
            user_link = f"[{display_name}](https://t.me/user?id={u['user_id']})"
            text += f"{status} {user_link} — `{u['user_id']}` ({configs_count} конфигов)\n"
    
    if len(users) > 20:
        text += f"\n…и ещё {len(users) - 20}"
 
    await query.edit_message_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_keyboard()
    )
 
 
async def cb_admin_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ Доступ запрещено.", reply_markup=admin_back_keyboard())
        return
 
    all_users = db.get_all_users()
    active = sum(1 for u in all_users if db.is_subscription_active(u["user_id"]))
 
    text = (
        f"ℹ️ *Информация о боте*\n\n"
        f"👥 Пользователей: {len(all_users)}\n"
        f"✅ Активных подписок: {active}\n"
        f"🌐 Серверов: {len(xray.SERVERS)}\n"
        f"👑 Админов: {len(ADMIN_IDS)}\n"
    )
    await query.edit_message_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_keyboard()
    )
 
 
async def cb_admin_extend_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ Доступ запрещено.", reply_markup=admin_back_keyboard())
        return
    await query.edit_message_text(
        "⏰ *Продление подписки*\n\n"
        "Отправьте ID пользователя и количество дней через пробел:\n"
        "Пример: `123456789 30`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_back_keyboard()
    )
    context.user_data["admin_action"] = "extend_subscription"
 
 
async def cb_admin_find_configs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает ID пользователя для показа его конфигов."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ Доступ запрещено.", reply_markup=admin_back_keyboard())
        return
    
    await query.edit_message_text(
        "🔍 *Поиск конфигов пользователя*\n\n"
        "Отправьте Telegram ID пользователя чтобы увидеть все его конфиги:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_back_keyboard()
    )
    context.user_data["admin_action"] = "find_configs"


async def cb_admin_grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ Доступ запрещено.", reply_markup=admin_back_keyboard())
        return
    await query.edit_message_text(
        "📤 *Выдача конфига*\n\n"
        "Отправьте Telegram ID пользователя которому нужно выдать конфиг:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_back_keyboard()
    )
    context.user_data["admin_action"] = "grant_config"
 
 
async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений в режиме admin_action."""
    action = context.user_data.get("admin_action")
    if not action:
        return False  # Не наш случай
 
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return False
 
    text = update.message.text.strip()
    context.user_data.pop("admin_action", None)
 
    if action == "find_configs":
        if not text.isdigit():
            await update.message.reply_text(
                "❌ Укажите числовой Telegram ID.",
                reply_markup=admin_back_keyboard()
            )
            return True
        target_id = int(text)
        target = db.get_user(target_id)
        if not target:
            await update.message.reply_text(
                T.ADMIN_USER_NOT_FOUND.format(user_id=target_id),
                parse_mode=ParseMode.MARKDOWN, reply_markup=admin_back_keyboard()
            )
            return True
        
        clients = db.get_clients_for_user(target_id)
        uname = f"@{target['username']}" if target["username"] else f"id{target_id}"
        
        if not clients:
            await update.message.reply_text(
                f"📭 У пользователя {uname} нет конфигов.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=admin_back_keyboard()
            )
            return True
        
        text = f"📱 *Конфиги пользователя {uname}:*\n\n"
        for c in clients:
            srv = get_server_by_id(c["server_id"])
            srv_name = srv.name if srv else f"Сервер {c['server_id']}"
            text += f"🌐 *{srv_name}*\n`{c['vless_link']}`\n\n"
        
        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_back_keyboard()
        )
        return True

    elif action == "extend_subscription":
        parts = text.split()
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            await update.message.reply_text(
                "❌ Неверный формат. Пример: `123456789 30`",
                parse_mode=ParseMode.MARKDOWN, reply_markup=admin_back_keyboard()
            )
            return True
        target_id, days = int(parts[0]), int(parts[1])
        target = db.get_user(target_id)
        if not target:
            await update.message.reply_text(
                T.ADMIN_USER_NOT_FOUND.format(user_id=target_id),
                parse_mode=ParseMode.MARKDOWN, reply_markup=admin_back_keyboard()
            )
            return True
        new_exp = db.extend_subscription(target_id, days)
        await update.message.reply_text(
            T.ADMIN_EXTENDED.format(user_id=target_id, expires=new_exp[:10]),
            parse_mode=ParseMode.MARKDOWN, reply_markup=admin_back_keyboard()
        )
 
    elif action == "grant_config":
        if not text.isdigit():
            await update.message.reply_text(
                "❌ Укажите числовой Telegram ID.", reply_markup=admin_back_keyboard()
            )
            return True
        target_id = int(text)
        target = db.get_user(target_id)
        if not target:
            await update.message.reply_text(
                T.ADMIN_USER_NOT_FOUND.format(user_id=target_id),
                parse_mode=ParseMode.MARKDOWN, reply_markup=admin_back_keyboard()
            )
            return True
        if db.has_any_config(target_id):
            await update.message.reply_text(
                f"⚠️ У пользователя `{target_id}` уже есть конфиг.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=admin_back_keyboard()
            )
            return True
        try:
            for server in xray.SERVERS:
                c_uuid, email, vless = await provision_user_on_server(server, target_id, server.id)
                db.add_client(target_id, server.id, c_uuid, email, vless)
            await update.message.reply_text(
                f"✅ Конфиг выдан пользователю `{target_id}`.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=admin_back_keyboard()
            )
        except Exception as e:
            logger.exception(f"Admin grant config error: {e}")
            await update.message.reply_text(
                "❌ Ошибка при создании конфига.", reply_markup=admin_back_keyboard()
            )
 
    return True
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Общий обработчик текстовых сообщений
# ─────────────────────────────────────────────────────────────────────────────
 
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Маршрутизатор текстовых сообщений:
    1. Если ждём названия устройства — обрабатываем.
    2. Если админский режим ввода — обрабатываем.
    3. Иначе — игнорируем (или подсказываем).
    """
    # Сначала проверяем режим устройства
    if context.user_data.get("waiting_for_device_name"):
        await handle_device_name(update, context)
        return
 
    # Потом режим администратора
    if await handle_admin_message(update, context):
        return
 
    # Всё остальное — отправляем в профиль
    # (опционально, можно убрать эти строки если не нужно)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Регистрация обработчиков
# ─────────────────────────────────────────────────────────────────────────────
 
def setup_handlers(application):
    # Команды
    application.add_handler(CommandHandler("start",      cmd_start))
    application.add_handler(CommandHandler("configs",    cmd_configs))
    application.add_handler(CommandHandler("admin",      cmd_admin))
    application.add_handler(CommandHandler("admin_list", cmd_admin_list))
 
    # Навигация
    application.add_handler(CallbackQueryHandler(cb_back_main,    pattern="^back_main$"))
 
    # Конфиги
    application.add_handler(CallbackQueryHandler(cb_generate_config, pattern="^generate_config$"))
    application.add_handler(CallbackQueryHandler(cb_replace_link,    pattern="^replace_link$"))
 
    # Устройства
    application.add_handler(CallbackQueryHandler(cb_devices,    pattern="^devices$"))
    application.add_handler(CallbackQueryHandler(cb_add_device, pattern="^add_device$"))
    application.add_handler(CallbackQueryHandler(cb_del_device, pattern="^del_device:"))
 
    # Триал и оплата
    application.add_handler(CallbackQueryHandler(cb_activate_trial, pattern="^activate_trial$"))
    application.add_handler(CallbackQueryHandler(cb_pay,            pattern="^pay$"))
    application.add_handler(CallbackQueryHandler(cb_check_pay,      pattern="^check_pay:"))
 
    # Админ
    application.add_handler(CallbackQueryHandler(cb_admin_clients,        pattern="^admin_clients$"))
    application.add_handler(CallbackQueryHandler(cb_admin_find_configs,  pattern="^admin_find_configs$"))
    application.add_handler(CallbackQueryHandler(cb_admin_grant,          pattern="^admin_grant$"))
    application.add_handler(CallbackQueryHandler(cb_admin_extend_manual,  pattern="^admin_extend_manual$"))
    application.add_handler(CallbackQueryHandler(cb_admin_info,           pattern="^admin_info$"))
 
    # Текстовые сообщения (названия устройств + админ ввод)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )