import json
import os
import datetime

HISTORY_FILE = "history.jsonl"

def log_pack(pack_id, meta, status="success", error=None):
    entry = {
        "pack_id": pack_id,
        "timestamp": datetime.datetime.now().isoformat(),
        "status": status,
        "meta": meta,
        "error": str(error) if error else None
    }
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
