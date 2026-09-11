import os
import json
from aiohttp import web
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")

DATA_FILE = "data.json"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "invite_links": {}}

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    user_id = str(user.id)

    if user_id not in data["users"]:
        data["users"][user_id] = {
            "invited": [],
            "completed": False,
        }

    if not CHANNEL_ID:
        await update.message.reply_text(
            "הבוט עדיין לא מחובר לערוץ. נסה שוב מאוחר יותר."
        )
        save_data(data)
        return

    if data["users"][user_id]["completed"]:
        link = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
        )

        await update.message.reply_text(
            "כבר השלמת את המשימה 🎉\n\n"
            f"הנה הקישור לערוץ:\n{link.invite_link}"
        )
        return

    # Create personal referral link
    existing_link = None

    for link, inviter_id in data["invite_links"].items():
        if str(inviter_id) == user_id:
            existing_link = link
            break

    if existing_link:
        referral_link = existing_link
    else:
        invite = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            name=f"ref_{user_id}",
        )

        referral_link = invite.invite_link
        data["invite_links"][referral_link] = user_id

    invited_count = len(data["users"][user_id]["invited"])

    await update.message.reply_text(
        "ברוכים הבאים 👋\n\n"
        "כדי לקבל גישה לערוץ, צריך להזמין 2 אנשים חדשים.\n\n"
        f"הקישור האישי שלך:\n{referral_link}\n\n"
        f"הוזמנו עד עכשיו: {invited_count}/2"
    )

    save_data(data)


async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.chat_member:
        return

    chat_member = update.chat_member

    # Only our channel
    if CHANNEL_ID and str(chat_member.chat.id) != str(CHANNEL_ID):
        return

    # Only when somebody joins
    old_status = chat_member.old_chat_member.status
    new_status = chat_member.new_chat_member.status

    if new_status not in ("member", "administrator"):
        return

    if old_status in ("member", "administrator"):
        return

    new_user = chat_member.new_chat_member.user

    # Don't count bots
    if new_user.is_bot:
        return

    invite_link = chat_member.invite_link

    if not invite_link:
        return

    data = load_data()

    inviter_id = data["invite_links"].get(invite_link.invite_link)

    if not inviter_id:
        return

    inviter_id = str(inviter_id)
    new_user_id = str(new_user.id)

    # Don't count self-referrals
    if inviter_id == new_user_id:
        return

    if inviter_id not in data["users"]:
        return

    invited = data["users"][inviter_id]["invited"]

    # Don't count the same person twice
    if new_user_id in invited:
        return

    invited.append(new_user_id)

    count = len(invited)

    if count >= 2 and not data["users"][inviter_id]["completed"]:
        data["users"][inviter_id]["completed"] = True

        try:
            access_link = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
            )

            await context.bot.send_message(
                chat_id=int(inviter_id),
                text=(
                    "🎉 כל הכבוד!\n\n"
                    "הזמנת 2 אנשים חדשים.\n"
                    "הנה הקישור האישי שלך לערוץ:\n\n"
                    f"{access_link.invite_link}"
                ),
            )

        except Exception as e:
            print("Error creating access link:", e)

    else:
        try:
            await context.bot.send_message(
                chat_id=int(inviter_id),
                text=f"🔥 מישהו הצטרף דרך הקישור שלך!\n\n"
                     f"התקדמות: {count}/2",
            )
        except Exception:
            pass

    save_data(data)


async def health(request):
    return web.Response(text="Bot is running!")


async def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    application.add_handler(
        ChatMemberHandler(
            member_update,
            ChatMemberHandler.CHAT_MEMBER,
        )
    )

    await application.initialize()
    await application.start()
    await application.updater.start_polling(
        allowed_updates=["message", "chat_member"]
    )

    app = web.Application()
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 10000))

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"Bot is running on port {port}")

    await application.updater.wait()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
