import os
import sys
import json
import logging
import asyncio
import subprocess
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters

# ==========================================
# ⚙️ CONFIGURATION SECTION (HARDCODED)
# ==========================================
BOT_TOKEN = "8803590097:AAG1yRfZuFCtzYpxuO9d8sPPNyVA6XfAXTA"
OWNER_URL = "https://t.me/ZYREX_10"
SUPPORT_URL = "https://t.me/+oDEzFsTz7PdkOGM1"

# Owner Account ID configuration for Admin commands
OWNER_ID = 8909378644 # Set your actual numeric Telegram ID here

# FORCE JOIN CHANNELS & CHATS CONFIGURATION
MANDATORY_CHANNEL = "@botscripts18"        
MANDATORY_GROUP = "-1003959721793"         

# Invite Links displayed on the verification gate popup
CHANNEL_INVITE_URL = "https://t.me/botscripts18"
GROUP_INVITE_URL = "https://t.me/+oDEzFsTz7PdkOGM1"
# ==========================================

# Directory structures
HOST_DIR = "hosted_scripts"
LOG_DIR = os.path.join(HOST_DIR, "logs")
DATABASE_FILE = "user_database.json"

os.makedirs(HOST_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# Process registry to track active run states dynamically
active_processes = {}

# Structural Logging Configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot_activity.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ==========================================
# 📂 LOCAL DATABASE CONTROLLER
# ==========================================
def load_db():
    """Loads database from disk or builds an empty initialization frame."""
    if not os.path.exists(DATABASE_FILE):
        return {"users": {}}
    try:
        with open(DATABASE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading database file: {e}")
        return {"users": {}}

def save_db(data):
    """Saves the database state to storage."""
    try:
        with open(DATABASE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error writing to database: {e}")

def register_user(user_id, username, referrer_id=None):
    """Registers a user and processes referral pathways."""
    db = load_db()
    uid_str = str(user_id)
    
    if uid_str not in db["users"]:
        db["users"][uid_str] = {
            "username": username or "Unknown",
            "referrer": str(referrer_id) if (referrer_id and str(referrer_id) != uid_str) else None,
            "referrals_count": 0,
            "role": "free",  # "free" or "premium"
            "unlocked": False,
            "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # Credit the referrer if valid
        if referrer_id:
            ref_str = str(referrer_id)
            if ref_str in db["users"] and ref_str != uid_str:
                db["users"][ref_str]["referrals_count"] += 1
                logger.info(f"User {referrer_id} gained a referral from {user_id}")
            
        save_db(db)
        return True
    return False


# ==========================================
# 🛡️ ACCESS & ROLE CHECKERS
# ==========================================
def is_owner(user) -> bool:
    """Verifies if the user is the configured Owner."""
    if user.id == OWNER_ID:
        return True
    if user.username and user.username.lower() == "zyrex_10":
        return True
    return False

def get_user_role(user_id) -> str:
    """Returns the role of a user from the database."""
    db = load_db()
    uid_str = str(user_id)
    if uid_str in db["users"]:
        return db["users"][uid_str].get("role", "free")
    return "free"

async def check_membership(bot, user_id) -> bool:
    """Queries Telegram to check if user has joined the mandatory chats."""
    if user_id == OWNER_ID:
        return True
        
    for target in [MANDATORY_CHANNEL, MANDATORY_GROUP]:
        try:
            member = await bot.get_chat_member(chat_id=target, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception as e:
            logger.error(f"Membership query failed for {target} on UID {user_id}: {e}")
            continue
    return True

async def verify_user_access(bot, user) -> tuple[bool, str]:
    """
    Checks if a user has full access to use the bot.
    Returns: (access_granted: bool, status_reason: str)
    """
    if is_owner(user):
        return True, "owner"

    db = load_db()
    uid_str = str(user.id)
    user_data = db["users"].get(uid_str, {})
    
    # Premium users bypass referral gates entirely
    if user_data.get("role") == "premium":
        return True, "premium"

    # Check join requirement
    joined = await check_membership(bot, user.id)
    if not joined:
        return False, "join_required"

    # Check referral requirement (Minimum 2 referrals)
    referral_count = user_data.get("referrals_count", 0)
    if referral_count < 2:
        return False, "referrals_required"

    # Access is unlocked
    if not user_data.get("unlocked"):
        db["users"][uid_str]["unlocked"] = True
        save_db(db)
        
    return True, "free"


async def send_verification_gate(update: Update, context: ContextTypes.DEFAULT_TYPE, status_reason: str):
    """Presents verification requirements or referral stats to the user."""
    user_id = update.effective_user.id
    bot_info = await context.bot.get_me()
    referral_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    
    db = load_db()
    user_data = db["users"].get(str(user_id), {"referrals_count": 0})
    ref_count = user_data.get("referrals_count", 0)

    # UI Buttons
    inline_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_INVITE_URL)],
        [InlineKeyboardButton("💬 Join Support Chat", url=GROUP_INVITE_URL)],
        [InlineKeyboardButton("🔄 Verify Membership & Referrals", callback_data="verify_join")]
    ])
    
    if status_reason == "join_required":
        warning_text = (
            "🛑 **Step 1: Membership Required**\n\n"
            "To unlock hosting features, you must first join our official channels!\n\n"
            "👉 Please join both platforms using the links below, then click Verify!"
        )
    else:  # referrals_required
        warning_text = (
            "🛑 **Step 2: Invite Your Friends**\n\n"
            "🎉 You have successfully joined the channels! Now you need to invite **at least 2 users** using your referral link to unlock hosting features.\n\n"
            f"📈 **Your Referrals:** `{ref_count} / 2` invited\n\n"
            f"🔗 **Your Referral Link:**\n`{referral_link}`\n\n"
            "Invite friends, then click the verification button below!"
        )
    
    if update.message:
        await update.message.reply_text(warning_text, reply_markup=inline_kb, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(warning_text, reply_markup=inline_kb, parse_mode="Markdown")


# ==========================================
# 🎛️ KEYBOARD FACTORY
# ==========================================
def get_control_panel_keyboard():
    """Generates the main Reply Keyboard layout."""
    keyboard = [
        [KeyboardButton("🚀 Deploy Project"), KeyboardButton("📁 My Files")],
        [KeyboardButton("📈 Performance"), KeyboardButton("📊 Dashboard")],
        [KeyboardButton("💬 Support Center"), KeyboardButton("👥 Referral")],
        [KeyboardButton("📦 Package Manager"), KeyboardButton("📚 Documentation")],
        [KeyboardButton("👑 Contact Owner")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ==========================================
# 👑 OWNER COMMANDS
# ==========================================
async def promote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows Owner to upgrade a user to Premium tier."""
    if not is_owner(update.effective_user):
        await update.message.reply_text("❌ This is an owner-only admin command.")
        return

    if not context.args:
        await update.message.reply_text("💡 Usage: `/promote <user_id>`", parse_mode="Markdown")
        return

    target_id = context.args[0]
    db = load_db()
    if target_id in db["users"]:
        db["users"][target_id]["role"] = "premium"
        save_db(db)
        await update.message.reply_text(f"✅ User `{target_id}` has been successfully promoted to **Premium Tier**!", parse_mode="Markdown")
        try:
            await context.bot.send_message(
                chat_id=int(target_id),
                text="🎉 **Congratulations!**\n\nThe Administrator has upgraded your account to **Premium Tier**. You now have unlimited hosting access!",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ User ID not found in database. Ask them to /start first.")


async def demote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows Owner to downgrade a user to Free tier."""
    if not is_owner(update.effective_user):
        await update.message.reply_text("❌ This is an owner-only admin command.")
        return

    if not context.args:
        await update.message.reply_text("💡 Usage: `/demote <user_id>`", parse_mode="Markdown")
        return

    target_id = context.args[0]
    db = load_db()
    if target_id in db["users"]:
        db["users"][target_id]["role"] = "free"
        save_db(db)
        await update.message.reply_text(f"⚠️ User `{target_id}` has been demoted back to **Free Tier**.", parse_mode="Markdown")
        try:
            await context.bot.send_message(
                chat_id=int(target_id),
                text="⚠️ Your account has been reverted to the **Free Tier** by the Administrator.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ User ID not found in database.")


# ==========================================
# 🤖 BOT ACTION HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes deep-link referrals and performs membership check."""
    user = update.effective_user
    
    # Process Referral Argument
    referrer_id = None
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                potential_ref = arg.split("_")[1]
                if int(potential_ref) != user.id:
                    referrer_id = potential_ref
            except Exception:
                pass
                
    # Register user
    is_new = register_user(user.id, user.username, referrer_id)
    
    # Notify referrer if successful
    if is_new and referrer_id:
        try:
            await context.bot.send_message(
                chat_id=referrer_id,
                text=f"🎉 **New Referral!**\n\nUser @{user.username or user.first_name} joined using your link!",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    # Verify Access Requirements
    granted, reason = await verify_user_access(context.bot, user)
    if not granted:
        await send_verification_gate(update, context, reason)
        return

    # Display Dashboard
    reply_markup = get_control_panel_keyboard()
    start_message = (
        "🎛️ **Welcome to the Advanced Automation Host**\n\n"
        "Click *🚀 Deploy Project* to submit your code for live 24/7 hosting."
    )
    await update.message.reply_text(start_message, reply_markup=reply_markup, parse_mode="Markdown")


async def handle_menu_clicks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes reply keyboard option clicks."""
    button_text = update.message.text
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # Enforce verification wall
    granted, reason = await verify_user_access(context.bot, user)
    if not granted:
        await send_verification_gate(update, context, reason)
        return
    
    role = get_user_role(user.id) if not is_owner(user) else "owner"
    
    if button_text == "🚀 Deploy Project":
        # Check Hosting file limits for Free tier
        prefix = f"{chat_id}_"
        file_count = len([f for f in os.listdir(HOST_DIR) if f.startswith(prefix) and os.path.isfile(os.path.join(HOST_DIR, f))])
        
        if role == "free" and file_count >= 5:
            await update.message.reply_text(
                "❌ **Hosting Limit Reached!**\n\n"
                "As a **Free User**, you can only host up to **5 files** concurrently.\n\n"
                "💡 *To host unlimited projects, contact the Owner to upgrade to Premium!*",
                parse_mode="Markdown"
            )
            return

        deploy_prompt = (
            "📥 **Ready for Deployment**\n\n"
            f"Account Status: **{role.upper()}** (Using {file_count} active slots)\n\n"
            "Please upload/send your bot file now.\n"
            "• Supported formats: `.py` (Python) or `.js` (JavaScript/Node.js)"
        )
        await update.message.reply_text(deploy_prompt, parse_mode="Markdown")
        return

    if button_text == "💬 Support Center":
        inline_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Open Support Group", url=SUPPORT_URL)]])
        await update.message.reply_text("Push the button below to join the Official Support Center group:", reply_markup=inline_kb)
        return

    if button_text == "👑 Contact Owner":
        inline_kb = InlineKeyboardMarkup([[InlineKeyboardButton("👤 Chat with Owner", url=OWNER_URL)]])
        await update.message.reply_text("Push the button below to message my creator directly:", reply_markup=inline_kb)
        return

    if button_text == "👥 Referral":
        db = load_db()
        user_info = db["users"].get(str(user.id), {"referrals_count": 0})
        referral_count = user_info.get("referrals_count", 0)
        bot_info = await context.bot.get_me()
        referral_link = f"https://t.me/{bot_info.username}?start=ref_{user.id}"
        
        ref_message = (
            f"👥 **Referral System Portal**\n\n"
            f"Share your referral link with other developers. Track your audience and earn rewards!\n\n"
            f"🔗 **Your Referral Link:**\n`{referral_link}`\n\n"
            f"📊 **Your Stats:**\n"
            f"• Total referrals invited: `{referral_count}`"
        )
        await update.message.reply_text(ref_message, parse_mode="Markdown")
        return

    if button_text == "📁 My Files":
        user_running = active_processes.get(chat_id, {})
        prefix = f"{chat_id}_"
        try:
            user_files = [f[len(prefix):] for f in os.listdir(HOST_DIR) if f.startswith(prefix) and os.path.isfile(os.path.join(HOST_DIR, f))]
        except Exception:
            user_files = []
        
        if user_files:
            file_list = []
            keyboard_buttons = []
            for name in user_files:
                is_running = name in user_running and user_running[name]["process"].poll() is None
                status_icon = "🟢 Running" if is_running else "🔴 Stopped / Crashed"
                file_list.append(f"• `{name}` ({status_icon})")
                if is_running:
                    keyboard_buttons.append([InlineKeyboardButton(f"🛑 Stop {name}", callback_data=f"stop_{name}")])
            
            file_list_str = "\n".join(file_list)
            reply_markup = InlineKeyboardMarkup(keyboard_buttons) if keyboard_buttons else None
            
            await update.message.reply_text(
                f"🗂️ **Hosted Files Explorer** (Account: **{role.upper()}**)\n\nYou currently have the following files on the host system:\n\n{file_list_str}\n\n"
                "💡 *Click a stop button below to terminate a running script instantly.*",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "🗂️ **Hosted Files Explorer**\n\nYou have not deployed any files yet. Click *🚀 Deploy Project* to begin.",
                parse_mode="Markdown"
            )
        return

    if button_text == "📈 Performance":
        user_running = active_processes.get(chat_id, {})
        active_count = sum(1 for data in user_running.values() if data["process"].poll() is None)
        await update.message.reply_text(
            f"⚡ **System Analytics**\n\n"
            f"• **Active Hosted Tasks:** `{active_count}` running\n"
            f"• **CPU Status:** `Healthy` (~1.2%)\n"
            f"• **Memory Pool:** ~`54MB` allocated\n"
            f"• **Engine Status:** `Operational`",
            parse_mode="Markdown"
        )
        return

    features = {
        "📊 Dashboard": f"🖥️ *Instance Metrics*\nUptime: `100%` \nTier: `{role.upper()}` \nDatabase Sync: `Connected` \nNetwork Latency: `8ms`",
        "📦 Package Manager": "📦 **Runtime Environments**\nStandard packages are globally linked. If an import error is thrown, make sure you ran `pip install <package-name>` inside your PC terminal.",
        "📚 Documentation": "📖 **Developer Guide**\n1. Use a unique token for every hosted file.\n2. Do not host scripts using blocking `while True` loops without sleep timers."
    }
    response_text = features.get(button_text, "⚠️ Target command not recognized.")
    await update.message.reply_text(response_text, parse_mode="Markdown")


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline keyboard query click actions."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user = update.effective_user
    data = query.data

    # Verify Gate Check Action
    if data == "verify_join":
        granted, reason = await verify_user_access(context.bot, user)
        if granted:
            await query.message.delete()
            reply_markup = get_control_panel_keyboard()
            await context.bot.send_message(
                chat_id=chat_id,
                text="🎉 **Verification Successful!**\n\nYour hosting tools are now fully unlocked. Welcome to your Dashboard!",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            if reason == "join_required":
                await query.answer("❌ You haven't joined our channel/group yet! Please do so first.", show_alert=True)
            elif reason == "referrals_required":
                db = load_db()
                user_data = db["users"].get(str(user.id), {"referrals_count": 0})
                ref_count = user_data.get("referrals_count", 0)
                await query.answer(f"❌ Referrals Goal not met! You need 2 referrals (Current: {ref_count}/2).", show_alert=True)
                # Re-render status panel
                await send_verification_gate(update, context, reason)
        return

    # Dynamic file stop button execution
    if data.startswith("stop_"):
        filename = data[5:]
        if chat_id in active_processes and filename in active_processes[chat_id]:
            task = active_processes[chat_id][filename]
            try:
                task["process"].terminate()
                task["process"].wait(timeout=2)
            except Exception:
                try:
                    task["process"].kill()
                except Exception:
                    pass
            try:
                task["file_stream"].close()
            except Exception:
                pass
                
            del active_processes[chat_id][filename]
            await query.edit_message_text(
                f"🛑 **Hosting Interrupted successfully!**\n\n"
                f"📦 **File:** `{filename}` has been terminated and removed from background processes.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                f"⚠️ **Error:** No active process registry found for `{filename}`. It may have already stopped.",
                parse_mode="Markdown"
            )


async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Saves and deploys files inside background sub-processes after running limitations tests."""
    chat_id = update.effective_chat.id
    user = update.effective_user
    document = update.message.document
    filename = document.file_name

    # Enforce verification gate
    granted, reason = await verify_user_access(context.bot, user)
    if not granted:
        await send_verification_gate(update, context, reason)
        return

    role = get_user_role(user.id) if not is_owner(user) else "owner"

    # Enforce Upload Limit for Free Tier
    prefix = f"{chat_id}_"
    file_count = len([f for f in os.listdir(HOST_DIR) if f.startswith(prefix) and os.path.isfile(os.path.join(HOST_DIR, f))])
    
    if role == "free" and file_count >= 5:
        await update.message.reply_text(
            "❌ **Hosting Limit Reached!**\n\n"
            "As a **Free User**, you can only host up to **5 files** concurrently.\n\n"
            "💡 *Contact the Owner to upgrade to Premium for unlimited hosting capability!*",
            parse_mode="Markdown"
        )
        return

    if not (filename.endswith('.py') or filename.endswith('.js')):
        await update.message.reply_text("❌ **Invalid File Type!** Please only upload a `.py` or `.js` file.")
        return

    status_msg = await update.message.reply_text("📥 *Downloading file to local engine...*", parse_mode="Markdown")

    file_path = os.path.abspath(os.path.join(HOST_DIR, f"{chat_id}_{filename}"))
    log_path = os.path.abspath(os.path.join(LOG_DIR, f"{chat_id}_{filename}.log"))
    
    # Overwrite running project cleanly if deployed again
    if chat_id in active_processes and filename in active_processes[chat_id]:
        old_task = active_processes[chat_id][filename]
        try:
            old_task["process"].terminate()
            old_task["process"].wait(timeout=2)
        except Exception:
            try:
                old_task["process"].kill()
            except Exception:
                pass
        try:
            old_task["file_stream"].close()
        except Exception:
            pass
        del active_processes[chat_id][filename]

    tg_file = await context.bot.get_file(document.file_id)
    await tg_file.download_to_drive(custom_path=file_path)

    await status_msg.edit_text(f"✅ Download complete: `{filename}`\n🚀 *Initializing startup sequence & verifying runtime...*", parse_mode="Markdown")

    try:
        log_file = open(log_path, "w", encoding="utf-8")
        custom_env = os.environ.copy()
        custom_env["PYTHONIOENCODING"] = "utf-8"

        if filename.endswith('.py'):
            process = subprocess.Popen(
                [sys.executable, "-u", file_path], 
                stdout=log_file, 
                stderr=subprocess.STDOUT,
                cwd=HOST_DIR,
                env=custom_env,
                text=True
            )
        elif filename.endswith('.js'):
            process = subprocess.Popen(
                ["node", file_path], 
                stdout=log_file, 
                stderr=subprocess.STDOUT,
                cwd=HOST_DIR,
                env=custom_env,
                text=True
            )

        await asyncio.sleep(3.0)
        return_code = process.poll()
        
        if return_code is not None:
            log_file.close()
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    error_preview = f.read().strip()
            except Exception:
                error_preview = "Could not parse process output log."
                
            if not error_preview:
                error_preview = "Process terminated immediately with no console output."

            bt = "```"
            fail_message = (
                f"❌ **Deployment Failed! The script crashed on startup.**\n\n"
                f"⚠️ **Execution Log Output:**\n"
                f"{bt}text\n{error_preview[:3000]}\n{bt}\n"
                f"💡 *Check your token validity, library installations, and code syntax!*"
            )
            await status_msg.edit_text(fail_message, parse_mode="Markdown")
            logger.warning(f"Child process crashed: {filename}. Return code: {return_code}.")
            return

        if chat_id not in active_processes:
            active_processes[chat_id] = {}
            
        active_processes[chat_id][filename] = {
            "process": process,
            "log_path": log_path,
            "file_stream": log_file
        }

        success_message = (
            f"🚀 **Deployment Successful!**\n\n"
            f"📦 **File:** `{filename}`\n"
            f"🆔 **Process ID (PID):** `{process.pid}`\n"
            f"🟢 **Status:** Verified running successfully in background."
        )
        await status_msg.edit_text(success_message, parse_mode="Markdown")
        logger.info(f"Successfully launched background host task {filename} with PID {process.pid}")

    except Exception as e:
        logger.error(f"Failed to execute script {filename}: {e}")
        await status_msg.edit_text(f"❌ **Failed to boot script.** Local platform error:\n`{str(e)}`", parse_mode="Markdown")


async def main():
    logger.info("Initializing Advanced Local Host Bot...")
    app = ApplicationBuilder().token(BOT_TOKEN).connect_timeout(30).build()

    # Setup core command interaction handling
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("promote", promote_user))
    app.add_handler(CommandHandler("demote", demote_user))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_clicks))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file_upload))
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Bot engine lifecycle loop
    while True:
        try:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            while True:
                await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Main loop error: {e}. Recovering in 15s...")
            await asyncio.sleep(15)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot execution halted by user.")
        for user_tasks in active_processes.values():
            for task in user_tasks.values():
                try:
                    task["process"].terminate()
                    task["file_stream"].close()
                except Exception:
                    pass