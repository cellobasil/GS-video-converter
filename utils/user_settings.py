import json
import os
import logging

SETTINGS_FILE = "user_channels.json"
logger = logging.getLogger(__name__)

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")
        return {}

def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")

def set_user_channel(user_id, channel_id):
    data = load_settings()
    data[str(user_id)] = channel_id
    save_settings(data)

def get_user_channel(user_id):
    data = load_settings()
    return data.get(str(user_id))
