import os
import time
import logging
from pyrogram import Client
from pyrogram.types import Message

logger = logging.getLogger(__name__)

async def download_media_with_progress(client: Client, message: Message, directory: str):
    try:
        logger.info(f"Starting download of message {message.id}")
        # Determine file name logic internally by Pyrogram or fallback
        # We pass a directory path ending with separate to treat it as dir
        dl_path = os.path.join(directory, "")
        file_path = await client.download_media(
            message,
            file_name=dl_path,
            progress=progress_callback
        )
        logger.info(f"Download complete: {file_path}")
        return file_path
    except FloodWait:
        raise
    except Exception as e:
        logger.error(f"Error downloading message {message.id}: {e}")
        return None

def progress_callback(current, total):
    # Log every 10%
    percent = current * 100 / total
    if int(percent) % 10 == 0:
        logger.info(f"Downloading: {percent:.1f}%")

