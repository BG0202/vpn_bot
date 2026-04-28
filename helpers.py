"""
helpers.py — вспомогательные функции.
"""

from datetime import datetime, timezone


DEVICE_ICONS = {
    "iphone": "📱",
    "ipad": "📱",
    "ios": "📱",
    "android": "🤖",
    "xiaomi": "🤖",
    "samsung": "🤖",
    "huawei": "🤖",
    "windows": "🖥",
    "win": "🖥",
    "macos": "💻",
    "mac": "💻",
    "linux": "🐧",
    "ubuntu": "🐧",
    "tv": "📺",
    "router": "📡",
}


def device_icon(name: str) -> str:
    name_lower = name.lower()
    for key, icon in DEVICE_ICONS.items():
        if key in name_lower:
            return icon
    return "📲"


def fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return iso


def is_expired(iso: str | None) -> bool:
    if not iso:
        return True
    try:
        return datetime.fromisoformat(iso) < datetime.utcnow()
    except Exception:
        return True
