import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TARGET_CHANNEL_ID_RAW = os.getenv("TARGET_CHANNEL_ID", "")
# Handle both numeric IDs and invite links
try:
    TARGET_CHANNEL_ID = int(TARGET_CHANNEL_ID_RAW)
except ValueError:
    TARGET_CHANNEL_ID = TARGET_CHANNEL_ID_RAW  # Use as string (invite link)

# Parse allowed users
allowed_users_str = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS = [int(u.strip()) for u in allowed_users_str.split(",") if u.strip().isdigit()]

WORK_DIR = os.getenv("WORK_DIR", "downloads")
os.makedirs(WORK_DIR, exist_ok=True)
