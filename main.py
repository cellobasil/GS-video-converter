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

# Droplet Optimized (4 vCPU / 8GB RAM)
# Increased workers for parallel network and processing tasks
app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=16)
collector = AlbumCollector()

AUTHORIZED_USERS = set(ALLOWED_USER_IDS)
PASS = "gemstock123"
publish_queue = asyncio.Queue()
group_metadata = {}

def generate_pack_id():
    now = datetime.datetime.now()
    ts = now.strftime("%Y%m%d-%H%M%S")
    rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"GS-{ts}-{rand}"

async def prepare_media_item(i, msg: Message, pack_dir):
    """Parallel Stage: Concurrent Download and Compression."""
    try:
        # Gallery / Visual Album Path
        if msg.photo or msg.video:
             # Identify type for final grouping
             m_type = "photo" if msg.photo else "video"
             f_id = msg.photo.file_id if msg.photo else msg.video.file_id
             return {"type": "gallery", "media_type": m_type, "file_id": f_id, "caption": msg.caption or ""}

        # Document / File Path
        path = None
        for attempt in range(5):
            try:
                path = await download_media_with_progress(app, msg, pack_dir)
                if path and os.path.exists(path): break
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception:
                await asyncio.sleep(1)

        if not path or not os.path.exists(path): return None
        
        orig_name = msg.document.file_name if msg.document else os.path.basename(path)
        # Determine if it's a video document that needs compression
        is_video_doc = msg.document and "video" in (msg.document.mime_type or "")
        proc_path = os.path.join(pack_dir, f"proc_{orig_name}")
        
        if is_video_doc:
            # Parallel Compression: FFmpeg will use available cores
            success, _ = await asyncio.get_running_loop().run_in_executor(None, compress_video, path, proc_path)
            if not success: shutil.copy2(path, proc_path)
        else:
            shutil.copy2(path, proc_path)
            
        final_path = os.path.join(pack_dir, orig_name).replace("\\", "/")
        if os.path.exists(final_path): os.remove(final_path)
        os.rename(proc_path, final_path)
        
        return {"type": "document", "path": final_path, "caption": msg.caption or ""}
    except Exception as e:
        logger.error(f"Prepare fail: {e}")
        return None

async def relay_item(client, chat_id, item, is_visual_album):
    """High-speed relay to generate stable file_ids."""
    try:
        if item["type"] == "gallery":
            if item["media_type"] == "photo":
                m = await client.send_photo(chat_id, photo=item["file_id"], disable_notification=True)
                return m.id, m.photo.file_id, item["caption"], "photo"
            else:
                m = await client.send_video(chat_id, video=item["file_id"], disable_notification=True)
                return m.id, m.video.file_id, item["caption"], "video"
        
        elif item["type"] == "document":
            # If visual album mode, we treat documents as visual if possible
            # but user said only gallery is visual, documents are documents.
            if is_visual_album:
                # Fallback to photo for documents in visual mode (unlikely but safe)
                m = await client.send_photo(chat_id, photo=item["path"], disable_notification=True)
                return m.id, m.photo.file_id, item["caption"], "photo"
            else:
                m = await client.send_document(chat_id, document=item["path"], force_document=True, disable_notification=True)
                return m.id, m.document.file_id, item["caption"], "document"
    except Exception as e:
        logger.error(f"Relay fail: {e}")
        return None

async def sequencer_worker():
    while True:
        await asyncio.sleep(1)
        if not collector.albums: continue
        gids = sorted(collector.albums.keys(), key=lambda g: group_metadata.get(g, {}).get("first_id", 0))
        for gid in gids:
            meta = group_metadata.get(gid)
            if not meta or (time.time() - meta["last_update"]) < 3.0: continue
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
                status = await messages[0].reply_text("🏎️ Turbo Processing...")
                
                is_visual = not any(m.document for m in messages)
                pack_dir = os.path.join(WORK_DIR, generate_pack_id())
                os.makedirs(pack_dir, exist_ok=True)
                start = datetime.datetime.now()

                # STAGE 1: Parallel Compute (All cores)
                p_tasks = [prepare_media_item(i, m, pack_dir) for i, m in enumerate(messages)]
                prep_items = await asyncio.gather(*p_tasks)
                
                # STAGE 2: Sequential High-Speed Relay
                results = []
                for item in prep_items:
                    if not item: continue
                    res = await relay_item(app, chat_id, item, is_visual)
                    if res: results.append(res)
                    await asyncio.sleep(0.3) 

                if results:
                    # STAGE 3: Final Publish with Mixed Type Support
                    media_grouped = []
                    for r in results:
                        caption = r[2]
                        file_id = r[1]
                        kind = r[3]
                        
                        if kind == "photo":
                            media_grouped.append(InputMediaPhoto(media=file_id, caption=caption))
                        elif kind == "video":
                            media_grouped.append(InputMediaVideo(media=file_id, caption=caption))
                        else: # document
                            media_grouped.append(InputMediaDocument(media=file_id, caption=caption))
                    
                    for offset in range(0, len(media_grouped), 10):
                        await app.send_media_group(TARGET_CHANNEL_ID, media=media_grouped[offset:offset+10])
                    
                    dur = (datetime.datetime.now() - start).total_seconds()
                    await status.edit_text(f"🏁 Turbo Pack: {dur:.1f}s")
                    asyncio.create_task(app.delete_messages(chat_id, [r[0] for r in results]))
                else:
                    await status.edit_text("❌ Turbo Failure.")
                
                shutil.rmtree(pack_dir, ignore_errors=True)
        except Exception:
             logger.exception("Publisher Error")
        finally:
            publish_queue.task_done()
            await asyncio.sleep(1)

@app.on_message(filters.private & (filters.text | filters.sticker | filters.photo | filters.video | filters.document) & ~filters.command(["start", "setup", "channel"]))
async def handle_everything(client, message):
    if message.from_user.id not in AUTHORIZED_USERS: return
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
    if message.from_user.id not in AUTHORIZED_USERS:
        await message.reply_text("🔑 `/start gemstock123`")
        return
    if message.text.startswith("/start"):
        await message.reply_text("🏎️ GS Turbo Active.")

if __name__ == "__main__":
    print("Turbo Bot active...")
    loop = asyncio.get_event_loop()
    loop.create_task(sequencer_worker())
    loop.create_task(publisher_worker())
    app.run()
