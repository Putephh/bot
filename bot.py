import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from bakong_khqr import KHQR

load_dotenv()

# ============ CONFIGURATION ============
TELEGRAM_TOKEN = os.getenv("8502848831:AAG184UsX7tirVtPSCsAcjzPBN8_t4PQ42E")
BAKONG_TOKEN = os.getenv("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7ImlkIjoiM2VhMzg3OTRkMDJlNDZkYyJ9LCJpYXQiOjE3NjgyNzg0NzMsImV4cCI6MTc3NjA1NDQ3M30.gybhfjIvzzVCxbLUXHa5JPv6FaDtty1nEmZWBykfIrM")  # Get from https://api-bakong.nbc.gov.kh/register or RBK from https://bakongrelay.com

# Your Bakong account - format: username@bank
# Get from: Bakong App → Profile → Account Information
BANK_ACCOUNT = os.getenv("sin_soktep@bkrt")  # e.g., "myshop@wing"
MERCHANT_NAME = os.getenv("MERCHANT_NAME", "My Bookshop")
MERCHANT_CITY = os.getenv("MERCHANT_CITY", "Phnom Penh")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "85581599652")
STORE_LABEL = os.getenv("STORE_LABEL", "BookShop")

# Initialize KHQR with official bakong-khqr library
try:
    khqr = KHQR(BAKONG_TOKEN)
    print("✅ KHQR Initialized successfully")
except Exception as e:
    print(f"❌ KHQR Initialization error: {e}")
    khqr = None

# Transaction storage
transactions = {}

# Book catalog with USD and KHR prices
BOOKS = {
    "b1": {"title": "Python Programming", "price_usd": 0.01, "price_khr": 50000, "author": "John Doe"},
    "b2": {"title": "Web Development", "price_usd": 0.01, "price_khr": 50000, "author": "Jane Smith"},
    "b3": {"title": "Data Science", "price_usd": 0.01, "price_khr": 50000, "author": "Bob Johnson"},
}

# Conversation states
REQUESTING_NAME, REQUESTING_PHONE, REQUESTING_GROUP, REQUESTING_CURRENCY = range(4)

# ============ KHQR PAYMENT FUNCTIONS ============

def create_payment_qr(bank_account, amount, currency, bill_number):
    """
    Create real KHQR QR code using official Bakong API
    
    Parameters:
    - bank_account: Format "username@bank" (e.g., "shop@wing")
    - amount: Amount in currency (float)
    - currency: "KHR" or "USD"
    - bill_number: Unique bill/transaction reference
    """
    if not khqr:
        return None
    
    try:
        qr_string = khqr.create_qr(
            bank_account=bank_account,
            merchant_name=MERCHANT_NAME,
            merchant_city=MERCHANT_CITY,
            amount=amount,  # Amount in currency
            currency=currency,  # KHR or USD
            store_label=STORE_LABEL,
            phone_number=PHONE_NUMBER,
            bill_number=bill_number,
            terminal_label="Cashier-01",
            static=False  # Dynamic QR (expires after payment or timeout)
        )
        return qr_string
    except Exception as e:
        print(f"❌ Error creating QR: {e}")
        return None

def get_md5_hash(qr_string):
    """Generate MD5 hash from QR string for payment verification"""
    if not khqr:
        return None
    
    try:
        md5 = khqr.generate_md5(qr_string)
        return md5
    except Exception as e:
        print(f"❌ Error generating MD5: {e}")
        return None

def check_payment_status(md5_hash):
    """
    Check payment status from Bakong API
    Returns: "PAID", "UNPAID", or error
    """
    if not khqr:
        return "ERROR"
    
    try:
        status = khqr.check_payment(md5_hash)
        return status  # Returns "PAID" or "UNPAID"
    except Exception as e:
        print(f"❌ Error checking payment: {e}")
        return "ERROR"

def get_payment_details(md5_hash):
    """Get detailed payment information after successful payment"""
    if not khqr:
        return None
    
    try:
        payment_info = khqr.get_payment(md5_hash)
        return payment_info
    except Exception as e:
        print(f"❌ Error getting payment details: {e}")
        return None

def generate_qr_image(qr_string):
    """Generate QR image as PNG from QR string"""
    if not khqr:
        return None
    
    try:
        png_path = khqr.qr_image(qr_string, format='png')
        return png_path
    except Exception as e:
        print(f"❌ Error generating QR image: {e}")
        return None

# ============ BOT HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    if not khqr:
        await update.message.reply_text(
            "❌ Bot is not configured properly. Missing BAKONG_TOKEN or cannot connect to Bakong API.\n\n"
            "Solution: Use RBK Token from https://bakongrelay.com/ if you're outside Cambodia"
        )
        return
    
    user = update.effective_user
    
    keyboard = [
        [InlineKeyboardButton("📚 Browse Books", callback_data="browse")],
        [InlineKeyboardButton("💳 How to Pay", callback_data="about")],
        [InlineKeyboardButton("❓ FAQ", callback_data="faq")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Welcome to {MERCHANT_NAME}! 📖\n\n"
        f"Hi {user.first_name}! 👋\n\n"
        f"We accept KHQR payment from any bank in Cambodia.\n"
        f"Simple, fast, and secure! 🔒",
        reply_markup=reply_markup
    )

async def browse_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show book catalog"""
    query = update.callback_query
    await query.answer()
    
    keyboard = []
    for book_id, book_info in BOOKS.items():
        keyboard.append([
            InlineKeyboardButton(
                f"{book_info['title']} - ${book_info['price_usd']} / {book_info['price_khr']}៛",
                callback_data=f"select_{book_id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="back_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📚 *Available Books:*\n\n(Select a book to continue)",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def select_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Select book and choose currency"""
    query = update.callback_query
    book_id = query.data.split("_")[1]
    
    book = BOOKS[book_id]
    context.user_data["selected_book"] = book_id
    
    keyboard = [
        [InlineKeyboardButton(f"💵 USD ${book['price_usd']}", callback_data=f"currency_USD_{book_id}")],
        [InlineKeyboardButton(f"💴 KHR {book['price_khr']}៛", callback_data=f"currency_KHR_{book_id}")],
        [InlineKeyboardButton("◀️ Back", callback_data="browse")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.answer()
    await query.edit_message_text(
        f"📖 *{book['title']}*\n"
        f"Author: {book['author']}\n\n"
        f"Select payment currency:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def select_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Select currency and request name"""
    query = update.callback_query
    data_parts = query.data.split("_")
    currency = data_parts[1]
    book_id = data_parts[2]
    
    book = BOOKS[book_id]
    amount = book['price_usd'] if currency == "USD" else book['price_khr']
    
    context.user_data["currency"] = currency
    context.user_data["amount"] = amount
    context.user_data["selected_book"] = book_id
    
    await query.answer()
    await query.edit_message_text("Please enter your *name*:", parse_mode="Markdown")
    
    return REQUESTING_NAME

async def name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process name and request phone"""
    context.user_data["name"] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes, share my number", callback_data="phone_yes")],
        [InlineKeyboardButton("⏭️  Skip", callback_data="phone_skip")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Would you like to share your phone number? (Optional)",
        reply_markup=reply_markup
    )
    
    return REQUESTING_PHONE

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle phone option"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "phone_yes":
        await query.edit_message_text("Please enter your *phone number*:", parse_mode="Markdown")
        return REQUESTING_PHONE
    else:
        context.user_data["phone"] = "Not provided"
        return await request_category(update, context)

async def phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process phone and request category"""
    context.user_data["phone"] = update.message.text
    return await request_category(update, context)

async def request_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Request book category preference"""
    keyboard = [
        [InlineKeyboardButton("📕 Fiction", callback_data="cat_fiction")],
        [InlineKeyboardButton("📗 Non-Fiction", callback_data="cat_nonfiction")],
        [InlineKeyboardButton("📘 Educational", callback_data="cat_educational")],
        [InlineKeyboardButton("⏭️  Skip", callback_data="cat_skip")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text(
            "What's your preferred book category?",
            reply_markup=reply_markup
        )
    else:
        await update.callback_query.edit_message_text(
            "What's your preferred book category?",
            reply_markup=reply_markup
        )
    
    return REQUESTING_GROUP

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate KHQR payment after category selection"""
    query = update.callback_query
    category = query.data.split("_")[1] if query.data != "cat_skip" else "general"
    context.user_data["category"] = category
    
    await query.answer()
    
    # Generate unique bill number
    bill_number = f"BILL{int(datetime.now().timestamp())}"
    amount = context.user_data["amount"]
    currency = context.user_data["currency"]
    
    # Create KHQR QR code
    qr_string = create_payment_qr(BANK_ACCOUNT, amount, currency, bill_number)
    
    if not qr_string:
        await query.edit_message_text(
            "❌ *Error* generating payment QR code\n\n"
            "Troubleshooting:\n"
            "1. Check BAKONG_TOKEN is valid\n"
            "2. If outside Cambodia, use RBK Token from bakongrelay.com\n"
            "3. Check BANK_ACCOUNT format (username@bank)\n\n"
            "For help, contact support.",
            parse_mode="Markdown"
        )
        return
    
    # Get MD5 hash
    md5_hash = get_md5_hash(qr_string)
    
    if not md5_hash:
        await query.edit_message_text("❌ Error generating payment hash. Please try again.")
        return
    
    # Store transaction
    expires_at = datetime.now() + timedelta(minutes=10)
    transactions[md5_hash] = {
        "amount": amount,
        "currency": currency,
        "user_id": update.effective_user.id,
        "name": context.user_data.get("name"),
        "phone": context.user_data.get("phone"),
        "category": category,
        "bill_number": bill_number,
        "qr_string": qr_string,
        "expires_at": expires_at,
        "created_at": datetime.now(),
        "status": "UNPAID"
    }
    
    currency_symbol = "$" if currency == "USD" else "៛"
    
    # Payment details message
    message_text = (
        f"💳 *KHQR Payment*\n\n"
        f"📋 *Details:*\n"
        f"Amount: {amount}{currency_symbol}\n"
        f"Bill No: `{bill_number}`\n"
        f"MD5: `{md5_hash}`\n"
        f"Name: {context.user_data.get('name')}\n"
        f"Phone: {context.user_data.get('phone', 'Not provided')}\n"
        f"Category: {category}\n\n"
        f"⏰ *Expires in: 10 minutes*\n\n"
        f"📱 *Scan with your bank app to pay:*"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ I've Paid", callback_data=f"check_{md5_hash}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_order")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message_text, parse_mode="Markdown")
    
    # Generate and send QR image
    qr_image_path = generate_qr_image(qr_string)
    
    if qr_image_path and os.path.exists(qr_image_path):
        try:
            with open(qr_image_path, 'rb') as photo:
                await query.message.reply_photo(
                    photo=photo,
                    caption=(
                        f"🔐 Scan this QR code with your mobile banking app\n\n"
                        f"Supported banks: WING, ABA, BIDC, Acleda, etc.\n"
                        f"Amount: {amount}{currency_symbol}"
                    ),
                    reply_markup=reply_markup
                )
        except Exception as e:
            print(f"Error sending QR image: {e}")
            await query.message.reply_text(
                "QR code ready (image send failed, but you can use the QR string above)",
                reply_markup=reply_markup
            )
    else:
        await query.message.reply_text(
            f"QR String:\n`{qr_string}`",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    context.user_data["current_md5"] = md5_hash

async def check_payment_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check payment status from Bakong"""
    query = update.callback_query
    md5_hash = query.data.split("_")[1]
    
    await query.answer("Checking payment status...", show_alert=False)
    
    # Check payment status
    status = check_payment_status(md5_hash)
    
    # Get payment details if paid
    payment_details = None
    if status == "PAID":
        payment_details = get_payment_details(md5_hash)
        transactions[md5_hash]["status"] = "PAID"
    
    emoji_map = {"PAID": "✅", "UNPAID": "⏳", "ERROR": "❌"}
    emoji = emoji_map.get(status, "❓")
    
    message_text = f"{emoji} *Payment Status: {status}*\n\n"
    message_text += f"MD5: `{md5_hash}`\n"
    
    if payment_details:
        message_text += (
            f"\n💰 *Payment Info:*\n"
            f"From: {payment_details.get('fromAccountId', 'N/A')}\n"
            f"Amount: {payment_details.get('amount', 'N/A')} {payment_details.get('currency', 'KHR')}\n"
            f"Date: {datetime.fromtimestamp(payment_details.get('acknowledgedDateMs', 0) / 1000)}\n"
        )
    
    if status == "PAID":
        keyboard = [
            [InlineKeyboardButton("🏠 Back Home", callback_data="back_menu")],
            [InlineKeyboardButton("📚 Buy More", callback_data="browse")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("🔄 Check Again", callback_data=f"check_{md5_hash}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_order")]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message_text,
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def back_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to main menu"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📚 Browse Books", callback_data="browse")],
        [InlineKeyboardButton("💳 How to Pay", callback_data="about")],
        [InlineKeyboardButton("❓ FAQ", callback_data="faq")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"Welcome to {MERCHANT_NAME}! 📖\n\n"
        f"We accept KHQR payment from any bank in Cambodia.",
        reply_markup=reply_markup
    )

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show how to pay"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("◀️ Back", callback_data="back_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "💳 *How to Pay with KHQR:*\n\n"
        "1️⃣ Select a book and currency\n"
        "2️⃣ Enter your name and phone\n"
        "3️⃣ We generate a KHQR QR code\n"
        "4️⃣ Scan with your bank app (WING, ABA, BIDC, etc.)\n"
        "5️⃣ Complete the payment\n"
        "6️⃣ Click 'I've Paid' to confirm\n\n"
        "✅ Simple, fast, secure!\n"
        "🔒 All banks in Cambodia supported",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show FAQ"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("◀️ Back", callback_data="back_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "❓ *Frequently Asked Questions:*\n\n"
        "*Q: What is KHQR?*\n"
        "A: KHQR is Cambodia's official QR payment code.\n\n"
        "*Q: Which banks are supported?*\n"
        "A: All Cambodian banks (WING, ABA, BIDC, Acleda, etc.)\n\n"
        "*Q: Is it secure?*\n"
        "A: Yes! KHQR is encrypted and verified by Bakong.\n\n"
        "*Q: How long is the payment valid?*\n"
        "A: 10 minutes from generation.\n\n"
        "*Q: What if payment expires?*\n"
        "A: Generate a new QR code.\n\n"
        "📞 Support: Contact merchant directly",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel order"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("📚 Browse Books", callback_data="browse")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "❌ Order cancelled.",
        reply_markup=reply_markup
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main callback handler"""
    query = update.callback_query
    data = query.data
    
    if data == "browse":
        await browse_books(update, context)
    elif data.startswith("select_"):
        await select_book(update, context)
    elif data.startswith("currency_"):
        return await select_currency(update, context)
    elif data.startswith("check_"):
        await check_payment_status_handler(update, context)
    elif data == "back_menu":
        await back_menu(update, context)
    elif data == "about":
        await about(update, context)
    elif data == "faq":
        await faq(update, context)
    elif data == "cancel_order":
        await cancel_order(update, context)
    elif data in ["phone_yes", "phone_skip"]:
        return await handle_phone(update, context)
    elif data.startswith("cat_"):
        return await category_selected(update, context)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input"""
    user_state = context.user_data.get('conversation_state')
    
    if user_state == REQUESTING_NAME:
        return await name_received(update, context)
    elif user_state == REQUESTING_PHONE:
        return await phone_received(update, context)

# ============ MAIN ============

def main():
    """Start the bot"""
    if not TELEGRAM_TOKEN or not BAKONG_TOKEN or not BANK_ACCOUNT:
        print("❌ Missing required environment variables!")
        print("Required:")
        print("  TELEGRAM_BOT_TOKEN - from @BotFather")
        print("  BAKONG_TOKEN - from https://api-bakong.nbc.gov.kh/register or RBK from https://bakongrelay.com")
        print("  BANK_ACCOUNT - format: username@bank (e.g., myshop@wing)")
        return
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(select_currency, pattern="^currency_"),
        ],
        states={
            REQUESTING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_received)],
            REQUESTING_PHONE: [
                CallbackQueryHandler(handle_phone, pattern="^phone_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, phone_received)
            ],
            REQUESTING_GROUP: [CallbackQueryHandler(category_selected, pattern="^cat_")],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    print("=" * 60)
    print("🤖 Telegram Bookshop Bot with KHQR Payment")
    print("=" * 60)
    print(f"✅ Bot Token: {TELEGRAM_TOKEN[:20]}...")
    print(f"✅ Bakong Token: {BAKONG_TOKEN[:20]}...")
    print(f"✅ Bank Account: {BANK_ACCOUNT}")
    print(f"✅ KHQR Library: Loaded")
    print("=" * 60)
    print("🚀 Bot is running... Press Ctrl+C to stop")
    print("=" * 60)
    
    app.run_polling()

if __name__ == "__main__":
    main()
