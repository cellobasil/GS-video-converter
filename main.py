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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# EXTREME SPEED: Increase workers for cloud droplet
# workers=16 helps pyrogram maintain multiple media sessions without resets
app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=16)
collector = AlbumCollector()

AUTHORIZED_USERS = set(ALLOWED_USER_IDS)
PASS = "gemstock123"
publish_queue = asyncio.Queue()
group_metadata = {}

# TURBO COMPRESSION: 2 concurrent tasks for 4-vCPU droplet. 
# Each FFmpeg will take 2 cores instead of fighting for all 4.
compression_semaphore = asyncio.Semaphore(2)

def generate_pack_id():
    now = datetime.datetime.now()
    ts = now.strftime("%Y%m%d-%H%M%S")
    rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"GS-{ts}-{rand}"

async def prepare_media_item(i, msg: Message, pack_dir):
    try:
        # 1. Gallery Bypass (0s delay)
        if msg.photo or msg.video:
             m_type = "photo" if msg.photo else "video"
             f_id = msg.photo.file_id if msg.photo else msg.video.file_id
             return {"type": "gallery", "media_type": m_type, "file_id": f_id, "caption": msg.caption or ""}

        # 2. Parallel Download
        path = None
        for attempt in range(3):
            try:
                path = await download_media_with_progress(app, msg, pack_dir)
                if path and os.path.exists(path): break
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception:
                await asyncio.sleep(0.5)

        if not path or not os.path.exists(path): return None
        
        orig_name = msg.document.file_name if msg.document else os.path.basename(path)
        is_video_doc = msg.document and "video" in (msg.document.mime_type or "")
        proc_path = os.path.join(pack_dir, f"proc_{orig_name}")
        
        if is_video_doc:
            # TURBO LOCK: 2 videos at a time
            async with compression_semaphore:
                logger.info(f"[{i+1}] Processing Video: {orig_name}")
                # We use a wrapper to ensure FFmpeg doesn't starve the event loop
                success, _ = await asyncio.get_running_loop().run_in_executor(None, compress_video, path, proc_path)
                if not success: shutil.copy2(path, proc_path)
        else:
            shutil.copy2(path, proc_path)
            
        final_path = os.path.join(pack_dir, orig_name).replace("\\", "/")
        if os.path.exists(final_path): os.remove(final_path)
        os.rename(proc_path, final_path)
        
        return {"type": "document", "path": final_path, "caption": msg.caption or ""}
    except Exception as e:
        logger.error(f"[{i+1}] Prepare crash: {e}")
        return None

async def relay_item(client, chat_id, item):
    try:
        # RELAY: Instant relay without sleep. We rely on Pyrogram's internal throttle.
        if item["type"] == "gallery":
            if item["media_type"] == "photo":
                m = await client.send_photo(chat_id, photo=item["file_id"], disable_notification=True)
                return m.id, m.photo.file_id, item["caption"], "photo"
            else:
                m = await client.send_video(chat_id, video=item["file_id"], disable_notification=True)
                return m.id, m.video.file_id, item["caption"], "video"
        
        elif item["type"] == "document":
            m = await client.send_document(chat_id, document=item["path"], force_document=True, disable_notification=True)
            return m.id, m.document.file_id, item["caption"], "document"
    except Exception as e:
        logger.error(f"Relay fail: {e}")
        return None

async def sequencer_worker():
    while True:
        await asyncio.sleep(0.5) # Fast scan
        if not collector.albums: continue
        gids = sorted(collector.albums.keys(), key=lambda g: group_metadata.get(g, {}).get("first_id", 0))
        for gid in gids:
            meta = group_metadata.get(gid)
            # SETTLE TIME: Reduced to 1.2s for faster response
            if not meta or (time.time() - meta["last_update"]) < 1.2: continue
            if gid != gids[0]: break
            
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
    logger.info("Turbo Publisher Ready.")
    while True:
        task = await publish_queue.get()
        try:
            ttype = task.get("type")
            if ttype == "text":
                await app.send_message(TARGET_CHANNEL_ID, task["msg"].text)
            elif ttype == "sticker":
                await app.send_sticker(TARGET_CHANNEL_ID, task["msg"].sticker.file_id)
            elif ttype == "media_pack":
                messages = task["messages"]
                chat_id = messages[0].chat.id
                status = await messages[0].reply_text("🏎️ Extreme Processing...")
                
                pack_dir = os.path.join(WORK_DIR, generate_pack_id())
                os.makedirs(pack_dir, exist_ok=True)
                start = datetime.datetime.now()

                # STAGE 1: Prepare (Parallel Download & Double-Throttled Compression)
                p_tasks = [prepare_media_item(i, m, pack_dir) for i, m in enumerate(messages)]
                prep_items = await asyncio.gather(*p_tasks)
                
                # STAGE 2: Relay (No Sleep)
                relay_results = []
                for item in prep_items:
                    if not item: continue
                    res = await relay_item(app, chat_id, item)
                    if res: relay_results.append(res)

                if relay_results:
                    # STAGE 3: Final Grouping
                    media_group = []
                    for r in relay_results:
                        m_id, f_id, caption, m_kind = r
                        if m_kind == "photo":
                            media_group.append(InputMediaPhoto(media=f_id, caption=caption))
                        elif m_kind == "video":
                            media_group.append(InputMediaVideo(media=f_id, caption=caption))
                        else: # document
                            media_group.append(InputMediaDocument(media=f_id, caption=caption))
                    
                    # Final send (Large groups)
                    for offset in range(0, len(media_group), 10):
                        await app.send_media_group(TARGET_CHANNEL_ID, media=media_group[offset:offset+10])
                    
                    dur = (datetime.datetime.now() - start).total_seconds()
                    await status.edit_text(f"🏁 Extreme Time: {dur:.1f}s")
                    asyncio.create_task(app.delete_messages(chat_id, [r[0] for r in relay_results]))
                else:
                    await status.edit_text("❌ Failed.")
                
                shutil.rmtree(pack_dir, ignore_errors=True)
        except Exception:
             logger.exception("Publisher Error")
        finally:
            publish_queue.task_done()
            # Cooldown reduced to minimal for cloud stability
            await asyncio.sleep(0.5)

@app.on_message(filters.private & (filters.text | filters.sticker | filters.photo | filters.video | filters.document) & ~filters.command(["start", "setup", "channel"]))
async def handle_everything(client, message):
    if (message.from_user.id if message.from_user else 0) not in AUTHORIZED_USERS: return
    gid = message.media_group_id or f"solo_{message.id}"
    collector.add_message(gid, message)
    if gid not in group_metadata:
        group_metadata[gid] = {"first_id": message.id, "last_update": time.time()}
    else:
        group_metadata[gid]["last_update"] = time.time()

@app.on_message(filters.command(["start", "channel", "setup"]))
async def handle_cmds(client, message):
    args = message.command
    if len(args) > 1 and args[1] == PASS:
        AUTHORIZED_USERS.add(message.from_user.id)
        await message.reply_text("✅ Turbo Ready!")
        return
    if (message.from_user.id if message.from_user else 0) not in AUTHORIZED_USERS:
        await message.reply_text("🔑 `/start gemstock123`")
        return
    if message.text.startswith("/start"):
        await message.reply_text("🏎️ GS EXTREME Active.")

if __name__ == "__main__":
    print("Extreme Bot starting...")
    loop = asyncio.get_event_loop()
    loop.create_task(sequencer_worker())
    loop.create_task(publisher_worker())
    app.run()
