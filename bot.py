import os
import json
import asyncio
from aiohttp import web
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
)

# ============================================================
# הגדרות מערכת
# בדרך כלל אין צורך לגעת כאן
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")

DATA_FILE = "data.json"


# ============================================================
# הודעות
#
# בעתיד, אם תרצה לשנות את הטקסטים של הבוט,
# תצטרך לערוך רק את החלק הזה.
#
# אפשר להשתמש ב:
# {link}  = הקישור האישי
# {count} = מספר האנשים שהצטרפו
# ============================================================

WELCOME_MESSAGE = """
👋 ברוכים הבאים!

כדי לקבל גישה לערוץ, צריך להזמין 2 אנשים חדשים.

הקישור האישי שלך:
{link}

התקדמות: {count}/2
"""

PROGRESS_MESSAGE = """
🔥 מישהו הצטרף דרך הקישור שלך!

התקדמות: {count}/2
"""

SUCCESS_MESSAGE = """
🎉 כל הכבוד!

הזמנת 2 אנשים חדשים.

הנה הקישור האישי שלך לערוץ:
{link}
"""


# ============================================================
# ניהול נתונים
# ============================================================

def empty_data():
    return {
        "users": {},
        "invite_links": {}
    }


def load_data():
    if not os.path.exists(DATA_FILE):
        return empty_data()

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return empty_data()

        data.setdefault("users", {})
        data.setdefault("invite_links", {})

        return data

    except (json.JSONDecodeError, OSError):
        print("Warning: Could not load data.json")
        return empty_data()


def save_data(data):
    temp_file = DATA_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp_file, DATA_FILE)


# ============================================================
# יצירת / קבלת קישור אישי
# ============================================================

async def get_personal_invite_link(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: str,
    data: dict
):
    # בודקים האם כבר קיים למשתמש קישור
    for link, inviter_id in data["invite_links"].items():
        if str(inviter_id) == user_id:
            return link

    # אם אין קישור - יוצרים קישור חדש
    invite = await context.bot.create_chat_invite_link(
        chat_id=CHANNEL_ID,
        name=f"ref_{user_id}"
    )

    personal_link = invite.invite_link

    data["invite_links"][personal_link] = user_id

    return personal_link


# ============================================================
# /start
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.effective_user or not update.message:
        return

    if not CHANNEL_ID:
        await update.message.reply_text(
            "הבוט עדיין לא מחובר לערוץ. נסה שוב מאוחר יותר."
        )
        return

    user_id = str(update.effective_user.id)

    data = load_data()

    # אם המשתמש חדש - יוצרים לו רשומה
    if user_id not in data["users"]:
        data["users"][user_id] = {
            "invited": [],
            "completed": False
        }

    user_data = data["users"][user_id]

    # ========================================================
    # המשתמש כבר השלים את המשימה
    # ========================================================

    if user_data.get("completed", False):

        access_link = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1
        )

        await update.message.reply_text(
            "כבר השלמת את המשימה 🎉\n\n"
            "הנה הקישור לערוץ:\n"
            f"{access_link.invite_link}"
        )

        save_data(data)
        return

    # ========================================================
    # המשתמש עדיין לא השלים
    # ========================================================

    personal_link = await get_personal_invite_link(
        context,
        user_id,
        data
    )

    count = len(user_data.get("invited", []))

    await update.message.reply_text(
        WELCOME_MESSAGE.format(
            link=personal_link,
            count=count
        )
    )

    save_data(data)


# ============================================================
# זיהוי הצטרפות לערוץ
# ============================================================

async def member_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    chat_member = update.chat_member

    if not chat_member:
        return

    # ========================================================
    # מוודאים שהאירוע שייך לערוץ שלנו
    # ========================================================

    if not CHANNEL_ID:
        return

    if str(chat_member.chat.id) != str(CHANNEL_ID):
        return

    old_member = chat_member.old_chat_member
    new_member = chat_member.new_chat_member

    # ========================================================
    # בודקים שהמשתמש באמת הפך לחבר
    # ========================================================

    if new_member.status not in (
        "member",
        "administrator"
    ):
        return

    # אם הוא כבר היה חבר - לא סופרים אותו שוב
    if old_member.status in (
        "member",
        "administrator"
    ):
        return

    new_user = new_member.user

    # לא סופרים בוטים
    if new_user.is_bot:
        return

    # ========================================================
    # חייב להיות קישור הזמנה
    # ========================================================

    invite_link = chat_member.invite_link

    if not invite_link:
        return

    invite_url = invite_link.invite_link

    data = load_data()

    # ========================================================
    # מזהים למי שייך הקישור
    # ========================================================

    inviter_id = data["invite_links"].get(invite_url)

    if not inviter_id:
        return

    inviter_id = str(inviter_id)
    new_user_id = str(new_user.id)

    # ========================================================
    # משתמש לא יכול להזמין את עצמו
    # ========================================================

    if inviter_id == new_user_id:
        return

    # ========================================================
    # המזמין חייב להיות רשום
    # ========================================================

    if inviter_id not in data["users"]:
        return

    inviter_data = data["users"][inviter_id]

    # ========================================================
    # אם המזמין כבר השלים - לא מוסיפים עוד אנשים
    # ========================================================

    if inviter_data.get("completed", False):
        return

    invited_users = inviter_data.setdefault(
        "invited",
        []
    )

    # ========================================================
    # אותו אדם לא יכול להיספר פעמיים
    # ========================================================

    if new_user_id in invited_users:
        return

    # ========================================================
    # מוסיפים את המשתמש החדש
    # ========================================================

    invited_users.append(new_user_id)

    count = len(invited_users)

    # ========================================================
    # הגיע ל-2
    # ========================================================

    if count >= 2:

        inviter_data["completed"] = True

        # יוצרים קישור כניסה חד-פעמי לערוץ
        access_link = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1
        )

        try:
            await context.bot.send_message(
                chat_id=int(inviter_id),
                text=SUCCESS_MESSAGE.format(
                    link=access_link.invite_link
                )
            )

        except Exception as error:
            print(
                "Could not send success message:",
                error
            )

    # ========================================================
    # עדיין לא הגיע ל-2
    # ========================================================

    else:

        try:
            await context.bot.send_message(
                chat_id=int(inviter_id),
                text=PROGRESS_MESSAGE.format(
                    count=count
                )
            )

        except Exception as error:
            print(
                "Could not send progress message:",
                error
            )

    save_data(data)


# ============================================================
# Health Check ל-Render
# ============================================================

async def health(request):
    return web.Response(
        text="Bot is running!"
    )


# ============================================================
# הפעלת הבוט
# ============================================================

async def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing"
        )

    if not CHANNEL_ID:
        raise RuntimeError(
            "CHANNEL_ID is missing"
        )

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # /start
    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # זיהוי הצטרפות לערוץ
    application.add_handler(
        ChatMemberHandler(
            member_update,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    # ========================================================
    # הפעלת Telegram
    # ========================================================

    await application.initialize()
    await application.start()

    await application.updater.start_polling(
        allowed_updates=[
            "message",
            "chat_member"
        ]
    )

    # ========================================================
    # שרת קטן עבור Render
    # ========================================================

    app = web.Application()

    app.router.add_get(
        "/",
        health
    )

    runner = web.AppRunner(app)

    await runner.setup()

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )

    await site.start()

    print(
        f"Bot is running on port {port}"
    )

    # ========================================================
    # משאיר את הבוט פעיל
    # ========================================================

    try:
        await asyncio.Event().wait()

    finally:

        await application.updater.stop()
        await application.stop()
        await application.shutdown()

        await runner.cleanup()


# ============================================================
# Start
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
