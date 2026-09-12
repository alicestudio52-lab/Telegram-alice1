import os
import json
import asyncio

from aiohttp import web

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.error import Forbidden

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)


# ============================================================
# הגדרות מערכת
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")

DATA_FILE = "data.json"

# Render מספק את כתובת השירות באופן אוטומטי.
# אם לא קיימת, אפשר להגדיר WEBHOOK_URL ידנית ב-Render.
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

WEBHOOK_PATH = "/telegram"


# ============================================================
# הודעות
#
# בעתיד, אם תרצה לשנות טקסטים,
# תצטרך לערוך רק את החלק הזה.
#
# אפשר להשתמש ב:
# {link}  = הקישור האישי
# {count} = מספר האנשים שהתחילו דרך הקישור שלך
# ============================================================

WELCOME_MESSAGE = """
👋 היי, ברוך הבא למקום הפרטי של Alice ❤️

כאן Alice משתפת תוכן אישי ואקסקלוסיבי שלא עולה במקומות אחרים.

🔒 התוכן מיועד לחברי הקבוצה בלבד.

כדי לקבל גישה לתוכן המלא, צריך להזמין 2 אנשים חדשים דרך הקישור האישי שלך.

🔗 הקישור האישי שלך:
{link}

📊 ההתקדמות שלך: {count}/2

אחרי ש-2 אנשים יתחילו צ'אט עם הבוט דרך הקישור שלך, תקבל גישה לתוכן האקסקלוסיבי של Alice. ✨
"""


PROGRESS_MESSAGE = """
🔥 מישהו התחיל צ'אט עם הבוט דרך הקישור שלך!

ההזמנה נקלטה בהצלחה ❤️

📊 ההתקדמות שלך: {count}/2

נשאר לך עוד קצת כדי לקבל גישה לתוכן האקסקלוסיבי של Alice...
"""


SUCCESS_MESSAGE = """
🎉 הצלחת!

השלמת את המשימה וקיבלת גישה לתוכן האקסקלוסיבי של Alice ❤️

🔓 הכניסה שלך לקבוצה:

{link}

תהנה מהתוכן 😉
"""


HOW_IT_WORKS_MESSAGE = """
ℹ️ איך זה עובד?

Alice משתפת כאן תוכן אישי ואקסקלוסיבי שמיועד לחברי הקבוצה בלבד. ❤️

כדי לקבל גישה:

1️⃣ שתף את הקישור האישי שלך עם 2 אנשים חדשים.

2️⃣ כל אדם שייכנס דרך הקישור שלך וילחץ Start ייחשב כהזמנה אחת.

3️⃣ ברגע שמגיעים ל־2/2, תקבל קישור חד־פעמי לכניסה לקבוצה.

🔒 הקישור האישי שלך מוביל לבוט ולא לקבוצה.

בהצלחה ❤️
"""


# ============================================================
# כפתורי הבוט
# ============================================================

def get_main_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(
                "🔗 הקישור שלי",
                callback_data="my_link"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 ההתקדמות שלי",
                callback_data="my_progress"
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ איך זה עובד?",
                callback_data="how_it_works"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# ניהול נתונים
# ============================================================

def empty_data():
    return {
        "users": {}
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
# יצירת קישור אישי לבוט
# ============================================================

async def get_personal_link(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: str
):
    bot_info = await context.bot.get_me()

    bot_username = bot_info.username

    if not bot_username:
        raise RuntimeError(
            "Bot username could not be detected"
        )

    return (
        f"https://t.me/{bot_username}"
        f"?start=ref_{user_id}"
    )


# ============================================================
# יצירת קישור גישה חד-פעמי לקבוצה
# ============================================================

async def create_access_link(
    context: ContextTypes.DEFAULT_TYPE
):
    access_link = await context.bot.create_chat_invite_link(
        chat_id=CHANNEL_ID,
        member_limit=1
    )

    return access_link.invite_link


# ============================================================
# יצירת משתמש
# ============================================================

def create_user():
    return {
        "invited": [],
        "completed": False,
        "referred_by": None
    }


# ============================================================
# עיבוד Referral
# ============================================================

async def process_referral(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: dict,
    new_user_id: str
):
    if not context.args:
        return

    referral_code = context.args[0]

    if not referral_code.startswith("ref_"):
        return

    inviter_id = referral_code[4:]

    if not inviter_id.isdigit():
        return

    inviter_id = str(inviter_id)

    # משתמש לא יכול להזמין את עצמו
    if inviter_id == new_user_id:
        return

    # המזמין חייב להיות משתמש קיים
    if inviter_id not in data["users"]:
        return

    new_user_data = data["users"][new_user_id]

    # משתמש שכבר הגיע בעבר לא יכול להיספר שוב
    if new_user_data.get("referred_by") is not None:
        return

    inviter_data = data["users"][inviter_id]

    # אם המזמין כבר השלים - לא מוסיפים עוד הזמנות
    if inviter_data.get("completed", False):
        return

    invited_users = inviter_data.setdefault(
        "invited",
        []
    )

    # אותו משתמש לא יכול להיספר פעמיים
    if new_user_id in invited_users:
        return

    # ========================================================
    # ההזמנה התקבלה
    # ========================================================

    invited_users.append(new_user_id)

    new_user_data["referred_by"] = inviter_id

    count = len(invited_users)

    # ========================================================
    # הגיע ל-2/2
    # ========================================================

    if count >= 2:

        inviter_data["completed"] = True

        access_link = await create_access_link(
            context
        )

        try:
            await context.bot.send_message(
                chat_id=int(inviter_id),
                text=SUCCESS_MESSAGE.format(
                    link=access_link
                ),
                reply_markup=get_main_keyboard()
            )

        except Forbidden:
            print(
                f"User {inviter_id} blocked the bot. "
                f"Could not send success message."
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
                ),
                reply_markup=get_main_keyboard()
            )

        except Forbidden:
            print(
                f"User {inviter_id} blocked the bot. "
                f"Could not send progress message."
            )

        except Exception as error:
            print(
                "Could not send progress message:",
                error
            )


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
            "הבוט עדיין לא מחובר לקבוצה. נסה שוב מאוחר יותר."
        )
        return

    user_id = str(
        update.effective_user.id
    )

    data = load_data()

    # ========================================================
    # האם המשתמש חדש?
    # ========================================================

    is_new_user = user_id not in data["users"]

    if is_new_user:
        data["users"][user_id] = create_user()

    user_data = data["users"][user_id]

    # ========================================================
    # אם משתמש חדש - מעבדים Referral
    # ========================================================

    if is_new_user:
        await process_referral(
            update,
            context,
            data,
            user_id
        )

    # שומרים נתונים
    save_data(data)

    # ========================================================
    # אם המשתמש כבר השלים
    # ========================================================

    if user_data.get("completed", False):

        access_link = await create_access_link(
            context
        )

        try:
            await update.message.reply_text(
                "כבר השלמת את המשימה 🎉\n\n"
                "הנה קישור כניסה חדש לקבוצה:\n"
                f"{access_link}",
                reply_markup=get_main_keyboard()
            )

        except Forbidden:
            print(
                f"User {user_id} blocked the bot."
            )

        return

    # ========================================================
    # המשתמש עדיין לא השלים
    # ========================================================

    personal_link = await get_personal_link(
        context,
        user_id
    )

    count = len(
        user_data.get("invited", [])
    )

    try:
        await update.message.reply_text(
            WELCOME_MESSAGE.format(
                link=personal_link,
                count=count
            ),
            reply_markup=get_main_keyboard()
        )

    except Forbidden:
        print(
            f"User {user_id} blocked the bot."
        )


# ============================================================
# טיפול בכפתורים
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    # ========================================================
    # עונים מיד ל-Telegram
    # כדי שהטעינה של הכפתור תיעלם
    # ========================================================

    try:
        await query.answer()

    except Exception as error:
        print(
            "Could not answer callback query:",
            error
        )

    user = query.from_user

    if not user:
        return

    if not CHANNEL_ID:
        try:
            await query.message.reply_text(
                "הבוט עדיין לא מחובר לקבוצה."
            )
        except Exception:
            pass

        return

    user_id = str(user.id)

    data = load_data()

    # ========================================================
    # אם המשתמש עדיין לא קיים
    # ========================================================

    if user_id not in data["users"]:
        data["users"][user_id] = create_user()

    user_data = data["users"][user_id]

    # ========================================================
    # הקישור שלי
    # ========================================================

    if query.data == "my_link":

        personal_link = await get_personal_link(
            context,
            user_id
        )

        try:
            await query.message.reply_text(
                f"🔗 הקישור האישי שלך:\n\n"
                f"{personal_link}"
            )

        except Forbidden:
            print(
                f"User {user_id} blocked the bot."
            )

    # ========================================================
    # ההתקדמות שלי
    # ========================================================

    elif query.data == "my_progress":

        count = len(
            user_data.get("invited", [])
        )

        if user_data.get("completed", False):

            try:
                await query.message.reply_text(
                    "🎉 כבר השלמת את המשימה!\n\n"
                    "התקדמות: 2/2"
                )

            except Forbidden:
                print(
                    f"User {user_id} blocked the bot."
                )

        else:

            try:
                await query.message.reply_text(
                    f"📊 ההתקדמות שלך:\n\n"
                    f"{count}/2"
                )

            except Forbidden:
                print(
                    f"User {user_id} blocked the bot."
                )

    # ========================================================
    # איך זה עובד
    # ========================================================

    elif query.data == "how_it_works":

        try:
            await query.message.reply_text(
                HOW_IT_WORKS_MESSAGE
            )

        except Forbidden:
            print(
                f"User {user_id} blocked the bot."
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
# Webhook של Telegram
# ============================================================

async def telegram_webhook(request):
    try:
        data = await request.json()

        update = Update.de_json(
            data,
            request.app["telegram_application"].bot
        )

        await request.app[
            "telegram_application"
        ].process_update(update)

        return web.Response(
            text="OK"
        )

    except Exception as error:
        print(
            "Webhook error:",
            repr(error)
        )

        return web.Response(
            text="Internal Server Error",
            status=500
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

    # ========================================================
    # יצירת Telegram Application
    # ========================================================

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # ========================================================
    # Handlers
    # ========================================================

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # ========================================================
    # אתחול Telegram Application
    # ========================================================

    await application.initialize()
    await application.start()

    # ========================================================
    # יצירת שרת HTTP
    # ========================================================

    app = web.Application()

    app["telegram_application"] = application

    app.router.add_get(
        "/",
        health
    )

    app.router.add_post(
        WEBHOOK_PATH,
        telegram_webhook
    )

    runner = web.AppRunner(app)

    await runner.setup()

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )

    await site.start()

    # ========================================================
    # קביעת כתובת ה-Webhook
    # ========================================================

    base_url = (
        WEBHOOK_URL
        or RENDER_EXTERNAL_URL
    )

    if not base_url:
        raise RuntimeError(
            "Could not determine webhook URL. "
            "Set WEBHOOK_URL in Render."
        )

    base_url = base_url.rstrip("/")

    webhook_url = (
        f"{base_url}{WEBHOOK_PATH}"
    )

    print(
        f"Setting Telegram webhook: {webhook_url}"
    )

    await application.bot.set_webhook(
        url=webhook_url,
        allowed_updates=[
            "message",
            "callback_query"
        ],
        drop_pending_updates=False
    )

    print(
        f"Bot is running on port {port}"
    )

    print(
        "Telegram webhook is active."
    )

    # ========================================================
    # משאיר את השירות פעיל
    # ========================================================

    try:
        await asyncio.Event().wait()

    finally:

        print(
            "Shutting down bot..."
        )

        try:
            await application.bot.delete_webhook()
        except Exception as error:
            print(
                "Could not delete webhook:",
                error
            )

        await application.stop()
        await application.shutdown()

        await runner.cleanup()


# ============================================================
# Start
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())