"""
payments.py — создание и проверка платежей через YooKassa SDK.
"""
 
import os
import uuid
import logging
from typing import Optional
 
import database as db
 
logger = logging.getLogger(__name__)
 
PRICE = float(os.getenv("SUBSCRIPTION_PRICE", "100"))
RETURN_URL = os.getenv("YOOKASSA_RETURN_URL", "https://t.me/your_bot")
 
 
def init_yookassa():
    from yookassa import Configuration
    Configuration.account_id = os.getenv("YOOKASSA_ACCOUNT_ID")
    Configuration.secret_key = os.getenv("YOOKASSA_API_KEY")
 
 
def create_payment(user_id: int) -> tuple[str, str]:
    """
    Создаёт платёж в YooKassa.
    Возвращает (payment_id, confirmation_url).
    """
    idempotency_key = str(uuid.uuid4())
    payment = Payment.create({
        "amount": {
            "value": f"{PRICE:.2f}",
            "currency": "RUB",
        },
        "confirmation": {
            "type": "redirect",
            "return_url": RETURN_URL,
        },
        "capture": True,
        "description": f"Pythoon VPN — подписка 1 месяц (tg:{user_id})",
        "metadata": {
            "user_id": str(user_id),
        },
    }, idempotency_key)
 
    db.create_payment(user_id, payment.id, PRICE)
    logger.info(f"Created payment {payment.id} for user {user_id}")
    return payment.id, payment.confirmation.confirmation_url
 
 
def check_payment(payment_id: str) -> str:
    """
    Запрашивает статус платежа у YooKassa.
    Возвращает статус: 'pending' | 'succeeded' | 'canceled'
    """
    try:
        payment = Payment.find_one(payment_id)
        return payment.status
    except Exception as e:
        logger.error(f"YooKassa error checking {payment_id}: {e}")
        return "error"
 
 
def confirm_if_succeeded(payment_id: str) -> bool:
    """
    Проверяет платёж и если succeeded — помечает в БД.
    Возвращает True если платёж прошёл успешно.
    """
    status = check_payment(payment_id)
    if status == "succeeded":
        db.confirm_payment(payment_id)
        return True
    return False