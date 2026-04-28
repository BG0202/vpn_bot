"""
qr.py — генерация QR-кода из VLESS-ссылки в байты PNG.
"""

import io
import qrcode
from qrcode.image.pure import PyPNGImage


def make_qr_bytes(data: str) -> bytes:
    """Генерирует QR-код и возвращает PNG в виде bytes."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=8,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)
    return buf.read()
