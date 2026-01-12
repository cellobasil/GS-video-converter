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
from utils.user_settings import set_user_channel, get_user_channel

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Production Mode: 16 workers, optimized for 4-vCPU droplet
app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=16)
collector = AlbumCollector()

AUTHORIZED_USERS = set(ALLOWED_USER_IDS)
PASS = "gemstock123"
publish_queue = asyncio.Queue()
group_metadata = {}

# Turbo Parallel: 2 concurrent encodings
compression_semaphore = asyncio.Semaphore(2)

def generate_pack_id():
    now = datetime.datetime.now()
    ts = now.strftime("%Y%m%d-%H%M%S")
    rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"GS-{ts}-{rand}"

async def prepare_media_item(i, msg: Message, pack_dir):
    try:
        if msg.photo or msg.video:
             m_type = "photo" if msg.photo else "video"
             f_id = msg.photo.file_id if msg.photo else msg.video.file_id
             return {"type": "gallery", "media_type": m_type, "file_id": f_id, "caption": msg.caption or ""}

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
            async with compression_semaphore:
                logger.info(f"[{i+1}] Processing: {orig_name}")
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
        await asyncio.sleep(0.5)
        if not collector.albums: continue
        gids = sorted(collector.albums.keys(), key=lambda g: group_metadata.get(g, {}).get("first_id", 0))
        for gid in gids:
            meta = group_metadata.get(gid)
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
    logger.info("Production Publisher Ready.")
    while True:
        task = await publish_queue.get()
        try:
            ttype = task.get("type")
            
            # Resolve Target Channel for this Task
            # 1. Identify User
            user_id = None
            if ttype == "media_pack":
                if task["messages"]: 
                    user_id = task["messages"][0].from_user.id
            elif "msg" in task and task["msg"].from_user:
                user_id = task["msg"].from_user.id
            
            # 2. Get Channel
            target_chat = TARGET_CHANNEL_ID
            if user_id:
                custom_target = get_user_channel(user_id)
                if custom_target:
                    target_chat = int(custom_target)

            if ttype == "text":
                await app.send_message(target_chat, task["msg"].text)
            elif ttype == "sticker":
                await app.send_sticker(target_chat, task["msg"].sticker.file_id)
            elif ttype == "media_pack":
                messages = task["messages"]
                chat_id = messages[0].chat.id
                status = await messages[0].reply_text("Processing...")
                
                pack_dir = os.path.join(WORK_DIR, generate_pack_id())
                os.makedirs(pack_dir, exist_ok=True)

                p_tasks = [prepare_media_item(i, m, pack_dir) for i, m in enumerate(messages)]
                prep_items = await asyncio.gather(*p_tasks)
                
                relay_results = []
                for item in prep_items:
                    if not item: continue
                    res = await relay_item(app, chat_id, item)
                    if res: relay_results.append(res)

                if relay_results:
                    media_group = []
                    for r in relay_results:
                        m_id, f_id, caption, m_kind = r
                        if m_kind == "photo":
                            media_group.append(InputMediaPhoto(media=f_id, caption=caption))
                        elif m_kind == "video":
                            media_group.append(InputMediaVideo(media=f_id, caption=caption))
                        else:
                            media_group.append(InputMediaDocument(media=f_id, caption=caption))
                    
                    for offset in range(0, len(media_group), 10):
                        await app.send_media_group(target_chat, media=media_group[offset:offset+10])
                    
                    try: 
                        await status.delete()
                    except: pass
                    
                    temp_ids = [r[0] for r in relay_results]
                    asyncio.create_task(app.delete_messages(chat_id, temp_ids))
                else:
                    await status.edit_text("Processing failed.")
                
                shutil.rmtree(pack_dir, ignore_errors=True)
        except Exception:
             logger.exception("Publisher Error")
        finally:
            publish_queue.task_done()
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
    # Args parsing
    args = message.command
    user_id = message.from_user.id
    
    # Check authorization first
    if len(args) > 1 and args[1] == PASS:
        AUTHORIZED_USERS.add(user_id)
        await message.reply_text("✅ Authorized!")
        # If there's a 3rd arg, treat it as a channel ID
        if len(args) > 2:
            try:
                new_target = int(args[2])
                set_user_channel(user_id, new_target)
                await message.reply_text(f"🎯 Target Channel set to: `{new_target}`")
            except ValueError:
                await message.reply_text("❌ Invalid Channel ID format.")
        return

    if user_id not in AUTHORIZED_USERS:
        return

    # Handle /start <channel_id> for already authorized users
    if message.text.startswith("/start") and len(args) > 1:
        try:
            # Check if arg is an int (channel ID)
            new_target = int(args[1])
            set_user_channel(user_id, new_target)
            await message.reply_text(f"🎯 Target Channel updated: `{new_target}`")
        except ValueError:
            # Not an ID, assume standard start
            await message.reply_text("GS Bot Online.")
        return
    
    if message.text.startswith("/start"):
        # Check current channel
        curr = get_user_channel(user_id) or TARGET_CHANNEL_ID
        await message.reply_text(f"GS Bot Online.\n🎯 Current Target: `{curr}`\n\nTo change, send: `/start <channel_id>`")

    elif message.text.startswith("/channel"):
        try:
            curr = get_user_channel(user_id) or TARGET_CHANNEL_ID
            chat = await app.get_chat(curr)
            await message.reply_text(f"✅ Target: {chat.title} (`{curr}`)")
        except: 
            curr = get_user_channel(user_id) or TARGET_CHANNEL_ID
            await message.reply_text(f"⚠️ Target is set to `{curr}`, but I can't access it (Check Admin rights).")

if __name__ == "__main__":
    print("Bot starting (Multi-User Channel Mode)...")
    loop = asyncio.get_event_loop()
    loop.create_task(sequencer_worker())
    loop.create_task(publisher_worker())
    app.run()
