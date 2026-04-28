"""
main.py — точка запуска VPN бота.
"""

import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from telegram.ext import Application

import database as db
import xray
from handlers import setup_handlers
from utils import remove_user_from_server, get_server_by_id

load_dotenv()

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
ADMIN_IDS        = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Фоновая задача: деактивация истёкших подписок
# ─────────────────────────────────────────────────────────────────────────────

async def job_expire_subscriptions(context):
    """
    Запускается каждый час. Находит пользователей с истёкшей подпиской
    и удаляет их клиентов с серверов.
    """
    expired_users = db.get_users_with_expired_subscriptions()
    if not expired_users:
        return

    for user in expired_users:
        user_id = user["user_id"]
        # Пропускаем админов — у них безлимит
        if user_id in ADMIN_IDS:
            continue

        clients = db.get_clients_for_user(user_id)
        if not clients:
            continue

        logger.info(f"Deactivating expired subscription for user {user_id}")

        # Удаляем с серверов уникальных клиентов
        seen_uuid = set()
        for c in clients:
            if c["uuid"] not in seen_uuid:
                seen_uuid.add(c["uuid"])
                server = get_server_by_id(c["server_id"])
                if server:
                    try:
                        await remove_user_from_server(server, c["uuid"])
                        logger.info(f"Removed client {c['uuid']} from server {c['server_id']}")
                    except Exception as e:
                        logger.warning(f"Could not remove {c['uuid']}: {e}")

        # Удаляем все записи из БД
        db.delete_all_clients_for_user(user_id)
        logger.info(f"Cleared configs for expired user {user_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Главная функция
# ─────────────────────────────────────────────────────────────────────────────

async def setup_bot_commands(application):
    """Устанавливает команды меню бота"""
    from telegram import BotCommand
    
    commands = [
        BotCommand("start", "🚀 Начать работу"),
        BotCommand("configs", "📱 Мои конфиги"),
    ]
    
    await application.bot.set_my_commands(commands)
    logger.info("Команды меню установлены")

def main():
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=logging.INFO,
    )

    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN не задан в .env!")

    logger.info("VPN Bot запускается...")

    # Инициализируем базу данных (НЕ очищаем — данные сохраняются между запусками)
    db.init_db()
    logger.info("База данных инициализирована.")

    # Создаём приложение
    application = Application.builder().token(TELEGRAM_TOKEN).connect_timeout(30.0).read_timeout(30.0).write_timeout(30.0).pool_timeout(30.0).build()

    # Регистрируем хендлеры
    setup_handlers(application)

    # Устанавливаем команды меню через initialize
    async def post_init(application: Application) -> None:
        await setup_bot_commands(application)
    
    application.post_init = post_init

    # Добавляем фоновую задачу проверки подписок (каждые 60 минут)
    job_queue = application.job_queue
    job_queue.run_repeating(
        job_expire_subscriptions,
        interval=3600,   # секунд
        first=60,        # первый запуск через 60 сек после старта
        name="expire_subscriptions",
    )
    logger.info("Задача проверки подписок зарегистрирована (интервал 60 мин).")

    logger.info("Бот запущен. Ожидаем сообщения...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()