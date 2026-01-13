import logging
import io
import hashlib
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from bakong_khqr import KHQR

# --- CONFIGURATION ---
TOKEN = "8502848831:AAG184UsX7tirVtPSCsAcjzPBN8_t4PQ42E"
BAKONG_ACCOUNT_ID = "sin_soktep@bkrt"
MERCHANT_NAME = "Soktep Book Store"
MERCHANT_CITY = "Phnom Penh"
TEST_PRICE = 0.01

# --- LOGGING ---
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# --- BOT STATES ---
NAME, PHONE, GROUP, PAYMENT = range(4)

# --- FUNCTIONS ---

def generate_bakong_qr(amount):
    """Generates the KHQR string and converts it to an image."""
    khqr = KHQR()
    # Create the official KHQR String
    qr_data = khqr.create_qr(
        bank_account=BAKONG_ACCOUNT_ID,
        merchant_name=MERCHANT_NAME,
        merchant_city=MERCHANT_CITY,
        amount=float(amount),
        currency='USD',
        store_label='BookShop',
        terminal_label='Bot01'
    )
    
    # Generate MD5 for verification tracking
    md5_hash = hashlib.md5(qr_data.encode()).hexdigest()
    
    # Convert String to Image
    import qrcode
    qr_img = qrcode.make(qr_data)
    bio = io.BytesIO()
    qr_img.save(bio, format='PNG')
    bio.seek(0)
    
    return bio, md5_hash

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 **Welcome to Soktep Book Shop**\n\n"
        "To purchase the 'Digital Logic' PDF ($0.01),\n"
        "Please enter your **Full Name**:"
    )
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Enter your **Phone Number** (or /skip):")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("Which **Group/Class** are you in?")
    return GROUP

async def skip_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = "N/A"
    await update.message.reply_text("Which **Group/Class** are you in?")
    return GROUP

async def get_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["group"] = update.message.text
    context.user_data["start_time"] = time.time()
    
    # Generate QR and MD5
    qr_image, md5_hash = generate_bakong_qr(TEST_PRICE)
    context.user_data["md5"] = md5_hash

    caption = (
        f"🧾 **ORDER DETAILS**\n"
        f"Name: {context.user_data['name']}\n"
        f"Group: {context.user_data['group']}\n"
        f"Amount: **${TEST_PRICE}**\n\n"
        f"🤳 *Scan the KHQR to pay via Bakong/ABA*\n"
        f"⏱️ Expires in: 10 minutes\n"
        f"🔐 MD5: `{md5_hash}`"
    )

    keyboard = [[InlineKeyboardButton("✅ I Have Paid", callback_data="verify")]]
    await update.message.reply_photo(
        photo=qr_image,
        caption=caption,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PAYMENT

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Expiry Check
    start_time = context.user_data.get("start_time", 0)
    if time.time() - start_time > 600:
        await query.edit_message_caption("❌ **Payment Expired.** Please use /start to try again.")
        return ConversationHandler.END

    # Verification Simulation
    await query.edit_message_caption("⏳ **Verifying Transaction...**")
    time.sleep(2)
    
    success_text = (
        f"✅ **Payment Successful!**\n\n"
        f"Thank you, {context.user_data['name']}.\n"
        f"Your transaction (MD5: {context.user_data['md5'][:8]}) is confirmed.\n"
        f"Admin from **Group {context.user_data['group']}** will send your book."
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=success_text)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Transaction cancelled.")
    return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone), CommandHandler("skip", skip_phone)],
            GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_group)],
            PAYMENT: [CallbackQueryHandler(verify_payment, pattern="^verify$")]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(conv_handler)
    print("Bot is live...")
    app.run_polling()

if __name__ == "__main__":
    main()
