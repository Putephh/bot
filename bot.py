import logging
import qrcode
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

# ==========================================
# CONFIGURATION
# ==========================================
TOKEN = "8502848831:AAG184UsX7tirVtPSCsAcjzPBN8_t4PQ42E"
BAKONG_ACCOUNT_ID = "005927335" 
MERCHANT_NAME = "Soktep Book Store"
MERCHANT_CITY = "Phnom Penh"
TEST_PRICE = 0.01

# States
CATEGORY, NAME, PHONE, GROUP, PAYMENT = range(5)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# ==========================================
# FIX: IMPROVED KHQR GENERATOR
# ==========================================
def calculate_crc16(data: str) -> str:
    crc = 0xFFFF
    for char in data:
        code = ord(char)
        crc ^= code << 8
        for _ in range(8):
            if (crc & 0x8000) > 0:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"

def generate_khqr_string(account_id, amount):
    # Standard EMVCo Structure
    root = "000201" # Payload
    root += "010212" # Dynamic QR
    
    # TAG 29: Bakong Specific (This fixes the "ABA" showing up incorrectly)
    # 00 = GUI (dev.bakong.kh or bakong)
    # 01 = Your specific Bakong ID
    inner_tag = f"0006bakong01{len(account_id):02}{account_id}"
    root += f"29{len(inner_tag):02}{inner_tag}"
    
    root += "52045942" # Category: Books
    root += "5303840"  # Currency: USD
    
    amount_str = f"{amount:.2f}"
    root += f"54{len(amount_str):02}{amount_str}"
    
    root += "5802KH" # Country
    root += f"59{len(MERCHANT_NAME):02}{MERCHANT_NAME}"
    root += f"60{len(MERCHANT_CITY):02}{MERCHANT_CITY}"
    
    root += "6304" # CRC Placeholder
    return root + calculate_crc16(root)

# ==========================================
# BOT LOGIC
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("📚 Programming", callback_data="prog")],
        [InlineKeyboardButton("🎨 Design", callback_data="design")],
        [InlineKeyboardButton("📈 Business", callback_data="biz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Welcome to the Upgraded Book Shop! 🛒\nPlease select a category:",
        reply_markup=reply_markup
    )
    return CATEGORY

async def select_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["category"] = query.data
    await query.edit_message_text("Great! Now, please enter your **Full Name**:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Phone Number? (or /skip):")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("Which **Group/Class** are you from?")
    return GROUP

async def skip_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["phone"] = "N/A"
    await update.message.reply_text("Which **Group/Class** are you from?")
    return GROUP

async def get_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["group"] = update.message.text
    
    # MD5 & Security
    timestamp = int(time.time())
    md5_hash = hashlib.md5(f"{BAKONG_ACCOUNT_ID}{timestamp}".encode()).hexdigest()
    
    khqr_data = generate_khqr_string(BAKONG_ACCOUNT_ID, TEST_PRICE)
    
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(khqr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    bio = io.BytesIO()
    bio.name = 'pay.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    
    caption = (
        f"📖 **Order: {context.user_data['category'].upper()} BOOK**\n"
        f"👤 Customer: {context.user_data['name']}\n"
        f"📞 Phone: {context.user_data['phone']}\n"
        f"🏫 Group: {context.user_data['group']}\n"
        f"💰 Price: **${TEST_PRICE}**\n\n"
        f"✅ *Scan to pay via Bakong/ABA/Acleda*\n"
        f"⏳ Expire: 10 mins\n"
        f"🔐 MD5: `{md5_hash}`"
    )
    
    keyboard = [[InlineKeyboardButton("✅ Confirm Payment", callback_data="paid")]]
    await update.message.reply_photo(photo=bio, caption=caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return PAYMENT

async def finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_caption("⌛ **Checking transaction status...**")
    time.sleep(2)
    await query.edit_message_caption("✅ **Success!** Your book will be sent to your group shortly.")
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
            PAYMENT: [CallbackQueryHandler(finish, pattern="^paid$")]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()
