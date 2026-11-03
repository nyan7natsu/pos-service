import asyncio
import io

import qrcode
from qrcode import constants


def _generate_qr_bytes_sync(data: str) -> bytes:
    img = qrcode.make(data, error_correction=constants.ERROR_CORRECT_L)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


async def generate_qr_bytes(data: str) -> bytes:
    "QRコードのPNG画像をバイト列で返す"
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _generate_qr_bytes_sync, data)
