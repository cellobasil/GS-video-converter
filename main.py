import asyncio
import os
import random
import string
import datetime
import logging
import shutil
import time
from pyrogram import Client, filters
from pyrogram.types import Message, InputMediaPhoto, InputMediaDocument, InputMediaVideo
from pyrogram.errors import FloodWait
from config import API_ID, API_HASH, BOT_TOKEN, TARGET_CHANNEL_ID, ALLOWED_USER_IDS, WORK_DIR
from utils.album_handler import AlbumCollector
from utils.downloader import download_media_with_progress
from utils.compressor import compress_video

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Server-Optimized: Defensive workers
app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=8)
collector = AlbumCollector()

# Dynamic Authorization
AUTHORIZED_USERS = set(ALLOWED_USER_IDS)
PASS = "gemstock123"

# Chronological Sequential Queue
publish_queue = asyncio.Queue()

# Tracks last arrival per group for settlement
group_metadata = {} # {gid: {"last_update": float, "first_id": int}}

def generate_pack_id():
    now = datetime.datetime.now()
    ts = now.strftime("%Y%m%d-%H%M%S")
    rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"GS-{ts}-{rand}"

async def process_media_item(i, msg: Message, pack_dir, is_visual_album, chat_id):
    """Utility to process media. Gallery items (photo/video) are relayed instantly."""
    try:
        # User Requirement: Skip processing for gallery Photo/Video
        if msg.photo or msg.video:
            logger.info(f"[{i+1}] Bypassing process for gallery media...")
            # Relay using original file_id to buffer
            for relay_attempt in range(5):
                try:
                    if msg.photo:
                        m = await app.send_photo(chat_id, photo=msg.photo.file_id, disable_notification=True)
                        return m.id, m.photo.file_id, msg.caption or ""
                    elif msg.video:
                        # We relay video as photo/video to maintain 'Gallery' look if needed
                        # But if user wants a 'Pack', we might need to send as document.
                        # However, user said "just forwarded", so we keep the type.
                        m = await app.send_video(chat_id, video=msg.video.file_id, disable_notification=True)
                        return m.id, m.video.file_id, msg.caption or ""
                except FloodWait as e:
                    await asyncio.sleep(e.value + 2)
                except Exception as e:
                    logger.error(f"Gallery relay failed: {e}")
                    await asyncio.sleep(2)
            return None

        # Requirement: Compression only for videos sent as FILES (documents)
        path = None
        for attempt in range(10):
            try:
                path = await download_media_with_progress(app, msg, pack_dir)
                if path and os.path.exists(path) and os.path.getsize(path) > 0:
                    break
            except FloodWait as e:
                await asyncio.sleep(e.value + 2)
            except Exception as e:
                logger.error(f"Download error: {e}")
                await asyncio.sleep(3)

        if not path or not os.path.exists(path): return None
        
        orig_name = msg.document.file_name if msg.document else os.path.basename(path)
        is_video_file = msg.document and "video" in (msg.document.mime_type or "")
        tmp_out = os.path.join(pack_dir, f"proc_{orig_name}")
        
        if is_video_file:
            success, err = await asyncio.get_running_loop().run_in_executor(None, compress_video, path, tmp_out)
            if not success:
                logger.error(f"FFmpeg failed. Sending original document.")
                shutil.copy2(path, tmp_out)
        else:
            shutil.copy2(path, tmp_out)
            
        final_path = os.path.join(pack_dir, orig_name).replace("\\", "/")
        if os.path.exists(final_path): os.remove(final_path)
        os.rename(tmp_out, final_path)
        
        # Relay as Document (to maintain file list look)
        for relay_attempt in range(5):
            try:
                m = await app.send_document(chat_id, document=final_path, force_document=True, disable_notification=True)
                return m.id, m.document.file_id, msg.caption or ""
            except FloodWait as e:
                await asyncio.sleep(e.value + 2)
            except Exception as e:
                logger.error(f"Document relay failed: {e}")
                await asyncio.sleep(2)
        return None
    except Exception as e:
        logger.exception(f"[{i+1}] Pipeline exception")
        return None

async def sequencer_worker():
    """Ensures everything enters publish_queue in chronological ID order."""
    logger.info("Sequencer worker active.")
    while True:
        await asyncio.sleep(1)
        if not collector.albums: continue
        
        sorted_gids = sorted(collector.albums.keys(), key=lambda g: group_metadata.get(g, {}).get("first_id", 0))
        
        for gid in sorted_gids:
            meta = group_metadata.get(gid)
            if not meta: continue
            
            # Settle period: 4 seconds of silence
            if (time.time() - meta["last_update"]) > 4.0:
                if gid != sorted_gids[0]: break # Wait for older
                
                msgs = collector.get_album(gid)
                group_metadata.pop(gid, None)
                if not msgs: continue
                
                if len(msgs) == 1:
                    m = msgs[0]
                    if m.text: await publish_queue.put({"type": "text", "msg": m})
                    elif m.sticker: await publish_queue.put({"type": "sticker", "msg": m})
                    else: await publish_queue.put({"type": "media_pack", "messages": msgs})
                else:
                    await publish_queue.put({"type": "media_pack", "messages": msgs})
                break 

async def publisher_worker():
    """Executes publishing and processing tasks from the queue."""
    logger.info("Publisher worker active.")
    while True:
        task = await publish_queue.get()
        try:
            task_type = task.get("type")
            if task_type == "text":
                msg = task["msg"]
                await app.send_message(TARGET_CHANNEL_ID, msg.text)
                await msg.reply_text("✅ Title published.")
            elif task_type == "sticker":
                msg = task["msg"]
                await app.send_sticker(TARGET_CHANNEL_ID, msg.sticker.file_id)
                await msg.reply_text("✅ Sticker published.")
            elif task_type == "media_pack":
                messages = task["messages"]
                chat_id = messages[0].chat.id
                status_msg = await messages[0].reply_text("🛰️ Processing pack...")
                
                # Check if this should be a visual album (all are gallery photo/video)
                # or a file pack (at least one is a document).
                any_doc = any(msg.document for msg in messages)
                is_visual_album = not any_doc
                
                pack_dir = os.path.join(WORK_DIR, generate_pack_id())
                os.makedirs(pack_dir, exist_ok=True)
                start_time = datetime.datetime.now()

                try:
                    results = []
                    for i, m in enumerate(messages):
                        res = await process_media_item(i, m, pack_dir, is_visual_album, chat_id)
                        if res: results.append(res)
                        await asyncio.sleep(1.5)

                    if results:
                        media = []
                        for r in results:
                            # If it was returned from a photo relay, use InputMediaPhoto
                            # We can check the type from Pyrogram or use is_visual_album as hint
                            if is_visual_album:
                                # This is slightly tricky as InputMediaPhoto/Video need to match
                                # But results[1] is just a file_id. 
                                # We can check the original messages.
                                orig_msg = next((m for m in messages if (m.photo and m.photo.file_id in r) or (m.video and m.video.file_id in r)), messages[0])
                                if orig_msg.photo: media.append(InputMediaPhoto(media=r[1], caption=r[2]))
                                else: media.append(InputMediaVideo(media=r[1], caption=r[2]))
                            else:
                                media.append(InputMediaDocument(media=r[1], caption=r[2]))
                        
                        for offset in range(0, len(media), 10):
                            await app.send_media_group(TARGET_CHANNEL_ID, media=media[offset:offset+10])
                        
                        temp_ids = [r[0] for r in results]
                        asyncio.create_task(app.delete_messages(chat_id, temp_ids))
                        dur = (datetime.datetime.now() - start_time).total_seconds()
                        await status_msg.edit_text(f"✅ Published in {dur:.1f}s!")
                    else:
                        await status_msg.edit_text("❌ Failed.")
                finally:
                    shutil.rmtree(pack_dir, ignore_errors=True)
        except Exception as e:
            logger.exception("Publisher fail")
        finally:
            publish_queue.task_done()
            await asyncio.sleep(1.5)

@app.on_message(filters.private & (filters.text | filters.sticker | filters.photo | filters.video | filters.document) & ~filters.command(["start", "setup", "channel"]))
async def handle_everything(client, message):
    if message.from_user.id not in AUTHORIZED_USERS: return
    gid = message.media_group_id or f"solo_{message.id}"
    collector.add_message(gid, message)
    if gid not in group_metadata:
        group_metadata[gid] = {"first_id": message.id, "last_update": time.time()}
    else:
        group_metadata[gid]["last_update"] = time.time()
        if message.id < group_metadata[gid]["first_id"]:
            group_metadata[gid]["first_id"] = message.id

@app.on_message(filters.command(["start", "channel", "setup"]))
async def handle_cmds(client, message):
    args = message.command
    if len(args) > 1 and args[1] == PASS:
        AUTHORIZED_USERS.add(message.from_user.id)
        await message.reply_text("✅ Authorized! Pure Sequence + Smart Bypass active.")
        return
    if message.from_user.id not in AUTHORIZED_USERS:
        await message.reply_text("👋 Send `/start gemstock123`.")
        return
    if message.text.startswith("/start"):
        await message.reply_text("👋 GS Bot Online. Order is safe.")
    elif message.text.startswith("/channel"):
        try:
            chat = await app.get_chat(TARGET_CHANNEL_ID)
            await message.reply_text(f"✅ Target: {chat.title}")
        except: await message.reply_text("❌ Connection Error.")

if __name__ == "__main__":
    print("Bot started...")
    loop = asyncio.get_event_loop()
    loop.create_task(sequencer_worker())
    loop.create_task(publisher_worker())
    app.run()
