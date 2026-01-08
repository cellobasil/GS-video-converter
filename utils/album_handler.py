import asyncio
from typing import Dict, List
from pyrogram.types import Message

class AlbumCollector:
    def __init__(self):
        self.albums: Dict[str, List[Message]] = {}
        self.timers: Dict[str, asyncio.Task] = {}

    def add_message(self, group_id: str, message: Message):
        if group_id not in self.albums:
            self.albums[group_id] = []
        self.albums[group_id].append(message)
        # Sort by message id to keep order
        self.albums[group_id].sort(key=lambda m: m.id)

    def get_album(self, group_id: str) -> List[Message]:
        return self.albums.pop(group_id, [])

    def clear_timer(self, group_id: str):
        if group_id in self.timers:
            task = self.timers.pop(group_id)
            task.cancel()
