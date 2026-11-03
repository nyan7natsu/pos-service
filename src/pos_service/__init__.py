import logging
import os
import sys
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

from .pos import GeneralConfig, POSService


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        "pos.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


def get_id() -> str:
    file = Path("pos.id")
    if file.exists():
        return file.read_text().strip()
    else:
        id = str(uuid.uuid4())
        file.write_text(id)
        return id


def run():
    load_dotenv()

    setup_logging()

    discord_token = os.getenv("DISCORD_TOKEN", "")

    host = os.getenv("HOST", "127.0.0.1")

    port = int(os.getenv("PORT", "8080"))

    guild_ids_str = os.getenv("GUILD_IDS", "")
    guild_ids = [int(gid) for gid in guild_ids_str.split(",") if gid]

    cogs_str = os.getenv("COGS", "")
    cogs = [cog.strip() for cog in cogs_str.split(",") if cog.strip()]

    lease_api_url = os.getenv("LEASE_API_URL", "http://localhost:8000")

    lease_label = os.getenv("LEASE_LABEL", "default")

    report_channel_id_str = os.getenv("REPORT_CHANNEL_ID", "")
    report_channel_id = int(report_channel_id_str) if report_channel_id_str else 0

    sys.setrecursionlimit(10000)

    pos = POSService(
        id=get_id(),
        conf=GeneralConfig(
            discord_token=discord_token,
            host=host,
            port=port,
            guild_ids=guild_ids,
            cogs=cogs,
            lease_api_url=lease_api_url,
            lease_label=lease_label,
            report_channel_id=report_channel_id,
        ),
    )
    pos.run()


def main():
    try:
        run()
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    except Exception as e:
        logging.exception(f"Unhandled exception: {e}")
    finally:
        logging.info("POS Service stopped.")
