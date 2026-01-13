import logging
import qrcode
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

# ==========================================
# CONFIGURATION (EDIT THIS)
# ==========================================
TOKEN = "8502848831:AAG184UsX7tirVtPSCsAcjzPBN8_t4PQ42E"  # Get from @BotFather
BAKONG_ACCOUNT_ID = "sin_soktep@bkrt"  # Your Bakong ID (e.g., name@abaa, 012345678@aclb)
MERCHANT_NAME = "Book Shop KH"
MERCHANT_CITY = "Phnom Penh"
CURRENCY_CODE = "840"  # 840 = USD, 116 = KHR
TEST_PRICE = 0.01

# ==========================================
# STATES FOR CONVERSATION
# ==========================================
NAME, PHONE, GROUP, PAYMENT = range(4)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# KHQR GENERATOR (EMVCo Standard)
# ==========================================
def calculate_crc16(data: str) -> str:
    """Calculates CRC16 (CCITT-FALSE) for KHQR."""
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
    """Generates a dynamic KHQR string compatible with Bakong/ABA."""
    # 1. Payload Format Indicator
    root = "000201"
    # 2. Point of Initiation (12 = Dynamic/Online)
    root += "010212"
    
    # 3. Merchant Account Information (29 for Bakong Global)
    # Sub-tag 00: GUI (bakong), Sub-tag 01: Account ID
    merchant_info = f"0006bakong01{len(account_id):02}{account_id}"
    root += f"29{len(merchant_info):02}{merchant_info}"
    
    # 4. Merchant Category Code (52) - 5942 (Book Stores)
    root += "52045942"
    
    # 5. Transaction Currency (53) - 840 (USD)
    root += f"5303{CURRENCY_CODE}"
    
    # 6. Transaction Amount (54)
    amount_str = f"{amount:.2f}"
    root += f"54{len(amount_str):02}{amount_str}"
    
    # 7. Country Code (58)
    root += "5802KH"
    
    # 8. Merchant Name (59)
    root += f"59{len(MERCHANT_NAME):02}{MERCHANT_NAME}"
    
    # 9. Merchant City (60)
    root += f"60{len(MERCHANT_CITY):02}{MERCHANT_CITY}"
    
    # 10. Timestamp (62) - Optional but good for dynamic
    # timestamp = str(int(time.time()))
    # root += f"62{len(timestamp)+4:02}05{len(timestamp):02}{timestamp}"

    # 11. CRC (63)
    root += "6304" # Placeholder for CRC
    
    # Calculate CRC
    crc = calculate_crc16(root)
    return root + crc

# ==========================================
# BOT FUNCTIONS
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation."""
    await update.message.reply_text(
        f"📚 Welcome to {MERCHANT_NAME}!\n"
        f"We are selling the 'Python Masterclass' PDF.\n"
        f"Price: ${TEST_PRICE}\n\n"
        "Please enter your **Name** to proceed:"
    )
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text
    await update.message.reply_text(
        "Got it. Now, please enter your **Phone Number** (or type /skip):"
    )
    return PHONE

async def skip_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["phone"] = "Not provided"
    await update.message.reply_text(
        "Okay, skipping phone. Please enter your **Group** (e.g., Class A, Group 1):"
    )
    return GROUP

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("Thanks. Please enter your **Group**:")
    return GROUP

async def get_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["group"] = update.message.text
    
    # Generate Data
    user_info = context.user_data
    timestamp = int(time.time())
    context.user_data["timestamp"] = timestamp
    
    # MD5 Generation (Mocking a security hash)
    # In a real bank API, this is usually: md5(merchant_id + order_id + amount + timestamp)
    raw_str = f"{user_info['name']}{TEST_PRICE}{timestamp}"
    md5_hash = hashlib.md5(raw_str.encode()).hexdigest()
    context.user_data["md5_hash"] = md5_hash
    
    # Generate KHQR String
    khqr_data = generate_khqr_string(BAKONG_ACCOUNT_ID, TEST_PRICE)
    
    # Create QR Image
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(khqr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Save to buffer
    bio = io.BytesIO()
    bio.name = 'qr.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    
    # Verification Keyboard
    keyboard = [
        [InlineKeyboardButton("✅ I have Paid", callback_data="check_status")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_photo(
        photo=bio,
        caption=(
            f"🧾 **INVOICE**\n"
            f"Name: {user_info['name']}\n"
            f"Group: {user_info['group']}\n"
            f"Amount: ${TEST_PRICE}\n\n"
            f"Scan the KHQR code above with your bank app (ABA, Acleda, etc.).\n"
            f"⏳ **Expires in 10 minutes**\n"
            f"🔐 Hash: `{md5_hash[:10]}...`"
        ),
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return PAYMENT

async def check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Simulates the Check Status API call."""
    query = update.callback_query
    await query.answer() # Close the loading state
    
    saved_time = context.user_data.get("timestamp", 0)
    current_time = int(time.time())
    
    # 1. Check Expiration (10 Minutes = 600 seconds)
    if current_time - saved_time > 600:
        await query.edit_message_caption(caption="⚠️ **Payment Expired**\nPlease request a new order.")
        return ConversationHandler.END
    
    # 2. Mock Verification Logic
    # NOTE: Since we don't have a real Bank API Key here, we cannot technically "know" 
    # if you paid. For this demo, we will assume if the user clicks, it's pending/success.
    # In production, you would do: requests.post("https://api.bank.com/check", json={...})
    
    # Simulating a "Pending" delay or Success
    await query.edit_message_caption(
        caption="🔄 **Verifying with Bank...**\nChecking MD5 Hash...",
        parse_mode="Markdown"
    )
    time.sleep(1.5) # Fake loading
    
    # SUCCESS SCENARIO
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            f"✅ **Payment Received!**\n\n"
            f"Thank you {context.user_data['name']}.\n"
            f"Here is your book: [Python Guide PDF](https://www.python.org/doc/)"
        ),
        parse_mode="Markdown"
    )
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_caption(caption="🚫 Order Cancelled.")
    else:
        await update.message.reply_text("🚫 Order Cancelled.")
    return ConversationHandler.END

def main() -> None:
    """Run the bot."""
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone),
                CommandHandler("skip", skip_phone)
            ],
            GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_group)],
            PAYMENT: [
                CallbackQueryHandler(check_payment_status, pattern="^check_status$"),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    
    # Run the bot
    print("Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
