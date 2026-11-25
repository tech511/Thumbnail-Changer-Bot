import asyncio
import html
import inspect
import logging
import time
import weakref
from io import BytesIO

from telegram import Bot, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database import setting_info
from logic import channel as channel_access
from utils.caption import style_caption
from utils.ui import tiny

log = logging.getLogger(__name__)

# Bot API cannot download files bigger than this
MAX_DOWNLOAD = 20 * 1024 * 1024

# Telegram thumbnail limits: JPEG, at most 200 KB, at most 320x320
MAX_THUMB_BYTES = 200 * 1024
MAX_THUMB_SIDE = 320

# Network timeouts (seconds)
THUMB_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120

# Files waiting for the user's thumbnail photo are dropped after this long
PENDING_KEY = "pending"
PENDING_TTL = 600

# ---- multi-file batches -------------------------------------------------
BATCH_WINDOW = 0.8       # s of silence that ends a group of separate files
ALBUM_WINDOW = 2.0       # same, when the last file belongs to an album
MAX_COLLECT = 10.0       # a group never waits longer than this in total
MAX_QUEUE = 100          # files collected / waiting for one user
MAX_BATCHES_PER_USER = 3 # batches of one user running or waiting
MAX_SEND_RETRIES = 4     # tries when Telegram asks us to slow down
BATCH_PAUSE = 0.4        # pause between files of a batch (flood control)
STATUS_REFRESH = 2.0     # progress message refresh interval
MAX_LISTED_FAILS = 10    # failed file names shown in the final summary
DOWNLOAD_SLOTS = 5       # documents downloaded at the same time, all users

NO_THUMB_TEXT = tiny("you have no thumbnail set yet")

# Why a document was resent without the requested thumbnail
REASON_TOO_LARGE = "too_large"
REASON_DOWNLOAD_FAILED = "download_failed"
REASON_NO_THUMB_DATA = "no_thumb_data"
REASON_THUMB_REJECTED = "thumb_rejected"

UNAPPLIED_TEXT = {
    REASON_TOO_LARGE: (
        "this file is too large for me to re-upload, so telegram could not "
        "apply your thumbnail. it was resent without the new thumbnail."
    ),
    REASON_DOWNLOAD_FAILED: (
        "i could not download this file to apply your thumbnail. "
        "it was resent without the new thumbnail."
    ),
    REASON_NO_THUMB_DATA: (
        "your saved thumbnail data is missing, so the file was resent "
        "without it. please set your thumbnail again."
    ),
    REASON_THUMB_REJECTED: (
        "telegram did not accept your thumbnail, so the file was resent "
        "without it. please set your thumbnail again."
    ),
}


class ThumbnailError(Exception):
    """A problem with the thumbnail that is safe to show to the user."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


# ==========================================
# PENDING FILES  (files waiting for a thumbnail photo)
# ==========================================

def add_pending(context: ContextTypes.DEFAULT_TYPE, items: list):
    """Remember files until the user sends a thumbnail photo.

    Returns (waiting, dropped): how many files are waiting now and how
    many did not fit into the queue limit.
    """
    now = time.time()
    entry = context.user_data.get(PENDING_KEY)
    current = entry["items"] if entry and entry["expires"] >= now else []

    room = max(0, MAX_QUEUE - len(current))
    kept = items[:room]

    context.user_data[PENDING_KEY] = {
        "items": current + kept,
        "expires": now + PENDING_TTL,
    }

    return len(current) + len(kept), len(items) - len(kept)


def pop_pending(context: ContextTypes.DEFAULT_TYPE) -> list:
    """Take all pending files (empty list when none / expired)."""
    entry = context.user_data.pop(PENDING_KEY, None)

    if not entry or entry["expires"] < time.time():
        return []

    return entry["items"]


def clear_pending(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(PENDING_KEY, None)


# ==========================================
# THUMBNAIL VALIDATION
# ==========================================

# JPEG start-of-frame markers we accept (baseline, extended, progressive)
_SOF_OK = (0xC0, 0xC1, 0xC2)
# Other start-of-frame markers (lossless, arithmetic, ...) are unsupported
_SOF_BAD = (0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)

_ERR_INVALID = "that photo could not be read. please send a different one."
_ERR_FORMAT = "only jpeg photos can be used as a thumbnail."
_ERR_SIZE = "that photo is too big to use as a thumbnail."


def inspect_jpeg(data: bytes) -> tuple[int, int]:
    """Check that `data` is a complete, supported JPEG.

    Walks the JPEG segment headers (no image library needed) and returns
    (width, height). Raises ThumbnailError for anything else.
    """
    n = len(data)

    if n < 4 or data[:2] != b"\xff\xd8":
        raise ThumbnailError(_ERR_FORMAT)

    i = 2
    size = None
    seen_scan = False

    while i < n:
        if data[i] != 0xFF:
            raise ThumbnailError(_ERR_INVALID)

        while i < n and data[i] == 0xFF:  # optional fill bytes
            i += 1

        if i >= n:
            raise ThumbnailError(_ERR_INVALID)

        marker = data[i]
        i += 1

        if marker == 0xD9:  # EOI before any image data
            break

        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # no length field
            continue

        if i + 2 > n:
            raise ThumbnailError(_ERR_INVALID)

        seg_len = int.from_bytes(data[i:i + 2], "big")

        if seg_len < 2 or i + seg_len > n:
            raise ThumbnailError(_ERR_INVALID)

        if marker in _SOF_BAD:
            raise ThumbnailError(_ERR_FORMAT)

        if marker in _SOF_OK:
            if seg_len < 8:
                raise ThumbnailError(_ERR_INVALID)

            precision = data[i + 2]
            height = int.from_bytes(data[i + 3:i + 5], "big")
            width = int.from_bytes(data[i + 5:i + 7], "big")

            if precision != 8 or not width or not height:
                raise ThumbnailError(_ERR_INVALID)

            size = (width, height)

        elif marker == 0xDA:  # start of scan: header part is over
            seen_scan = True
            break

        i += seg_len

    if size is None or not seen_scan:
        raise ThumbnailError(_ERR_INVALID)

    # A complete JPEG ends with the EOI marker (truncated files do not)
    if not data.rstrip(b"\x00").endswith(b"\xff\xd9"):
        raise ThumbnailError(_ERR_INVALID)

    return size


def _pick_size(sizes):
    """Largest photo size that fits Telegram's thumbnail limits."""
    fitting = [
        s for s in sizes
        if max(s.width, s.height) <= MAX_THUMB_SIDE
        and (s.file_size is None or s.file_size <= MAX_THUMB_BYTES)
    ]

    if not fitting:
        raise ThumbnailError(_ERR_SIZE)

    return max(fitting, key=lambda s: s.width * s.height)


async def _download_thumbnail(photo_size) -> bytes:
    tg_file = await photo_size.get_file()

    if tg_file.file_size is not None and tg_file.file_size > MAX_THUMB_BYTES:
        raise ThumbnailError(_ERR_SIZE)

    buffer = BytesIO()
    await tg_file.download_to_memory(buffer)
    return buffer.getvalue()


async def prepare_thumbnail(sizes):
    """Return (file_id of best size, validated JPEG bytes of the small size).

    Raises ThumbnailError (safe to show) when the photo cannot be used as
    a Telegram thumbnail, so callers never save or report a bad one.
    """
    small = _pick_size(sizes)

    try:
        thumb_bytes = await asyncio.wait_for(
            _download_thumbnail(small), timeout=THUMB_TIMEOUT
        )
    except asyncio.TimeoutError:
        raise ThumbnailError(
            "downloading your photo took too long. please try again."
        )
    except TelegramError:
        log.exception("Thumbnail download failed")
        raise ThumbnailError(
            "i could not download your photo. please try again."
        )

    if not thumb_bytes or len(thumb_bytes) > MAX_THUMB_BYTES:
        raise ThumbnailError(_ERR_SIZE)

    width, height = inspect_jpeg(thumb_bytes)

    if width > MAX_THUMB_SIDE or height > MAX_THUMB_SIDE:
        raise ThumbnailError(_ERR_SIZE)

    return sizes[-1].file_id, thumb_bytes


# ==========================================
# HELPERS
# ==========================================

def _caption_kwargs(item: dict, style: str) -> dict:
    styled = style_caption(item.get("caption"), style)

    if styled:
        return {"caption": styled, "parse_mode": ParseMode.HTML}

    # style "none": keep the original caption and its formatting
    return {
        "caption": item.get("caption"),
        "caption_entities": item.get("caption_entities"),
    }


async def _load_document(bot, item: dict):
    """Download a document once so it can be re-uploaded with a thumbnail.

    Returns (BytesIO, None) on success or (None, reason) when the file
    cannot be re-uploaded. Oversized files are rejected from the known
    size before any download starts.
    """
    size = item.get("file_size")

    if size is not None and size > MAX_DOWNLOAD:
        return None, REASON_TOO_LARGE

    try:
        tg_file = await asyncio.wait_for(
            bot.get_file(item["file_id"]), timeout=DOWNLOAD_TIMEOUT
        )

        if tg_file.file_size is not None and tg_file.file_size > MAX_DOWNLOAD:
            return None, REASON_TOO_LARGE

        buffer = BytesIO()
        await asyncio.wait_for(
            tg_file.download_to_memory(buffer), timeout=DOWNLOAD_TIMEOUT
        )
    except asyncio.TimeoutError:
        log.warning("Document download timed out")
        return None, REASON_DOWNLOAD_FAILED
    except TelegramError as exc:
        log.warning("Document download failed: %s", exc)
        if "too big" in str(exc).lower():
            return None, REASON_TOO_LARGE
        return None, REASON_DOWNLOAD_FAILED

    return buffer, None


async def _send_item(bot, chat_id, item: dict, cfg: dict, payload=None) -> bool:
    """Send the item. Returns True when the new thumbnail was applied.

    A document re-sent by file_id keeps its old thumbnail (Telegram
    ignores a new one), so the new thumbnail is only applied when the
    document bytes (`payload`) are re-uploaded.
    """
    caption = _caption_kwargs(item, cfg["caption_style"])

    if item["kind"] == "video":
        return await _send_video(bot, chat_id, item, cfg, caption)

    if payload is not None and cfg["thumb_bytes"]:
        payload.seek(0)
        await bot.send_document(
            chat_id=chat_id,
            document=payload,
            filename=item.get("file_name"),
            thumbnail=cfg["thumb_bytes"],
            **caption,
        )
        return True

    # file_id fallback: the file is delivered, the thumbnail is not applied
    await bot.send_document(
        chat_id=chat_id,
        document=item["file_id"],
        **caption,
    )
    return False


# Newer Bot API versions (python-telegram-bot >= 22.3) accept a video
# `cover`; older ones only know `thumbnail`. Pick what is installed.
try:
    _VIDEO_COVER_PARAM = (
        "cover" if "cover" in inspect.signature(Bot.send_video).parameters
        else "thumbnail"
    )
except (TypeError, ValueError):
    _VIDEO_COVER_PARAM = "cover"


async def _send_video(bot, chat_id, item: dict, cfg: dict, caption: dict) -> bool:
    """Send a video with the user's thumbnail as its cover.

    The cover is the validated JPEG bytes saved with the settings (never the
    reusable photo file_id). Returns True when the cover was sent. If
    Telegram rejects the thumbnail (BadRequest, i.e. nothing was sent) or no
    bytes are saved, the video is delivered without it and False is returned.
    """
    base = dict(
        chat_id=chat_id,
        video=item["file_id"],
        duration=item.get("duration"),
        width=item.get("width"),
        height=item.get("height"),
        supports_streaming=True,
        **caption,
    )

    thumb_bytes = cfg.get("thumb_bytes")

    if thumb_bytes:
        try:
            await bot.send_video(**base, **{_VIDEO_COVER_PARAM: thumb_bytes})
            return True
        except BadRequest as exc:
            # Rejected before delivery, so resending cannot duplicate it.
            log.warning("Video thumbnail upload rejected: %s", exc)
    else:
        log.warning("Saved thumbnail bytes missing; sending video without cover")

    await bot.send_video(**base)
    return False


def _wait_seconds(error: RetryAfter) -> float:
    value = error.retry_after
    return float(value.total_seconds() if hasattr(value, "total_seconds") else value)


async def _with_retry(factory):
    """Run a send; when Telegram says "slow down" wait and try again.

    Only flood-control errors are retried: the message was not sent in
    that case, so a retry can never create a duplicate.
    """
    for attempt in range(MAX_SEND_RETRIES):
        try:
            return await factory()
        except RetryAfter as exc:
            if attempt == MAX_SEND_RETRIES - 1:
                raise
            await asyncio.sleep(_wait_seconds(exc) + 1)


_download_slots = asyncio.Semaphore(DOWNLOAD_SLOTS)


# ==========================================
# BATCH PROCESSING
# ==========================================

class _Collector:
    """Files of one user that arrived close together."""

    __slots__ = ("chat_id", "items", "first_at", "timer")

    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.items = []
        self.first_at = time.monotonic()
        self.timer = None


_collectors: dict = {}                                  # user_id -> _Collector
_locks = weakref.WeakValueDictionary()                  # user_id -> Lock
_active_batches: dict = {}                              # user_id -> count
_tasks: set = set()                                     # keeps tasks alive


def _user_lock(user_id: int) -> asyncio.Lock:
    lock = _locks.get(user_id)

    if lock is None:
        lock = asyncio.Lock()
        _locks[user_id] = lock

    return lock


def _track(task: asyncio.Task):
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _file_name(item: dict) -> str:
    return item.get("name") or item["kind"]


async def _safe_send(bot, chat_id, text, **kwargs):
    try:
        return await bot.send_message(
            chat_id=chat_id, text=text, parse_mode=ParseMode.HTML, **kwargs
        )
    except TelegramError:
        log.warning("Unable to send a status message")
        return None


async def _safe_edit(message, text):
    if message is None:
        return

    try:
        await message.edit_text(text, parse_mode=ParseMode.HTML)
    except TelegramError:
        pass  # "not modified", flood limits... never stop the batch


async def _open_channel(bot, user_id: int, cfg: dict) -> dict:
    """Check the channel once per batch (permissions may have changed).

    Returns {"id", "active", "notice"}: `notice` is a message for the user
    when the channel cannot be used.
    """
    channel = {"id": cfg["channel_id"], "active": False, "notice": None}

    if not channel["id"]:
        return channel

    reason = await channel_access.check_channel_access(bot, channel["id"], user_id)

    if reason is None:
        channel["active"] = True
        return channel

    if reason in channel_access.STALE_REASONS:
        try:
            await setting_info.delete_channel(
                user_id, expected_channel_id=channel["id"]
            )
        except Exception:
            log.exception("Unable to remove outdated channel")
        channel["notice"] = (
            "your channel was removed from settings because you are no "
            "longer allowed to post there."
        )
    else:
        channel["notice"] = (
            "could not post to your channel. " + channel_access.REASON_TEXT[reason]
        )

    return channel


async def _post_item_to_channel(bot, item, cfg, channel, payload) -> bool:
    try:
        await _with_retry(
            lambda: _send_item(bot, channel["id"], item, cfg, payload)
        )
        return True
    except (Forbidden, BadRequest):
        # access is gone: stop posting the rest of this batch there
        log.warning("Channel delivery refused")
        channel["active"] = False
    except TelegramError:
        log.warning("Channel delivery failed")

    return False


async def _process_item(bot, chat_id, cfg, item, channel) -> dict:
    """Deliver one file. Never raises; reports what happened."""
    result = {"item": item, "status": "failed", "reason": None, "channel": None}
    payload = None

    try:
        if item["kind"] == "video" and not cfg["thumb_bytes"]:
            result["reason"] = REASON_NO_THUMB_DATA

        if item["kind"] == "document":
            if cfg["thumb_bytes"]:
                async with _download_slots:
                    payload, result["reason"] = await _load_document(bot, item)
            else:
                result["reason"] = REASON_NO_THUMB_DATA

        try:
            applied = await _with_retry(
                lambda: _send_item(bot, chat_id, item, cfg, payload)
            )
        except Exception:
            log.exception("Media delivery failed")
            return result  # not delivered, so nothing goes to the channel

        result["status"] = "applied" if applied else "unapplied"

        if not applied and result["reason"] is None:
            result["reason"] = REASON_THUMB_REJECTED

        if channel["active"]:
            posted = await _post_item_to_channel(bot, item, cfg, channel, payload)
            result["channel"] = "ok" if posted else "failed"

    except Exception:
        log.exception("Unexpected error while processing a file")
    finally:
        if payload is not None:
            payload.close()  # free the memory before the next file

    return result


_BATCH_REASON_TEXT = {
    REASON_TOO_LARGE: "too large to re-upload",
    REASON_DOWNLOAD_FAILED: "could not be downloaded",
    REASON_NO_THUMB_DATA: "saved thumbnail data missing",
    REASON_THUMB_REJECTED: "thumbnail not accepted by telegram",
}


def _summary_text(results: list, channel: dict) -> str:
    applied = sum(r["status"] == "applied" for r in results)
    unapplied = [r for r in results if r["status"] == "unapplied"]
    failed = [r for r in results if r["status"] == "failed"]

    lines = [
        f"✅ <b>{tiny('batch finished')}</b>\n",
        f"📦 {tiny('files')} : <code>{len(results)}</code>",
        f"✅ {tiny('thumbnail applied')} : <code>{applied}</code>",
    ]

    if unapplied:
        lines.append(
            f"⚠️ {tiny('sent without the new thumbnail')} : <code>{len(unapplied)}</code>"
        )

        reasons: dict = {}
        for r in unapplied:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1

        for reason, count in reasons.items():
            label = _BATCH_REASON_TEXT.get(reason, "not supported")
            lines.append(f"    • {tiny(label)} : <code>{count}</code>")

    if failed:
        lines.append(f"❌ {tiny('failed')} : <code>{len(failed)}</code>")

        for r in failed[:MAX_LISTED_FAILS]:
            name = html.escape(_file_name(r["item"])[:40])
            lines.append(f"    • <code>{name}</code>")

        if len(failed) > MAX_LISTED_FAILS:
            lines.append(
                f"    • {tiny('and')} <code>{len(failed) - MAX_LISTED_FAILS}</code> {tiny('more')}"
            )

    if channel["id"]:
        posted = sum(r["channel"] == "ok" for r in results)
        missed = sum(r["status"] != "failed" and r["channel"] != "ok" for r in results)
        lines.append(
            f"📢 {tiny('channel')} : <code>{posted}</code> {tiny('posted')}"
            f" · <code>{missed}</code> {tiny('failed')}"
        )

    return "\n".join(lines)


async def _process_batch(context, chat_id: int, user_id: int, items: list):
    bot = context.bot

    cfg = await setting_info.get_settings(user_id)  # one read for the batch

    if not cfg["thumb_file_id"]:
        waiting, dropped = add_pending(context, items)
        text = "📸 " + tiny("now send the photo to use as thumbnail.")

        if waiting > 1:
            text += f"\n📦 <code>{waiting}</code> " + tiny("files are waiting.")

        if dropped:
            text += f"\n⚠️ <code>{dropped}</code> " + tiny("files did not fit and were skipped.")

        await _safe_send(bot, chat_id, text)
        return

    try:
        await bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
    except TelegramError:
        pass

    channel = await _open_channel(bot, user_id, cfg)

    if channel["notice"]:
        await _safe_send(bot, chat_id, "⚠️ " + tiny(channel["notice"]))

    total = len(items)
    single = total == 1

    status = None
    if not single:
        status = await _safe_send(
            bot, chat_id, f"⏳ {tiny('processing files')} : <code>0/{total}</code>"
        )

    results = []
    last_edit = time.monotonic()

    for index, item in enumerate(items, start=1):
        result = await _process_item(bot, chat_id, cfg, item, channel)
        results.append(result)

        if single:
            if result["status"] == "failed":
                await _safe_send(
                    bot, chat_id, "❌ " + tiny("failed to send your file. please try again.")
                )
            elif result["status"] == "unapplied":
                text = UNAPPLIED_TEXT.get(
                    result["reason"], UNAPPLIED_TEXT[REASON_DOWNLOAD_FAILED]
                )
                await _safe_send(bot, chat_id, "⚠️ " + tiny(text))

            if channel["id"] and result["status"] != "failed":
                if result["channel"] != "ok":
                    await _safe_send(
                        bot,
                        chat_id,
                        "⚠️ " + tiny(
                            "could not post to your channel. "
                            "check that i am still an admin there."
                        ),
                    )
                elif result["status"] == "unapplied":
                    await _safe_send(
                        bot,
                        chat_id,
                        "⚠️ " + tiny("the channel copy was also sent without the new thumbnail."),
                    )
            continue

        now = time.monotonic()
        if now - last_edit >= STATUS_REFRESH and index < total:
            last_edit = now
            await _safe_edit(
                status, f"⏳ {tiny('processing files')} : <code>{index}/{total}</code>"
            )

        if index < total:
            await asyncio.sleep(BATCH_PAUSE)

    if not single:
        summary = _summary_text(results, channel)

        if status is not None:
            await _safe_edit(status, summary)
        else:
            await _safe_send(bot, chat_id, summary)


async def _run_batch(context, chat_id: int, user_id: int, items: list):
    """One batch at a time per user, in the order the files were sent."""
    try:
        async with _user_lock(user_id):
            try:
                await _process_batch(context, chat_id, user_id, items)
            except Exception:
                log.exception("Batch failed")
                await _safe_send(
                    context.bot,
                    chat_id,
                    "❌ " + tiny("something went wrong. please try again."),
                )
    finally:
        left = _active_batches.get(user_id, 1) - 1

        if left > 0:
            _active_batches[user_id] = left
        else:
            _active_batches.pop(user_id, None)


def _start_batch(context, chat_id: int, user_id: int, items: list):
    items = sorted(items, key=lambda i: i.get("message_id", 0))
    _active_batches[user_id] = _active_batches.get(user_id, 0) + 1
    _track(asyncio.create_task(_run_batch(context, chat_id, user_id, items)))


async def _flush_after(context, user_id: int, collector: _Collector, delay: float):
    await asyncio.sleep(delay)

    # a newer file may have replaced this timer; only the live one flushes
    if _collectors.get(user_id) is not collector:
        return

    del _collectors[user_id]
    _start_batch(context, collector.chat_id, user_id, collector.items)


async def enqueue(update: Update, context: ContextTypes.DEFAULT_TYPE, item: dict):
    """Collect a file; files that arrive close together form one batch.

    An album (shared media_group_id) is held a little longer, because its
    files can trickle in over a second or two. Separate files sent in a
    quick row are grouped by the short silence window.
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    collector = _collectors.get(user_id)

    if collector is None:
        if _active_batches.get(user_id, 0) >= MAX_BATCHES_PER_USER:
            await update.effective_message.reply_text(
                "⏳ " + tiny("i am still busy with your earlier files. please wait.")
            )
            return

        collector = _Collector(chat_id)
        _collectors[user_id] = collector

    if len(collector.items) >= MAX_QUEUE:
        await update.effective_message.reply_text(
            "⚠️ " + tiny("too many files at once. send the rest after this batch.")
        )
        return

    collector.items.append(item)

    if collector.timer is not None:
        collector.timer.cancel()

    window = ALBUM_WINDOW if item.get("group") else BATCH_WINDOW
    waited = time.monotonic() - collector.first_at
    delay = max(0.0, min(window, MAX_COLLECT - waited))

    collector.timer = asyncio.create_task(
        _flush_after(context, user_id, collector, delay)
    )
    _track(collector.timer)


# ==========================================
# COMMANDS
# ==========================================

async def show_thumb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = await setting_info.get_settings(update.effective_user.id)

    if not cfg["thumb_file_id"]:
        await update.message.reply_text(NO_THUMB_TEXT)
        return

    await update.message.reply_photo(
        photo=cfg["thumb_file_id"],
        caption=tiny("your current thumbnail"),
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cfg = await setting_info.get_settings(user_id)

    clear_pending(context)

    if not cfg["thumb_file_id"]:
        await update.message.reply_text(NO_THUMB_TEXT)
        return

    await setting_info.delete_thumbnail(user_id)
    await update.message.reply_text("🗑 " + tiny("thumbnail cleared."))


# ==========================================
# MESSAGE HANDLERS
# ==========================================

# ==========================================
# MESSAGE HANDLERS
# ==========================================

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    try:
        file_id, thumb_bytes = await prepare_thumbnail(update.message.photo)
        await setting_info.set_thumbnail(user_id, file_id, thumb_bytes)
    except ThumbnailError as exc:
        await update.message.reply_text("❌ " + tiny(exc.user_message))
        return
    except Exception:
        log.exception("Unable to save thumbnail")
        await update.message.reply_text(
            "❌ " + tiny("could not save your thumbnail. please try again.")
        )
        return

    pending = pop_pending(context)

    if pending:
        # every file that was waiting for this photo is processed as one batch
        _start_batch(context, chat_id, user_id, pending)
    elif user_id in _collectors:
        await update.message.reply_text(
            "✅ " + tiny("thumbnail saved. applying it to your files...")
        )
    else:
        await update.message.reply_text(
            "✅ " + tiny("thumbnail saved. now send a video or file.")
        )


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if msg.video:
        item = {
            "kind": "video",
            "name": msg.video.file_name,
            "file_id": msg.video.file_id,
            "caption": msg.caption,
            "caption_entities": msg.caption_entities,
            "duration": msg.video.duration,
            "width": msg.video.width,
            "height": msg.video.height,
        }

    elif msg.document:
        item = {
            "kind": "document",
            "name": msg.document.file_name,
            "file_id": msg.document.file_id,
            "file_name": msg.document.file_name,
            "file_size": msg.document.file_size,
            "caption": msg.caption,
            "caption_entities": msg.caption_entities,
        }

    else:
        return

    item["message_id"] = msg.message_id
    item["group"] = msg.media_group_id

    await enqueue(update, context, item)


def register_thumbnail_handlers(app: Application):
    private = filters.ChatType.PRIVATE

    app.add_handler(CommandHandler("thumb", show_thumb, filters=private))
    app.add_handler(CommandHandler("clear", clear, filters=private))
    app.add_handler(MessageHandler(private & filters.PHOTO, on_photo))
    app.add_handler(
        MessageHandler(private & (filters.VIDEO | filters.Document.ALL), on_media)
    )
