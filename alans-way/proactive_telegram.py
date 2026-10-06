"""Approve / Snooze 1d / Dismiss buttons for proposed watches.

A tap by the bound human is human approval, so the callback verifies the user
and chat against the bound direct route before it acts. Everything degrades to
the ``/watch approve|snooze|dismiss`` commands when this Hermes has no
``register_telegram_handler`` or the Telegram client is not connected yet.
"""
from .proactive_isolated import telegram_chat

PREFIX = "aw:"
ACTIONS = {"a": "approve", "s": "snooze", "d": "dismiss"}


def handle_callback(runtime, data, user_id, chat_id):
    """(popup answer, replacement message text or None). Never raises."""
    bound = telegram_chat(runtime.store.load_policy().session_key)
    if bound is None or str(user_id) != bound or str(chat_id) != bound:
        return "Not authorized", None
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[0] + ":" != PREFIX or parts[1] not in ACTIONS:
        return "That button is no longer valid", None
    action, watch_id, code = ACTIONS[parts[1]], parts[2], parts[3]
    reply = runtime.decide_watch(action, watch_id, code)
    if reply is None:
        return "That button is no longer valid", None
    runtime.ledger.log("proposal", f"{watch_id}: button", {"approve": "approved", "snooze": "snoozed",
                                                          "dismiss": "dismissed"}[action])
    return "Done", reply


async def on_button(runtime, update, context):
    query = update.callback_query
    chat = query.message.chat_id if getattr(query, "message", None) else None
    answer, text = handle_callback(runtime, query.data, query.from_user.id, chat)
    await query.answer(text=None if text else answer)
    if text:
        await query.edit_message_text(text)


def wire(runtime):
    """The factory Hermes calls with (Telegram Application, adapter) at connect time."""
    def factory(application, adapter):
        import asyncio
        from telegram.ext import CallbackQueryHandler

        async def handler(update, context):
            await on_button(runtime, update, context)

        application.add_handler(CallbackQueryHandler(handler, pattern=r"^aw:"))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = getattr(adapter, "_loop", None)
        runtime.telegram = {"application": application, "loop": loop}
    return factory


def offer(runtime, task, code):
    """Send the proposal with buttons to the bound chat; False means use the text command."""
    link = runtime.telegram
    chat = telegram_chat(runtime.store.load_policy().session_key)
    data = {key: f"{PREFIX}{key}:{task['id']}:{code}" for key in ACTIONS}
    if (not link or not link.get("loop") or chat is None or runtime.ledger.is_snoozed(task["id"])
            or any(len(value.encode()) > 64 for value in data.values())):
        return False
    try:
        import asyncio
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("Approve", callback_data=data["a"]),
                                        InlineKeyboardButton("Snooze 1d", callback_data=data["s"]),
                                        InlineKeyboardButton("Dismiss", callback_data=data["d"])]])
        text = (f"Proposed watch: {task.get('title', task['id'])}\n{task['scope'][:300]}\n"
                f"Next action: {task['next_action'][:200]}\n"
                f"Tap a button, or send /watch approve {task['id']} {code}")
        asyncio.run_coroutine_threadsafe(
            link["application"].bot.send_message(chat_id=int(chat), text=text, reply_markup=markup),
            link["loop"])
        return True
    except Exception:
        return False
