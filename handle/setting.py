
import asyncio

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import filters
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import DATABASE_URL, DATABASE_NAME, SETTING_VIDEO, SETTING_TEXT


mongo = AsyncIOMotorClient(DATABASE_URL)
collection = mongo[DATABASE_NAME]["thumbnails"]

sessions = {}


def dashboard_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Set Thumbnail", callback_data="setting_set"),
            InlineKeyboardButton("Show Thumbnail", callback_data="setting_show"),
        ],
        [
            InlineKeyboardButton("Del Thumbnail", callback_data="setting_delete"),
            InlineKeyboardButton("Close", callback_data="setting_close"),
        ],
    ])


def back_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Back to setting", callback_data="setting_home")]
    ])


def upload_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Back", callback_data="setting_cancel"),
            InlineKeyboardButton("Close", callback_data="setting_close"),
        ]
    ])


async def delete_message(message):
    try:
        await message.delete()
    except Exception:
        pass


async def show_dashboard(client, chat_id, user_id):
    record = await collection.find_one({"user_id": user_id})
    status = "✅ Set thumbnail" if record else "❌ No thumbnail set"
    caption = f"{SETTING_TEXT}\n\n📊 Status: {status}"

    await client.send_video(
        chat_id=chat_id,
        video=SETTING_VIDEO,
        caption=caption,
        reply_markup=dashboard_buttons(),
    )


async def clear_session(user_id):
    session = sessions.pop(user_id, None)

    if session:
        task = session.get("task")
        if task and task is not asyncio.current_task():
            task.cancel()


async def expire_session(client, user_id, chat_id, message_id):
    try:
        await asyncio.sleep(180)

        session = sessions.get(user_id)
        if session and session["message_id"] == message_id:
            sessions.pop(user_id, None)

            try:
                await client.delete_messages(chat_id, message_id)
            except Exception:
                pass
    except asyncio.CancelledError:
        pass


async def setting_command(client, message):
    user_id = message.from_user.id
    await clear_session(user_id)
    await show_dashboard(client, message.chat.id, user_id)


async def setting_callback(client, query):
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    message = query.message
    action = query.data

    if action == "setting_set":
        await query.answer()
        await delete_message(message)
        await clear_session(user_id)

        prompt = await client.send_message(
            chat_id,
            "🖼️ Send your thumbnail that you want to use.",
            reply_markup=upload_buttons(),
        )

        sessions[user_id] = {
            "chat_id": chat_id,
            "message_id": prompt.id,
        }

        task = asyncio.create_task(
            expire_session(client, user_id, chat_id, prompt.id)
        )
        sessions[user_id]["task"] = task

    elif action == "setting_cancel":
        await query.answer("Upload cancelled.")
        await clear_session(user_id)
        await delete_message(message)
        await show_dashboard(client, chat_id, user_id)

    elif action == "setting_show":
        await query.answer()
        await delete_message(message)

        record = await collection.find_one({"user_id": user_id})

        if record:
            await client.send_photo(
                chat_id,
                photo=record["file_id"],
                caption="🖼️ Here is your saved thumbnail.",
                reply_markup=back_button(),
            )
        else:
            await client.send_message(
                chat_id,
                "You have no thumbnail set yet.",
                reply_markup=back_button(),
            )

    elif action == "setting_delete":
        await query.answer()
        await delete_message(message)
        await collection.delete_one({"user_id": user_id})

        await client.send_message(
            chat_id,
            "🗑️ Your thumbnail was deleted.",
            reply_markup=back_button(),
        )

    elif action == "setting_home":
        await query.answer()
        await delete_message(message)
        await show_dashboard(client, chat_id, user_id)

    elif action == "setting_close":
        await query.answer("Settings closed.")
        await clear_session(user_id)
        await delete_message(message)


async def receive_thumbnail(client, message):
    user_id = message.from_user.id
    session = sessions.get(user_id)

    if not session or message.chat.id != session["chat_id"]:
        return

    file_id = None

    if message.photo:
        file_id = message.photo.file_id
    elif (
        message.document
        and (message.document.mime_type or "").startswith("image/")
    ):
        file_id = message.document.file_id

    if not file_id:
        return

    await collection.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "file_id": file_id}},
        upsert=True,
    )

    await clear_session(user_id)
    await delete_message(message)

    try:
        await client.delete_messages(
            session["chat_id"], session["message_id"]
        )
    except Exception:
        pass

    await client.send_message(
        session["chat_id"],
        "✅ Your image was saved.",
        reply_markup=back_button(),
    )


def register_settings(app):
    app.add_handler(
        MessageHandler(
            setting_command,
            filters.command("setting") & filters.private,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            setting_callback,
            filters.regex(r"^setting_(set|show|delete|close|cancel|home)$")
        )
    )

    app.add_handler(
        MessageHandler(
            receive_thumbnail,
            (filters.photo | filters.document) & filters.private,
        )
    )

