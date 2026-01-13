#!/usr/bin/env python3
"""
Telegram Book Shop Bot - FIXED KHQR Version
Working with real KHQR payments
"""

import os
import json
import logging
import asyncio
import sqlite3
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from io import BytesIO

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Telegram Bot
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ConversationHandler
)

# KHQR - CORRECT IMPORT
try:
    from bakong_khqr import KHQR
    KHQR_AVAILABLE = True
    print("✅ KHQR library imported successfully")
except ImportError as e:
    print(f"❌ KHQR import error: {e}")
    KHQR_AVAILABLE = False

# For QR code generation
import qrcode
from PIL import Image, ImageDraw

# ===================== CONFIGURATION =====================
TOKEN = os.getenv('TOKEN', '8502848831:AAG184UsX7tirVtPSCsAcjzPBN8_t4PQ42E')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '1273972944').split(',')]
BAKONG_TOKEN = os.getenv('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7ImlkIjoiM2VhMzg3OTRkMDJlNDZkYyJ9LCJpYXQiOjE3NjgyNzg0NzMsImV4cCI6MTc3NjA1NDQ3M30.gybhfjIvzzVCxbLUXHa5JPv6FaDtty1nEmZWBykfIrM', '')  # Your Bakong API token

# KHQR Configuration - CHANGE THESE!
BAKONG_ACCOUNT = os.getenv('BAKONG_ACCOUNT', 'sin_soktep@bkrt')  # ⚠️ CHANGE TO YOUR ACCOUNT
MERCHANT_NAME = "Classmate Book Shop"
MERCHANT_CITY = "Phnom Penh"
STORE_LABEL = "Book Shop"
PHONE_NUMBER = "85512345678"  # Your phone number

# Create necessary directories
os.makedirs('payment_images', exist_ok=True)

# Product catalog
PRODUCTS = {
    "math": {
        "name_kh": "សៀវភៅគណិតវិទ្យា",
        "price": 1.70,
        "description_kh": "សៀវភៅគណិតវិទ្យាសម្រាប់និស្សិត",
        "currency": "USD"
    },
    "human": {
        "name_kh": "Human & Society",
        "price": 1.99,
        "description_kh": "សៀវភៅមនុស្ស និងសង្គម",
        "currency": "USD"
    },
    "business": {
        "name_kh": "គោលការណ៍អាជីវកម្ម",
        "price": 1.99,
        "description_kh": "គោលការណ៍គ្រឹះនៃអាជីវកម្ម",
        "currency": "USD"
    },
    "computer": {
        "name_kh": "សៀវភៅកុំព្យូទ័រ",
        "price": 2.50,
        "description_kh": "សៀវភៅវិទ្យាសាស្ត្រកុំព្យូទ័រ",
        "currency": "USD"
    }
}

# Conversation states
(
    CHOOSING, SELECT_PRODUCT, GET_QUANTITY, 
    GET_NAME, GET_GROUP, GET_PHONE, 
    PAYMENT, WAITING_PAYMENT
) = range(8)

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===================== SIMPLE DATABASE =====================
class SimpleDB:
    def __init__(self):
        self.conn = sqlite3.connect('bookshop.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
    
    def create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                student_group TEXT,
                phone TEXT,
                product_name TEXT,
                quantity INTEGER,
                total_amount REAL,
                payment_status TEXT DEFAULT 'pending',
                khqr_md5 TEXT,
                bill_number TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
    
    def add_order(self, user_id, username, full_name, group, phone, product_name, quantity, total):
        bill_number = f"BOOK{datetime.now().strftime('%Y%m%d%H%M%S')}{user_id}"
        
        self.cursor.execute('''
            INSERT INTO orders 
            (user_id, username, full_name, student_group, phone, product_name, quantity, total_amount, bill_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, username, full_name, group, phone, product_name, quantity, total, bill_number))
        
        order_id = self.cursor.lastrowid
        self.conn.commit()
        return order_id, bill_number
    
    def save_md5(self, order_id, md5_hash):
        self.cursor.execute('''
            UPDATE orders SET khqr_md5 = ? WHERE id = ?
        ''', (md5_hash, order_id))
        self.conn.commit()
    
    def update_status(self, md5_hash, status):
        self.cursor.execute('''
            UPDATE orders SET payment_status = ? WHERE khqr_md5 = ?
        ''', (status, md5_hash))
        self.conn.commit()
    
    def get_order_by_md5(self, md5_hash):
        self.cursor.execute('SELECT * FROM orders WHERE khqr_md5 = ?', (md5_hash,))
        row = self.cursor.fetchone()
        if row:
            columns = [desc[0] for desc in self.cursor.description]
            return dict(zip(columns, row))
        return None
    
    def get_user_orders(self, user_id):
        self.cursor.execute('SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 10', (user_id,))
        return self.cursor.fetchall()

db = SimpleDB()

# ===================== KHQR PAYMENT SYSTEM - FIXED =====================
class KHQRPaymentSystem:
    def __init__(self):
        self.token = BAKONG_TOKEN
        self.khqr = None
        
        print(f"\n🔧 KHQR Initialization:")
        print(f"   Token available: {'✅' if self.token else '❌'}")
        print(f"   Library available: {'✅' if KHQR_AVAILABLE else '❌'}")
        
        if KHQR_AVAILABLE and self.token:
            try:
                # Initialize KHQR with token
                self.khqr = KHQR(self.token)
                print(f"   KHQR instance created: ✅")
                print(f"   Account: {BAKONG_ACCOUNT}")
            except Exception as e:
                print(f"   ❌ Failed to create KHQR: {e}")
                self.khqr = None
        else:
            print(f"   ⚠️  Cannot initialize KHQR")
    
    def create_payment(self, order_id, bill_number, amount_usd, customer_phone=""):
        """Create KHQR payment - FIXED VERSION"""
        print(f"\n🔄 Creating KHQR Payment:")
        print(f"   Order: #{order_id}")
        print(f"   Bill: {bill_number}")
        print(f"   Amount: ${amount_usd}")
        
        if not self.khqr:
            print("   ❌ KHQR not initialized!")
            return None, None, None
        
        try:
            # Convert USD to Riel (1 USD = 4100 Riel approximately)
            # KHQR works better with KHR currency in Cambodia
            amount_riel = int(amount_usd * 4100)
            
            print(f"   Converting: ${amount_usd} → {amount_riel}៛")
            print(f"   Account: {BAKONG_ACCOUNT}")
            print(f"   Merchant: {MERCHANT_NAME}")
            
            # Generate QR code data - USING CORRECT PARAMETERS
            qr_data = self.khqr.create_qr(
                bank_account=BAKONG_ACCOUNT,
                merchant_name=MERCHANT_NAME,
                merchant_city=MERCHANT_CITY,
                amount=amount_riel,  # In Riel
                currency='KHR',      # Use KHR for Cambodia
                store_label=STORE_LABEL,
                phone_number=customer_phone or PHONE_NUMBER,
                bill_number=bill_number,
                terminal_label=f"Order#{order_id}",
                static=False
            )
            
            print(f"   ✅ QR data generated")
            print(f"   QR preview: {qr_data[:80]}...")
            
            # Generate MD5 hash
            md5_hash = self.khqr.generate_md5(qr_data)
            print(f"   ✅ MD5 hash: {md5_hash}")
            
            # Generate QR image
            try:
                qr_image = self.khqr.qr_image(qr_data)
                print(f"   ✅ QR image generated")
                
                # If qr_image is a file path, open it
                if isinstance(qr_image, str):
                    qr_img = Image.open(qr_image)
                else:
                    qr_img = qr_image
                    
            except Exception as img_error:
                print(f"   ⚠️  Could not generate image: {img_error}")
                # Create fallback QR
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=10,
                    border=4,
                )
                qr.add_data(qr_data)
                qr.make(fit=True)
                qr_img = qr.make_image(fill_color="black", back_color="white")
            
            return qr_data, md5_hash, qr_img
            
        except Exception as e:
            print(f"   ❌ KHQR creation failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return None, None, None
    
    def check_payment(self, md5_hash):
        """Check payment status using MD5"""
        if not self.khqr:
            print(f"❌ Cannot check payment - KHQR not initialized")
            return "ERROR"
        
        try:
            print(f"🔄 Checking payment for MD5: {md5_hash[:12]}...")
            status = self.khqr.check_payment(md5_hash)
            print(f"✅ Payment status: {status}")
            return status
        except Exception as e:
            print(f"❌ Payment check error: {e}")
            return "ERROR"

# Initialize payment system
payment_system = KHQRPaymentSystem()

# ===================== PAYMENT VERIFICATION =====================
async def check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE, md5_hash=None):
    """Check payment status and update database"""
    query = update.callback_query
    if query:
        await query.answer()
    
    # Get MD5 from callback or context
    if not md5_hash:
        if query and query.data.startswith("check_"):
            md5_hash = query.data.replace("check_", "")
        else:
            md5_hash = context.user_data.get('md5_hash', '')
    
    if not md5_hash:
        message = "❌ រកមិនឃើញលេខកូដទូទាត់ទេ។"
        if query:
            await query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
        return
    
    try:
        # Show checking message
        if query:
            await query.edit_message_text("🔄 **កំពុងពិនិត្យស្ថានភាពទូទាត់...**")
        
        # Check payment status
        status = payment_system.check_payment(md5_hash)
        
        # Get order info
        order = db.get_order_by_md5(md5_hash)
        
        if status == "PAID":
            # Update database
            db.update_status(md5_hash, 'paid')
            
            message = f"""
🎉 **ការទូទាត់របស់អ្នកបានជោគជ័យ!**

🆔 លេខការបញ្ជាទិញ: #{order['id'] if order else 'N/A'}
💰 ចំនួនទឹកប្រាក់: ${order['total_amount'] if order else 0:.2f}
✅ ស្ថានភាព: បានទូទាត់
🕒 ពេលវេលា: {datetime.now().strftime('%H:%M:%S')}

សូមអរគុណសម្រាប់ការទិញ!
"""
            
            # Notify user if different from query sender
            if order and query and order['user_id'] != query.from_user.id:
                try:
                    await context.bot.send_message(
                        chat_id=order['user_id'],
                        text=f"🎉 ការទូទាត់សម្រាប់ការបញ្ជាទិញ #{order['id']} បានជោគជ័យ!"
                    )
                except:
                    pass
        
        elif status == "UNPAID":
            message = f"""
⏳ **ការទូទាត់មិនទាន់បានបញ្ចប់**

🆔 លេខការបញ្ជាទិញ: #{order['id'] if order else 'N/A'}
💰 ចំនួនទឹកប្រាក់: ${order['total_amount'] if order else 0:.2f}
❌ ស្ថានភាព: មិនទាន់ទូទាត់

សូមស្កេនកូដ KHQR និងទូទាត់។
"""
        else:
            message = f"""
⚠️ **មិនអាចពិនិត្យស្ថានភាពបាន**

ស្ថានភាព: {status}
សូមព្យាយាមម្តងទៀតក្រោយមក។
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 ពិនិត្យម្តងទៀត", callback_data=f"check_{md5_hash}")],
            [InlineKeyboardButton("📋 ការបញ្ជាទិញរបស់ខ្ញុំ", callback_data="my_orders")],
            [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await query.edit_message_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, reply_markup=reply_markup)
        
    except Exception as e:
        print(f"❌ Payment check error: {e}")
        error_msg = "❌ មិនអាចពិនិត្យស្ថានភាពបាន។ សូមព្យាយាមម្តងទៀត។"
        if query:
            await query.edit_message_text(error_msg)
        else:
            await update.message.reply_text(error_msg)

# ===================== BOT HANDLERS =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    # Check KHQR status
    if payment_system.khqr:
        khqr_status = "✅ KHQR Ready"
    elif KHQR_AVAILABLE:
        khqr_status = "⚠️  Need Token"
    else:
        khqr_status = "❌ Not Available"
    
    welcome_msg = f"""👋 សួស្តី {user.first_name}!

📚 **ស្វាគមន៍មកកាន់ហាងសៀវភៅសម្រាប់មិត្តរួមថ្នាក់**

💳 **ប្រព័ន្ធទូទាត់:** {khqr_status}
🔐 **ការផ្ទៀងផ្ទាត់:** ដោយស្វ័យប្រវត្តិ (MD5)

**សៀវភៅទាំងអស់៖**
• សៀវភៅគណិតវិទ្យា - $1.70
• Human & Society - $1.99
• គោលការណ៍អាជីវកម្ម - $1.99
• សៀវភៅកុំព្យូទ័រ - $2.50

**របៀបបញ្ជាទិញ៖**
1. ជ្រើសរើសសៀវភៅ
2. បញ្ចូលចំនួន
3. បំពេញព័ត៌មាន
4. ស្កេន KHQR និងទូទាត់
5. ពិនិត្យស្ថានភាពដោយស្វ័យប្រវត្តិ
"""
    
    keyboard = [
        [InlineKeyboardButton("🛒 បញ្ជាទិញឥឡូវនេះ", callback_data="order")],
        [InlineKeyboardButton("📋 ការបញ្ជាទិញរបស់ខ្ញុំ", callback_data="my_orders")],
        [InlineKeyboardButton("🔄 ពិនិត្យទូទាត់", callback_data="check_payments")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_msg, reply_markup=reply_markup)
    return CHOOSING

async def generate_khqr_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate REAL KHQR payment - FIXED VERSION"""
    query = update.callback_query
    await query.answer()
    
    try:
        user = update.effective_user
        product = context.user_data['product']
        quantity = context.user_data['quantity']
        total = context.user_data['total']
        name = context.user_data['name']
        group = context.user_data['group']
        phone = context.user_data.get('phone', '')
        
        # Check if KHQR is ready
        if not payment_system.khqr:
            error_msg = f"""
❌ **KHQR System Not Ready**

**Current Status:**
• KHQR Library: {'✅ Available' if KHQR_AVAILABLE else '❌ Not installed'}
• Bakong Token: {'✅ Set' if BAKONG_TOKEN else '❌ Missing'}
• Account: {BAKONG_ACCOUNT}

**For School Project:**
1. Install: pip3 install bakong-khqr
2. Get token from: https://api-bakong.nbc.gov.kh/register/
3. Set BAKONG_TOKEN in Railway
4. Use your real Bakong account

**Temporary Fix:**
Contact admin for manual payment: {BAKONG_ACCOUNT}
"""
            await query.edit_message_text(error_msg)
            return CHOOSING
        
        # Show generating message
        await query.edit_message_text("🔄 **កំពុងបង្កើតកូដ KHQR...**\n\nសូមរង់ចាំ។")
        
        # Create order in database
        order_id, bill_number = db.add_order(
            user.id,
            user.username or "",
            name,
            group,
            phone,
            product['name_kh'],
            quantity,
            total
        )
        
        print(f"\n📝 Creating order #{order_id} for {name}")
        
        # Generate REAL KHQR
        qr_data, md5_hash, qr_image = payment_system.create_payment(
            order_id, bill_number, total, phone
        )
        
        if not qr_data or not md5_hash:
            raise Exception("Failed to generate KHQR")
        
        # Save MD5 to database
        db.save_md5(order_id, md5_hash)
        
        # Store in context
        context.user_data['order_id'] = order_id
        context.user_data['md5_hash'] = md5_hash
        
        # Convert image to bytes for Telegram
        bio = BytesIO()
        
        # If qr_image is PIL Image
        if hasattr(qr_image, 'save'):
            qr_image.save(bio, 'PNG')
        else:
            # Try to save as is
            try:
                with open(qr_image, 'rb') as f:
                    bio.write(f.read())
            except:
                # Create simple QR
                qr = qrcode.QRCode()
                qr.add_data(qr_data)
                img = qr.make_image()
                img.save(bio, 'PNG')
        
        bio.seek(0)
        
        # Create payment message
        payment_msg = f"""
💳 **ការទូទាត់តាម KHQR**

📘 សៀវភៅ៖ {product['name_kh']}
🔢 ចំនួន៖ {quantity}
💰 ចំនួនទឹកប្រាក់៖ **${total:.2f} USD** (~{int(total * 4000):,}៛)
📝 លេខការបញ្ជាទិញ៖ **#{order_id}**
🔗 លេខវិក័យប័ត្រ៖ {bill_number}
🔐 លេខកូដ៖ `{md5_hash[:16]}...`

⬇️ **សូមស្កេនកូដ KHQR ខាងក្រោម៖**

**ព័ត៌មានបន្ថែម៖**
• ទូទាត់ទៅ៖ {BAKONG_ACCOUNT}
• ឈ្មោះហាង៖ {MERCHANT_NAME}
• ទីក្រុង៖ {MERCHANT_CITY}

**របៀបទូទាត់៖**
1. បើកកម្មវិធី **Bakong**
2. ស្កេនកូដ KHQR
3. បញ្ជាក់ការទូទាត់
4. រង់ចាំការផ្ទៀងផ្ទាត់

**ការផ្ទៀងផ្ទាត់៖**
• ប្រព័ន្ធនឹងពិនិត្យដោយស្វ័យប្រវត្តិ
• ចុចប៊ូតុងខាងក្រោមដើម្បីពិនិត្យស្ថានភាព
• អ្នកនឹងទទួលបានការបញ្ជាក់
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 ពិនិត្យស្ថានភាពទូទាត់", callback_data=f"check_{md5_hash}")],
            [InlineKeyboardButton("📋 ការបញ្ជាទិញរបស់ខ្ញុំ", callback_data="my_orders")],
            [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send QR code
        await query.message.reply_photo(
            photo=bio,
            caption=payment_msg,
            reply_markup=reply_markup
        )
        
        print(f"✅ KHQR sent for order #{order_id}")
        print(f"✅ MD5: {md5_hash}")
        
        # Schedule auto-check in 30 seconds
        await asyncio.sleep(30)
        await check_payment_status(update, context, md5_hash)
        
        return WAITING_PAYMENT
        
    except Exception as e:
        print(f"❌ Error in generate_khqr_payment: {str(e)}")
        import traceback
        traceback.print_exc()
        
        error_msg = f"""
❌ **មិនអាចបង្កើតកូដ KHQR បាន**

**កំហុស:** {str(e)}

**ដំណោះស្រាយ៖**
1. ពិនិត្យ BAKONG_TOKEN និង BAKONG_ACCOUNT
2. ទាក់ទងអ្នកគ្រប់គ្រង
3. ប្រើប្រព័ន្ធទូទាត់ផ្សេង

**ទូទាត់ដោយផ្ទាល់៖**
គណនី៖ {BAKONG_ACCOUNT}
ចំនួន៖ ${context.user_data.get('total', 0):.2f}
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 ព្យាយាមម្តងទៀត", callback_data="order")],
            [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(error_msg, reply_markup=reply_markup)
        return CHOOSING

# ===================== MAIN FUNCTION =====================
def main():
    """Start the bot"""
    print("=" * 60)
    print("🤖 Telegram Book Shop Bot - REAL KHQR Payments")
    print("=" * 60)
    
    # Debug information
    print(f"\n🔧 Configuration Check:")
    print(f"   Telegram Token: {'✅' if TOKEN and TOKEN != 'YOUR_BOT_TOKEN_HERE' else '❌'}")
    print(f"   KHQR Library: {'✅ Available' if KHQR_AVAILABLE else '❌ Not installed'}")
    print(f"   Bakong Token: {'✅ Set' if BAKONG_TOKEN else '❌ Missing'}")
    print(f"   Bakong Account: {BAKONG_ACCOUNT}")
    print(f"   Admin IDs: {ADMIN_IDS}")
    
    if not KHQR_AVAILABLE:
        print(f"\n⚠️  WARNING: bakong-khqr not installed!")
        print("   Run: pip3 install bakong-khqr")
    
    if not BAKONG_TOKEN:
        print(f"\n⚠️  WARNING: BAKONG_TOKEN not set!")
        print("   Get from: https://api-bakong.nbc.gov.kh/register/")
        print("   Or use: https://bakongrelay.com/ (for servers outside Cambodia)")
    
    if BAKONG_ACCOUNT == 'your_username@aba':
        print(f"\n⚠️  WARNING: Using default Bakong account!")
        print("   Change BAKONG_ACCOUNT to your real account")
    
    # Create application
    try:
        application = Application.builder().token(TOKEN).build()
        
        # Add conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                CHOOSING: [CallbackQueryHandler(handle_callback)],
                SELECT_PRODUCT: [CallbackQueryHandler(handle_callback)],
                GET_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_quantity)],
                GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
                GET_GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_group)],
                GET_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
                PAYMENT: [CallbackQueryHandler(handle_callback)],
                WAITING_PAYMENT: [CallbackQueryHandler(handle_callback)]
            },
            fallbacks=[CommandHandler('start', start)]
        )
        
        application.add_handler(conv_handler)
        
        print(f"\n🚀 Bot starting...")
        print(f"💳 Payment: REAL KHQR with MD5 verification")
        print("=" * 60)
        
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
