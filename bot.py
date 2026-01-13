import logging
import qrcode
import io
import hashlib
import time
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
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

load_dotenv()

# ==========================================
# CONFIGURATION
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8502848831:AAG184UsX7tirVtPSCsAcjzPBN8_t4PQ42E")
BAKONG_TOKEN = os.getenv("BAKONG_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7ImlkIjoiM2VhMzg3OTRkMDJlNDZkYyJ9LCJpYXQiOjE3NjgyNzg0NzMsImV4cCI6MTc3NjA1NDQ3M30.gybhfjIvzzVCxbLUXHa5JPv6FaDtty1nEmZWBykfIrM")  # From https://api-bakong.nbc.gov.kh/register
BAKONG_ACCOUNT_ID = os.getenv("BANK_ACCOUNT", "sin_soktep@bkrt")  # Format: username@bank
MERCHANT_NAME = os.getenv("MERCHANT_NAME", "Book Shop KH")
MERCHANT_CITY = os.getenv("MERCHANT_CITY", "Phnom Penh")
CURRENCY_CODE = "840"  # 840 = USD, 116 = KHR
TEST_PRICE = 0.01

# Bakong API endpoints
BAKONG_API_URL = "https://api-bakong.nbc.gov.kh"
BAKONG_API_SANDBOX = "https://sit-api-bakong.nbc.gov.kh"  # For testing

# ==========================================
# STATES FOR CONVERSATION
# ==========================================
NAME, PHONE, GROUP, PAYMENT = range(4)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Storage for transactions (use database in production)
transactions = {}

# ==========================================
# KHQR GENERATOR (EMVCo Standard + Bakong Format)
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

def generate_khqr_string(account_id: str, amount: float, bill_number: str) -> str:
    """
    Generates a complete KHQR string compatible with Bakong standard.
    Format: EMVCo with Bakong merchant information
    """
    # 1. Payload Format Indicator (00) = 01
    root = "000201"
    
    # 2. Point of Initiation (01) = 12 (Dynamic/Online)
    root += "010212"
    
    # 3. Merchant Account Information (29 for Bakong)
    # Format: 29{len}0006bakong01{len}{account_id}
    merchant_info = f"0006bakong01{len(account_id):02}{account_id}"
    root += f"29{len(merchant_info):02}{merchant_info}"
    
    # 4. Merchant Category Code (52) = 5942 (Book Stores)
    root += "52045942"
    
    # 5. Transaction Currency (53) = 840 (USD) or 116 (KHR)
    root += f"5303{CURRENCY_CODE}"
    
    # 6. Transaction Amount (54)
    amount_str = f"{amount:.2f}"
    root += f"54{len(amount_str):02}{amount_str}"
    
    # 7. Country Code (58) = KH
    root += "5802KH"
    
    # 8. Merchant Name (59)
    root += f"59{len(MERCHANT_NAME):02}{MERCHANT_NAME}"
    
    # 9. Merchant City (60)
    root += f"60{len(MERCHANT_CITY):02}{MERCHANT_CITY}"
    
    # 10. Additional Data Field Template (62)
    # Sub-tag 07: Bill Number/Transaction Reference
    additional_data = f"07{len(bill_number):02}{bill_number}"
    root += f"62{len(additional_data):02}{additional_data}"
    
    # 11. CRC (63) - Always placeholder first
    root += "6304"
    
    # Calculate and append actual CRC
    crc = calculate_crc16(root)
    return root + crc

def generate_md5_hash(account_id: str, amount: float, bill_number: str, timestamp: int) -> str:
    """Generate MD5 hash for payment verification"""
    raw_str = f"{account_id}{amount}{bill_number}{timestamp}"
    return hashlib.md5(raw_str.encode()).hexdigest()

# ==========================================
# BAKONG API FUNCTIONS (REAL PAYMENT VERIFICATION)
# ==========================================

def check_payment_with_bakong(md5_hash: str) -> dict:
    """
    Check payment status using actual Bakong API.
    Requires BAKONG_TOKEN from https://api-bakong.nbc.gov.kh/register
    """
    if not BAKONG_TOKEN or BAKONG_TOKEN == "YOUR_BAKONG_TOKEN":
        logger.warning("⚠️ BAKONG_TOKEN not set. Using simulation mode.")
        return {"status": "PENDING", "message": "Using simulation (no real token)"}
    
    try:
        # Bakong API endpoint to check payment
        url = f"{BAKONG_API_URL}/v1/check_transaction_status"
        
        headers = {
            "Authorization": f"Bearer {BAKONG_TOKEN}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "md5": md5_hash
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response_data = response.json()
        
        logger.info(f"Bakong API response: {response_data}")
        
        if response_data.get("status") == "00":
            # Status 00 = Success/Paid
            return {
                "status": "PAID",
                "message": "Payment confirmed!",
                "data": response_data.get("data", {})
            }
        else:
            return {
                "status": "UNPAID",
                "message": "Payment not yet received",
                "data": response_data.get("data", {})
            }
    except Exception as e:
        logger.error(f"❌ Bakong API error: {e}")
        return {"status": "ERROR", "message": str(e)}

def simulate_payment_check(md5_hash: str, timestamp: int) -> dict:
    """Simulate payment check when Bakong API is not available"""
    current_time = int(time.time())
    elapsed = current_time - timestamp
    
    # Check expiration (10 minutes = 600 seconds)
    if elapsed > 600:
        return {"status": "EXPIRED", "message": "Payment request expired"}
    
    # Simulate: if more than 3 seconds passed, assume payment received (for testing)
    if elapsed > 3:
        return {"status": "PAID", "message": "Payment verified"}
    
    return {"status": "PENDING", "message": "Waiting for payment..."}

# ==========================================
# BOT FUNCTIONS
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation."""
    await update.message.reply_text(
        f"📚 Welcome to {MERCHANT_NAME}!\n\n"
        f"📖 Product: Python Masterclass PDF\n"
        f"💰 Price: ${TEST_PRICE} USD\n\n"
        "Let's get started! Please enter your **name**:",
        parse_mode="Markdown"
    )
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Get customer name"""
    context.user_data["name"] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes, share it", callback_data="phone_yes")],
        [InlineKeyboardButton("⏭️ Skip", callback_data="phone_skip")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Nice to meet you, {context.user_data['name']}! 👋\n\n"
        "Would you like to share your phone number? (Optional)",
        reply_markup=reply_markup
    )
    return PHONE

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle phone option"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "phone_yes":
        await query.edit_message_text("Please enter your **phone number**:", parse_mode="Markdown")
        return PHONE
    else:
        context.user_data["phone"] = "Not provided"
        await query.edit_message_text("Got it! Please enter your **group** (e.g., Class A, Group 1):", parse_mode="Markdown")
        return GROUP

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Get phone number"""
    context.user_data["phone"] = update.message.text
    await update.message.reply_text(
        "Thanks! Now, please enter your **group** (e.g., Class A, Group 1):",
        parse_mode="Markdown"
    )
    return GROUP

async def get_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Get group and generate payment QR"""
    context.user_data["group"] = update.message.text
    
    # Generate transaction data
    user_info = context.user_data
    timestamp = int(time.time())
    bill_number = f"BILL{timestamp}"
    
    context.user_data["timestamp"] = timestamp
    context.user_data["bill_number"] = bill_number
    
    # Generate MD5 hash for verification
    md5_hash = generate_md5_hash(BAKONG_ACCOUNT_ID, TEST_PRICE, bill_number, timestamp)
    context.user_data["md5_hash"] = md5_hash
    
    logger.info(f"Generated transaction: Bill={bill_number}, MD5={md5_hash}, User={user_info['name']}")
    
    # Store transaction info (for production use database)
    transactions[md5_hash] = {
        "user_id": update.effective_user.id,
        "name": user_info['name'],
        "phone": user_info.get('phone', 'N/A'),
        "group": user_info['group'],
        "amount": TEST_PRICE,
        "timestamp": timestamp,
        "expires_at": timestamp + 600,  # 10 minutes
        "status": "PENDING"
    }
    
    # Generate KHQR string
    khqr_data = generate_khqr_string(BAKONG_ACCOUNT_ID, TEST_PRICE, bill_number)
    logger.info(f"KHQR generated: {khqr_data[:50]}...")
    
    # Create QR image
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(khqr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Save to buffer
    bio = io.BytesIO()
    bio.name = 'qr.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    
    # Payment verification buttons
    keyboard = [
        [InlineKeyboardButton("✅ I have Paid", callback_data=f"check_status_{md5_hash}")],
        [InlineKeyboardButton("⏱️ Check Status Again", callback_data=f"check_status_{md5_hash}")],
        [InlineKeyboardButton("❌ Cancel Order", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_photo(
        photo=bio,
        caption=(
            f"🧾 **KHQR PAYMENT**\n\n"
            f"👤 Name: {user_info['name']}\n"
            f"📞 Phone: {user_info.get('phone', 'N/A')}\n"
            f"👥 Group: {user_info['group']}\n"
            f"💰 Amount: ${TEST_PRICE} USD\n"
            f"📋 Bill No: `{bill_number}`\n"
            f"🔐 Hash: `{md5_hash[:12]}...`\n\n"
            f"📱 **Scan with your bank app:**\n"
            f"• ABA Pay\n"
            f"• Acleda Mobile\n"
            f"• WING\n"
            f"• Any Bakong-enabled bank\n\n"
            f"⏳ **Expires in: 10 minutes**"
        ),
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return PAYMENT

async def check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Check payment status using Bakong API"""
    query = update.callback_query
    await query.answer()
    
    md5_hash = query.data.split("_")[2]
    
    # Get transaction data
    txn = transactions.get(md5_hash, {})
    saved_time = txn.get("timestamp", 0)
    current_time = int(time.time())
    expires_at = txn.get("expires_at", 0)
    
    # 1. Check Expiration
    if current_time > expires_at:
        await query.edit_message_caption(
            caption=(
                "⚠️ **PAYMENT EXPIRED**\n\n"
                "The payment request has expired (10 minutes limit).\n"
                "Please start a new order with `/start`"
            ),
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    
    # Show loading message
    await query.edit_message_caption(
        caption="🔄 **Verifying payment with bank...**\n\nPlease wait...",
        parse_mode="Markdown"
    )
    
    # 2. Check payment status with Bakong API or simulation
    if BAKONG_TOKEN and BAKONG_TOKEN != "YOUR_BAKONG_TOKEN":
        # Real API call
        result = check_payment_with_bakong(md5_hash)
    else:
        # Simulation mode (for testing without token)
        result = simulate_payment_check(md5_hash, saved_time)
    
    logger.info(f"Payment check result: {result}")
    
    # 3. Handle results
    if result["status"] == "PAID":
        # Success!
        transactions[md5_hash]["status"] = "PAID"
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                f"✅ **PAYMENT RECEIVED!**\n\n"
                f"Thank you {context.user_data['name']} 🎉\n\n"
                f"📚 Here is your book:\n"
                f"[📥 Download Python Masterclass PDF](https://www.python.org/doc/)\n\n"
                f"📋 **Order Details:**\n"
                f"• Bill No: `{context.user_data['bill_number']}`\n"
                f"• Amount: ${TEST_PRICE}\n"
                f"• Hash: `{md5_hash[:12]}...`\n\n"
                f"Thank you for your purchase! 🙏"
            ),
            parse_mode="Markdown"
        )
        
        return ConversationHandler.END
    
    elif result["status"] == "PENDING":
        # Still waiting
        await query.edit_message_caption(
            caption=(
                "⏳ **PAYMENT PENDING**\n\n"
                "We haven't received your payment yet.\n"
                "Please complete the payment and click below to check again.\n\n"
                "⏱️ Time remaining: ~"
                f"{(expires_at - current_time) // 60} minutes"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Check Again", callback_data=f"check_status_{md5_hash}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
            ])
        )
        return PAYMENT
    
    elif result["status"] == "EXPIRED":
        # Expired
        await query.edit_message_caption(
            caption=(
                "⚠️ **PAYMENT EXPIRED**\n\n"
                "Your payment request has expired.\n"
                "Please start a new order."
            ),
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    
    else:
        # Error
        await query.edit_message_caption(
            caption=(
                "❌ **ERROR CHECKING PAYMENT**\n\n"
                f"Error: {result.get('message', 'Unknown error')}\n\n"
                "Please try again or contact support."
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again", callback_data=f"check_status_{md5_hash}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
            ])
        )
        return PAYMENT

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel order"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_caption(
        caption=(
            "🚫 **ORDER CANCELLED**\n\n"
            "Your order has been cancelled.\n"
            "You can start a new order with `/start`"
        ),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

def main() -> None:
    """Run the bot"""
    if not TOKEN or TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("❌ TELEGRAM_BOT_TOKEN not set in .env")
        return
    
    logger.info("=" * 60)
    logger.info("🤖 Telegram KHQR Bookshop Bot")
    logger.info("=" * 60)
    logger.info(f"✅ Bot Token: {TOKEN[:20]}...")
    logger.info(f"✅ Bank Account: {BAKONG_ACCOUNT_ID}")
    if BAKONG_TOKEN and BAKONG_TOKEN != "YOUR_BAKONG_TOKEN":
        logger.info(f"✅ Bakong API: ENABLED")
    else:
        logger.info(f"⚠️ Bakong API: DISABLED (using simulation mode)")
    logger.info("=" * 60)
    logger.info("🚀 Bot is running...")
    logger.info("=" * 60)
    
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone),
                CallbackQueryHandler(handle_phone, pattern="^phone_")
            ],
            GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_group)],
            PAYMENT: [
                CallbackQueryHandler(check_payment_status, pattern="^check_status_"),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    
    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
