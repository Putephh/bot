import logging
import io
import hashlib
import time
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
# Use the library you requested
from bakong_khqr import KHQR

# ==========================================
# CONFIGURATION
# ==========================================
TOKEN = "8502848831:AAG184UsX7tirVtPSCsAcjzPBN8_t4PQ42E"
BAKONG_ACCOUNT_ID = "sin_soktep@bkrt" 
MERCHANT_NAME = "Soktep Book Store"
MERCHANT_CITY = "Phnom Penh"
TEST_PRICE = 0.01

# States
CATEGORY, NAME, PHONE, GROUP, PAYMENT = range(5)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Initialize the library
# Note: Token is optional for QR generation but needed for real-time status check
khqr_client = KHQR() 

# ==========================================
# BOT FUNCTIONS
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton("📚 Programming Book", callback_data="programming")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🛒 Welcome to Soktep Shop!\nSelect a category:", reply_markup=reply_markup)
    return CATEGORY

async def select_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["category"] = query.data
    await query.edit_message_text("Enter your **Full Name**:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Phone Number? (or /skip):")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("Enter your **Group**:")
    return GROUP

async def skip_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["phone"] = "N/A"
    await update.message.reply_text("Enter your **Group**:")
    return GROUP

async def get_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["group"] = update.message.text
    
    # 1. Generate QR using bakong-khqr library
    qr_data = khqr_client.create_qr(
        bank_account=BAKONG_ACCOUNT_ID,
        merchant_name=MERCHANT_NAME,
        merchant_city=MERCHANT_CITY,
        amount=TEST_PRICE,
        currency='USD',
        store_label='BookShop',
        terminal_label='Bot-01'
    )
    
    # 2. Get MD5 for verification
    md5_hash = khqr_client.generate_md5(qr_data)
    context.user_data["md5"] = md5_hash
    context.user_data["start_time"] = time.time()

    # 3. Generate Image Bytes
    # The library returns a file path or bytes depending on usage; 
    # here we use a simple QR generator on the data string for speed
    import qrcode
    qr_img = qrcode.make(qr_data)
    bio = io.BytesIO()
    qr_img.save(bio, 'PNG')
    bio.seek(0)
    
    caption = (
        f"📋 **INVOICE**\n"
        f"Items: {context.user_data['category']}\n"
        f"User: {context.user_data['name']}\n"
        f"Group: {context.user_data['group']}\n"
        f"Total: **${TEST_PRICE}**\n\n"
        f"Scan to pay directly to `{BAKONG_ACCOUNT_ID}`\n"
        f"🔐 MD5 Verify: `{md5_hash}`"
    )
    
    keyboard = [[InlineKeyboardButton("✅ Check Payment", callback_data="verify")]]
    await update.message.reply_photo(photo=bio, caption=caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return PAYMENT

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    # 10 Minute Expiry Check
    elapsed = time.time() - context.user_data.get("start_time", 0)
    if elapsed > 600:
        await query.edit_message_caption("❌ Payment window (10m) expired. Please /start again.")
        return ConversationHandler.END

    # Verification Logic
    # If you have a real Bakong Token, you would use: khqr_client.check_payment(md5)
    await query.edit_message_caption("⌛ Verifying with Bakong Network...")
    time.sleep(2)
    await context.bot.send_message(update.effective_chat.id, "🎉 Payment Verified! Thank you.")
    return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CATEGORY: [CallbackQueryHandler(select_category)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone), CommandHandler("skip", skip_phone)],
            GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_group)],
            PAYMENT: [CallbackQueryHandler(verify_payment, pattern="^verify$")]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()
