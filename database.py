"""
database.py — SQLite-хранилище для VPN бота.
 
Таблицы:
  users       — пользователи и сроки подписки
  clients     — клиенты в 3x-ui (uuid, сервер, vless_link, device_name)
  payments    — история платежей YooKassa
"""
 
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional
 
DB_PATH = os.getenv("DB_PATH", "vpn_bot.db")
 
 
@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Инициализация
# ─────────────────────────────────────────────────────────────────────────────
 
def init_db():
    with get_conn() as conn:
        # Создаем таблицу users
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at  TEXT,
            trial_used  INTEGER NOT NULL DEFAULT 0
        );
        """)
        
        # Проверяем и добавляем колонку first_name если она не существует
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'first_name' not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
        
        # Создаем остальные таблицы
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS clients (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            server_id   INTEGER NOT NULL,
            uuid        TEXT NOT NULL,
            email       TEXT NOT NULL,
            vless_link  TEXT,
            device_name TEXT NOT NULL DEFAULT 'Основной конфиг',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
 
        CREATE TABLE IF NOT EXISTS payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            payment_id      TEXT NOT NULL UNIQUE,
            amount          REAL NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            confirmed_at    TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        """)
 
        # Миграция: добавляем device_name если его нет
        try:
            conn.execute("ALTER TABLE clients ADD COLUMN device_name TEXT DEFAULT 'Основной конфиг'")
        except Exception:
            pass
 
        conn.execute(
            "UPDATE clients SET device_name = 'Основной конфиг' "
            "WHERE device_name IS NULL OR device_name = ''"
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────────────────────────────────────
 
def get_user(user_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
 
 
def get_all_users() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
 
 
def register_user(user_id: int, username: str = None, first_name: str = None):
    """Регистрирует нового пользователя если его нет."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
            (user_id, username or "", first_name or "")
        )
 
 
def upsert_user(user_id: int, username: str):
    """Создаёт пользователя если его нет, иначе обновляет username."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (user_id, username) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
        """, (user_id, username or ""))
 
 
def activate_trial(user_id: int, days: int):
    expires = (datetime.utcnow() + timedelta(days=days)).isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute("""
            UPDATE users SET expires_at = ?, trial_used = 1
            WHERE user_id = ?
        """, (expires, user_id))
 
 
def extend_subscription(user_id: int, days: int) -> str:
    """Продлевает подписку от текущей даты истечения (или от сейчас, если уже истекла)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT expires_at FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        now = datetime.utcnow()
        if row and row["expires_at"]:
            try:
                base = datetime.fromisoformat(row["expires_at"])
            except ValueError:
                base = now
            base = max(base, now)
        else:
            base = now
        new_expires = (base + timedelta(days=days)).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE users SET expires_at = ? WHERE user_id = ?",
            (new_expires, user_id)
        )
    return new_expires
 
 
def is_subscription_active(user_id: int) -> bool:
    user = get_user(user_id)
    if not user or not user["expires_at"]:
        return False
    try:
        return datetime.fromisoformat(user["expires_at"]) > datetime.utcnow()
    except ValueError:
        return False
 
 
def get_users_with_expired_subscriptions() -> list:
    """Возвращает пользователей у которых подписка истекла (для деактивации)."""
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM users
            WHERE expires_at IS NOT NULL
            AND expires_at <= datetime('now')
        """).fetchall()
 
 
def count_active_users_on_server(server_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT COUNT(DISTINCT c.user_id) as cnt
            FROM clients c
            JOIN users u ON u.user_id = c.user_id
            WHERE c.server_id = ? AND u.expires_at > datetime('now')
        """, (server_id,)).fetchone()
        return row["cnt"] if row else 0
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Clients
# ─────────────────────────────────────────────────────────────────────────────
 
def get_clients_for_user(user_id: int) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM clients WHERE user_id = ?", (user_id,)
        ).fetchall()
 
 
def get_client_by_id(client_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
 
 
def get_main_client(user_id: int) -> Optional[sqlite3.Row]:
    """Возвращает основной конфиг пользователя (первый по серверу 1)."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM clients WHERE user_id = ? AND device_name = 'Основной конфиг' LIMIT 1",
            (user_id,)
        ).fetchone()
 
 
def has_any_config(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM clients WHERE user_id = ?", (user_id,)
        ).fetchone()
        return (row["cnt"] if row else 0) > 0
 
 
def add_client(user_id: int, server_id: int, uuid: str, email: str,
               vless_link: str, device_name: str = "Основной конфиг"):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO clients (user_id, server_id, uuid, email, vless_link, device_name)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, server_id, uuid, email, vless_link, device_name))
 
 
def update_client(client_id: int, new_uuid: str, new_email: str, new_vless: str):
    with get_conn() as conn:
        conn.execute("""
            UPDATE clients SET uuid = ?, email = ?, vless_link = ?
            WHERE id = ?
        """, (new_uuid, new_email, new_vless, client_id))
 
 
def update_device_name(client_id: int, user_id: int, device_name: str):
    """Добавляет именованное устройство — создаёт новую запись с тем же конфигом."""
    # Берём данные основного клиента чтобы скопировать ссылку
    with get_conn() as conn:
        main = conn.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        if not main:
            raise ValueError(f"Client {client_id} not found")
        conn.execute("""
            INSERT INTO clients (user_id, server_id, uuid, email, vless_link, device_name)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (main["user_id"], main["server_id"], main["uuid"],
              main["email"], main["vless_link"], device_name))
 
 
def delete_client_by_id(client_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM clients WHERE id = ? AND user_id = ?",
            (client_id, user_id)
        )
 
 
def delete_all_clients_for_user(user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM clients WHERE user_id = ?", (user_id,))
 
 
def count_named_devices(user_id: int) -> int:
    """Количество именованных устройств (не считая 'Основной конфиг')."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM clients WHERE user_id = ? AND device_name != 'Основной конфиг'",
            (user_id,)
        ).fetchone()
        return row["cnt"] if row else 0
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Payments
# ─────────────────────────────────────────────────────────────────────────────
 
def create_payment(user_id: int, payment_id: str, amount: float):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO payments (user_id, payment_id, amount, status)
            VALUES (?, ?, ?, 'pending')
        """, (user_id, payment_id, amount))
 
 
def confirm_payment(payment_id: str):
    with get_conn() as conn:
        conn.execute("""
            UPDATE payments
            SET status = 'succeeded', confirmed_at = datetime('now')
            WHERE payment_id = ?
        """, (payment_id,))
 
 
def get_payment(payment_id: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM payments WHERE payment_id = ?", (payment_id,)
        ).fetchone()
 
 
def get_pending_payments() -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM payments WHERE status = 'pending'"
        ).fetchall()