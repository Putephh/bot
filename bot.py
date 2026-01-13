#!/usr/bin/env python3
"""
Telegram Book Shop Bot with REAL KHQR Payments - CORRECT VERSION
"""

import os
import json
import logging
import asyncio
import sqlite3
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

# Try to import bakong_khqr CORRECTLY
try:
    from bakong_khqr import KHQR
    KHQR_AVAILABLE = True
    print("✅ KHQR library imported successfully using: from bakong_khqr import KHQR")
except ImportError as e:
    print(f"❌ KHQR import error: {e}")
    KHQR_AVAILABLE = False
    print("Run: pip3 install bakong-khqr")
except Exception as e:
    print(f"❌ Other import error: {e}")
    KHQR_AVAILABLE = False

# For QR image
import qrcode
from PIL import Image, ImageDraw
import hashlib

# ===================== CONFIGURATION =====================
TOKEN = os.getenv('TOKEN', '8502848831:AAG184UsX7tirVtPSCsAcjzPBN8_t4PQ42E')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '1273972944').split(',')]
BAKONG_TOKEN = os.getenv('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7ImlkIjoiM2VhMzg3OTRkMDJlNDZkYyJ9LCJpYXQiOjE3NjgyNzg0NzMsImV4cCI6MTc3NjA1NDQ3M30.gybhfjIvzzVCxbLUXHa5JPv6FaDtty1nEmZWBykfIrM', '')  # REQUIRED: Get from api-bakong.nbc.gov.kh

# KHQR Configuration
BAKONG_ACCOUNT = os.getenv('BAKONG_ACCOUNT', 'sin_soktep@bkrt')  # Your Bakong account (e.g., yourname@aba)
MERCHANT_NAME = "Classmate Book Shop"
MERCHANT_CITY = "Phnom Penh"
STORE_LABEL = "Telegram Book Shop"
PHONE_NUMBER = "85581599652"  # Your store phone

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
        self.conn = sqlite3.connect('bookshop_payments.db', check_same_thread=False)
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
                amount REAL,
                total_amount REAL,
                currency TEXT,
                payment_status TEXT DEFAULT 'pending',
                khqr_data TEXT,
                khqr_md5 TEXT,
                bill_number TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
    
    def create_order(self, user_id, username, full_name, group, phone, 
                    product_name, quantity, amount, total, currency):
        """Create new order and return order_id"""
        bill_number = f"BOOK{datetime.now().strftime('%Y%m%d%H%M%S')}{user_id}"
        
        self.cursor.execute('''
            INSERT INTO orders 
            (user_id, username, full_name, student_group, phone, 
             product_name, quantity, amount, total_amount, currency, bill_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, username, full_name, group, phone, 
              product_name, quantity, amount, total, currency, bill_number))
        
        order_id = self.cursor.lastrowid
        self.conn.commit()
        return order_id, bill_number
    
    def save_khqr_data(self, order_id, khqr_data, khqr_md5):
        """Save KHQR data to order"""
        self.cursor.execute('''
            UPDATE orders SET khqr_data = ?, khqr_md5 = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (khqr_data, khqr_md5, order_id))
        self.conn.commit()
    
    def update_payment_status(self, md5_hash, status):
        """Update payment status when verified"""
        self.cursor.execute('''
            UPDATE orders SET payment_status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE khqr_md5 = ?
        ''', (status, md5_hash))
        self.conn.commit()
        return self.cursor.rowcount > 0
    
    def get_order_by_md5(self, md5_hash):
        """Get order by MD5 hash"""
        self.cursor.execute('SELECT * FROM orders WHERE khqr_md5 = ?', (md5_hash,))
        row = self.cursor.fetchone()
        if row:
            columns = [desc[0] for desc in self.cursor.description]
            return dict(zip(columns, row))
        return None
    
    def get_user_orders(self, user_id):
        """Get all orders for a user"""
        self.cursor.execute('''
            SELECT id, product_name, quantity, total_amount, currency, 
                   payment_status, created_at
            FROM orders 
            WHERE user_id = ? 
            ORDER BY created_at DESC
            LIMIT 10
        ''', (user_id,))
        return self.cursor.fetchall()
    
    def get_pending_orders(self):
        """Get all pending orders"""
        self.cursor.execute('''
            SELECT id, khqr_md5, user_id, total_amount, created_at
            FROM orders 
            WHERE payment_status = 'pending' 
            ORDER BY created_at ASC
            LIMIT 20
        ''')
        return self.cursor.fetchall()

db = SimpleDB()

# ===================== KHQR PAYMENT SYSTEM =====================
class KHQRPayment:
    def __init__(self):
        self.token = BAKONG_TOKEN
        self.khqr_instance = None
        
        if KHQR_AVAILABLE and self.token:
            try:
                # CORRECT: Create instance with token
                self.khqr_instance = KHQR(self.token)
                print(f"✅ KHQR instance created with token: {self.token[:20]}...")
            except Exception as e:
                print(f"❌ Failed to create KHQR instance: {e}")
                self.khqr_instance = None
        else:
            print(f"⚠️  KHQR Status - Available: {KHQR_AVAILABLE}, Token: {'Yes' if self.token else 'No'}")
    
    def create_khqr_payment(self, order_id, bill_number, amount, currency="USD"):
        """Create real KHQR payment using bakong_khqr library"""
        if not self.khqr_instance:
            raise Exception("KHQR not initialized. Check BAKONG_TOKEN.")
        
        try:
            print(f"🔄 Creating KHQR for order #{order_id}, amount: ${amount} {currency}")
            
            # Convert amount for KHQR (KHQR uses smallest unit, e.g., cents for USD)
            if currency == "USD":
                # Convert to cents (multiply by 100)
                khqr_amount = int(amount * 100)
                khqr_currency = "USD"
            else:
                khqr_amount = int(amount)
                khqr_currency = currency
            
            print(f"   Amount in KHQR: {khqr_amount} {khqr_currency}")
            
            # Create QR code data - CORRECT METHOD CALL
            qr_data = self.khqr_instance.create_qr(
                bank_account=BAKONG_ACCOUNT,
                merchant_name=MERCHANT_NAME,
                merchant_city=MERCHANT_CITY,
                amount=khqr_amount,
                currency=khqr_currency,
                store_label=STORE_LABEL,
                phone_number=PHONE_NUMBER,
                bill_number=bill_number,
                terminal_label=f"Order#{order_id}",
                static=False  # Dynamic QR code
            )
            
            print(f"✅ KHQR data generated (first 100 chars): {qr_data[:100]}...")
            
            # Generate MD5 hash for verification
            md5_hash = self.khqr_instance.generate_md5(qr_data)
            print(f"✅ MD5 hash: {md5_hash}")
            
            # Generate QR image
            try:
                # Try to generate image using the library
                qr_image_path = self.khqr_instance.qr_image(qr_data)
                print(f"✅ QR image generated at: {qr_image_path}")
                qr_image = Image.open(qr_image_path)
            except Exception as img_error:
                print(f"⚠️  Could not generate KHQR image, using fallback: {img_error}")
                qr_image = self._create_fallback_qr(qr_data)
            
            return qr_data, md5_hash, qr_image
            
        except Exception as e:
            print(f"❌ KHQR creation error: {str(e)}")
            # Print full traceback for debugging
            import traceback
            traceback.print_exc()
            raise
    
    def _create_fallback_qr(self, qr_data):
        """Create fallback QR code if library fails"""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="white")
    
    def check_payment_status(self, md5_hash):
        """Check if payment is completed"""
        if not self.khqr_instance:
            return "KHQR_NOT_AVAILABLE"
        
        try:
            print(f"🔄 Checking payment status for MD5: {md5_hash[:12]}...")
            status = self.khqr_instance.check_payment(md5_hash)
            print(f"✅ Payment status: {status}")
            return status
        except Exception as e:
            print(f"❌ Payment check error: {e}")
            return "CHECK_ERROR"

# Initialize payment system
payment_system = KHQRPayment()

# ===================== BACKGROUND PAYMENT CHECKER =====================
async def check_payments_background(context: ContextTypes.DEFAULT_TYPE):
    """Background task to check payment status"""
    try:
        print(f"\n🔄 [{datetime.now().strftime('%H:%M:%S')}] Checking pending payments...")
        
        pending_orders = db.get_pending_orders()
        print(f"   Found {len(pending_orders)} pending orders")
        
        for order in pending_orders:
            order_id, md5_hash, user_id, amount, created_at = order
            
            if not md5_hash or md5_hash == 'None':
                continue
            
            print(f"   Checking order #{order_id}, MD5: {md5_hash[:12]}...")
            
            # Check payment status
            status = payment_system.check_payment_status(md5_hash)
            
            if status == "PAID":
                print(f"   ✅ Order #{order_id} PAID! Updating database...")
                db.update_payment_status(md5_hash, 'paid')
                
                # Notify user
                try:
                    message = f"""
🎉 **ការទូទាត់របស់អ្នកបានជោគជ័យ!**

🆔 លេខការបញ្ជាទិញ: #{order_id}
💰 ចំនួនទឹកប្រាក់: ${amount:.2f}
✅ ស្ថានភាព: បានទូទាត់
🕒 ពេលវេលា: {datetime.now().strftime('%H:%M:%S')}

សូមអរគុណសម្រាប់ការទិញ!
"""
                    await context.bot.send_message(chat_id=user_id, text=message)
                    print(f"   ✅ Notified user {user_id}")
                except Exception as e:
                    print(f"   ❌ Failed to notify user {user_id}: {e}")
            
            elif status == "UNPAID":
                print(f"   ⏳ Order #{order_id} still unpaid")
            
            # Small delay between API calls
            await asyncio.sleep(1)
        
        print(f"✅ [{datetime.now().strftime('%H:%M:%S')}] Payment check completed")
        
    except Exception as e:
        print(f"❌ Error in background check: {e}")

# ===================== BOT HANDLERS =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    # Check KHQR status
    if payment_system.khqr_instance:
        khqr_status = "✅ REAL KHQR"
    elif KHQR_AVAILABLE and BAKONG_TOKEN:
        khqr_status = "⚠️  Setup Issue"
    else:
        khqr_status = "❌ Not Configured"
    
    welcome_msg = f"""👋 សួស្តី {user.first_name}!

📚 **ស្វាគមន៍មកកាន់ហាងសៀវភៅសម្រាប់មិត្តរួមថ្នាក់**

💳 **ប្រព័ន្ធទូទាត់:** {khqr_status}
🔄 **ការផ្ទៀងផ្ទាត់:** ដោយស្វ័យប្រវត្តិ

**សៀវភៅទាំងអស់៖**
• សៀវភៅគណិតវិទ្យា - $1.70
• Human & Society - $1.99
• គោលការណ៍អាជីវកម្ម - $1.99
• សៀវភៅកុំព្យូទ័រ - $2.50

**របៀបបញ្ជាទិញ៖**
1. ជ្រើសរើសសៀវភៅ
2. បញ្ចូលចំនួន
3. បំពេញព័ត៌មាន
4. ស្កេនកូដ KHQR និងទូទាត់
5. រង់ចាំការបញ្ជាក់ដោយស្វ័យប្រវត្តិ
"""
    
    keyboard = [
        [InlineKeyboardButton("🛒 បញ្ជាទិញឥឡូវនេះ", callback_data="order")],
        [InlineKeyboardButton("📋 ការបញ្ជាទិញរបស់ខ្ញុំ", callback_data="my_orders")],
        [InlineKeyboardButton("🔄 ពិនិត្យទូទាត់", callback_data="check_my_payments")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_msg, reply_markup=reply_markup)
    return CHOOSING

async def start_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start order process"""
    query = update.callback_query
    await query.answer()
    
    context.user_data.clear()
    
    keyboard = []
    for pid, product in PRODUCTS.items():
        keyboard.append([
            InlineKeyboardButton(
                f"{product['name_kh']} - ${product['price']:.2f}",
                callback_data=f"select_{pid}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📚 **ជ្រើសរើសសៀវភៅ៖**\n\n"
        "ជ្រើសរើសសៀវភៅមួយដើម្បីទិញ៖",
        reply_markup=reply_markup
    )
    return SELECT_PRODUCT

async def select_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle product selection"""
    query = update.callback_query
    await query.answer()
    
    product_id = query.data.replace("select_", "")
    
    if product_id not in PRODUCTS:
        await query.edit_message_text("❌ រកមិនឃើញសៀវភៅនេះទេ។")
        return CHOOSING
    
    product = PRODUCTS[product_id]
    context.user_data['product'] = product
    context.user_data['product_id'] = product_id
    
    await query.edit_message_text(
        f"📘 **អ្នកបានជ្រើសរើស៖** {product['name_kh']}\n"
        f"💰 **តម្លៃ៖** ${product['price']:.2f}\n\n"
        "🔢 **តើអ្នកចង់ទិញចំនួនប៉ុន្មាន?**\n"
        "សរសេរលេខ (១-១០)៖"
    )
    return GET_QUANTITY

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get quantity from user"""
    try:
        quantity = int(update.message.text)
        
        if quantity < 1 or quantity > 10:
            await update.message.reply_text("❌ សូមបញ្ចូលលេខពី ១ ទៅ ១០។")
            return GET_QUANTITY
        
        context.user_data['quantity'] = quantity
        
        # Calculate total
        product = context.user_data['product']
        total = product['price'] * quantity
        context.user_data['total'] = total
        
        # Ask for name
        await update.message.reply_text(
            f"✅ **ចំនួន៖** {quantity}\n"
            f"💰 **សរុប៖** ${total:.2f}\n\n"
            "📝 **សូមបញ្ចូលឈ្មោះពេញរបស់អ្នក៖**"
        )
        return GET_NAME
        
    except ValueError:
        await update.message.reply_text("❌ សូមបញ្ចូលលេខដែលត្រឹមត្រូវ។")
        return GET_QUANTITY

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get student name"""
    name = update.message.text.strip()
    
    if len(name) < 2:
        await update.message.reply_text("❌ សូមបញ្ចូលឈ្មោះពេញ (យ៉ាងហោចណាស់ ២តួអក្សរ)។")
        return GET_NAME
    
    context.user_data['name'] = name
    
    await update.message.reply_text(
        f"✅ **ឈ្មោះ៖** {name}\n\n"
        "🎓 **តើអ្នកស្ថិតនៅក្រុមសិក្សាអ្វី?**\n"
        "ឧទាហរណ៍៖ Civil M3, Civil M4"
    )
    return GET_GROUP

async def get_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get student group"""
    group = update.message.text.strip()
    
    if not group:
        await update.message.reply_text("❌ សូមបញ្ចូលក្រុមសិក្សា។")
        return GET_GROUP
    
    context.user_data['group'] = group
    
    await update.message.reply_text(
        f"✅ **ក្រុម៖** {group}\n\n"
        "📱 **លេខទូរស័ព្ទ (មិនចាំបាច់)៖**\n"
        "បញ្ចូលលេខទូរស័ព្ទ ឬសរសេរ 'skip'៖"
    )
    return GET_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get phone number"""
    phone = update.message.text.strip()
    
    if phone.lower() == 'skip':
        phone = ""
    
    context.user_data['phone'] = phone
    
    # Show summary
    product = context.user_data['product']
    quantity = context.user_data['quantity']
    total = context.user_data['total']
    name = context.user_data['name']
    group = context.user_data['group']
    
    summary = f"""
✅ **សង្ខេបការបញ្ជាទិញ៖**

📘 សៀវភៅ៖ {product['name_kh']}
🔢 ចំនួន៖ {quantity}
💰 សរុប៖ ${total:.2f}

👤 ព័ត៌មាន៖
ឈ្មោះ៖ {name}
ក្រុម៖ {group}
ទូរស័ព្ទ៖ {phone if phone else 'មិនបានផ្តល់'}

💳 ចុចប៊ូតុងខាងក្រោមដើម្បីបង្កើតកូដទូទាត់ KHQR៖
"""
    
    keyboard = [
        [InlineKeyboardButton("💳 បង្កើតកូដ KHQR", callback_data="generate_khqr")],
        [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(summary, reply_markup=reply_markup)
    return PAYMENT

async def generate_khqr_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate REAL KHQR payment code"""
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
        
        # Show generating message
        await query.edit_message_text("🔄 **កំពុងបង្កើតកូដ KHQR...**\n\nសូមរង់ចាំ។")
        
        # Create order in database
        order_id, bill_number = db.create_order(
            user.id,
            user.username or "",
            name,
            group,
            phone,
            product['name_kh'],
            quantity,
            product['price'],
            total,
            product['currency']
        )
        
        print(f"📝 Created order #{order_id} with bill #{bill_number}")
        
        # Generate REAL KHQR
        qr_data, md5_hash, qr_image = payment_system.create_khqr_payment(
            order_id, bill_number, total, product['currency']
        )
        
        # Save KHQR data to database
        db.save_khqr_data(order_id, qr_data, md5_hash)
        
        # Store order ID and MD5 in context
        context.user_data['order_id'] = order_id
        context.user_data['md5_hash'] = md5_hash
        
        # Convert image to bytes for Telegram
        bio = BytesIO()
        qr_image.save(bio, 'PNG')
        bio.seek(0)
        
        payment_msg = f"""
💳 **ការទូទាត់តាម KHQR**

📘 សៀវភៅ៖ {product['name_kh']}
🔢 ចំនួន៖ {quantity}
💰 ចំនួនទឹកប្រាក់៖ **${total:.2f}**
📝 លេខការបញ្ជាទិញ៖ **#{order_id}**
🔗 លេខវិក័យប័ត្រ៖ {bill_number}

⬇️ **សូមស្កេនកូដ KHQR ខាងក្រោម៖**

⚠️ **របៀបទូទាត់៖**
1. បើកកម្មវិធី **Bakong**
2. ស្កេនកូដ KHQR
3. បញ្ជាក់ការទូទាត់
4. ប្រព័ន្ធនឹងផ្ទៀងផ្ទាត់ដោយស្វ័យប្រវត្តិ

⏳ **ការផ្ទៀងផ្ទាត់៖**
• ប្រព័ន្ធពិនិត្យរៀងរាល់ ៣០ វិនាទី
• អ្នកនឹងទទួលបានការបញ្ជាក់ដោយស្វ័យប្រវត្តិ
• មិនចាំបាច់ធ្វើអ្វីទៀតទេ
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 ពិនិត្យស្ថានភាព", callback_data=f"check_{md5_hash}")],
            [InlineKeyboardButton("📋 ការបញ្ជាទិញរបស់ខ្ញុំ", callback_data="my_orders")],
            [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_photo(
            photo=bio,
            caption=payment_msg,
            reply_markup=reply_markup
        )
        
        print(f"✅ KHQR sent for order #{order_id}")
        
        # Schedule auto-check in 30 seconds
        await asyncio.sleep(30)
        await auto_check_payment(update, context, md5_hash)
        
        return WAITING_PAYMENT
        
    except Exception as e:
        print(f"❌ Error generating KHQR: {str(e)}")
        
        error_msg = f"""
❌ **មិនអាចបង្កើតកូដ KHQR បាន**

កំហុស៖ {str(e)}

សូមព្យាយាមម្តងទៀត ឬទាក់ទងអ្នកគ្រប់គ្រង។
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 ព្យាយាមម្តងទៀត", callback_data="order")],
            [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(error_msg, reply_markup=reply_markup)
        return CHOOSING

async def auto_check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, md5_hash):
    """Auto-check payment after 30 seconds"""
    try:
        status = payment_system.check_payment_status(md5_hash)
        order = db.get_order_by_md5(md5_hash)
        
        if status == "PAID" and order:
            db.update_payment_status(md5_hash, 'paid')
            
            message = f"""
✅ **ការទូទាត់បានជោគជ័យ!**

អ្នកបានទូទាត់សម្រាប់ការបញ្ជាទិញ #{order['id']}
សូមអរគុណសម្រាប់ការទិញ!
"""
            try:
                await context.bot.send_message(chat_id=order['user_id'], text=message)
            except:
                pass
    except:
        pass

async def check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check payment status manually"""
    query = update.callback_query
    await query.answer()
    
    # Extract MD5 from callback data
    if query.data.startswith("check_"):
        md5_hash = query.data.replace("check_", "")
    else:
        md5_hash = context.user_data.get('md5_hash', '')
    
    if not md5_hash:
        await query.edit_message_text("❌ រកមិនឃើញលេខកូដទូទាត់ទេ។")
        return
    
    try:
        await query.edit_message_text("🔄 **កំពុងពិនិត្យស្ថានភាពទូទាត់...**")
        
        status = payment_system.check_payment_status(md5_hash)
        order = db.get_order_by_md5(md5_hash)
        
        if status == "PAID":
            db.update_payment_status(md5_hash, 'paid')
            
            message = f"""
🎉 **ការទូទាត់របស់អ្នកបានជោគជ័យ!**

🆔 លេខការបញ្ជាទិញ: #{order['id'] if order else 'N/A'}
💰 ចំនួនទឹកប្រាក់: ${order['total_amount'] if order else 0:.2f}
✅ ស្ថានភាព: បានទូទាត់

សូមអរគុណសម្រាប់ការទិញ!
"""
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
        
        await query.edit_message_text(message, reply_markup=reply_markup)
        
    except Exception as e:
        print(f"❌ Error checking payment: {e}")
        await query.edit_message_text("❌ មិនអាចពិនិត្យស្ថានភាពបាន។ សូមព្យាយាមម្តងទៀត។")

async def show_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's orders"""
    query = update.callback_query
    if query:
        await query.answer()
        user_id = query.from_user.id
    else:
        user_id = update.effective_user.id
    
    orders = db.get_user_orders(user_id)
    
    if not orders:
        msg = "📭 អ្នកមិនទាន់មានការបញ្ជាទិញណាមួយទេ។"
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return CHOOSING
    
    orders_msg = "📋 **ការបញ្ជាទិញរបស់អ្នក៖**\n\n"
    
    for order in orders:
        order_id, product_name, quantity, total, currency, status, created_at = order
        
        status_emoji = {
            'pending': '⏳',
            'paid': '✅',
            'expired': '❌'
        }.get(status, '❓')
        
        orders_msg += f"**#{order_id}** - {product_name}\n"
        orders_msg += f"{status_emoji} ស្ថានភាព: {status}\n"
        orders_msg += f"🔢 ចំនួន: {quantity}\n"
        orders_msg += f"💰 តម្លៃ: ${total:.2f}\n"
        orders_msg += f"📅 កាលបរិច្ឆេទ: {created_at[:10]}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("🛒 បញ្ជាទិញថ្មី", callback_data="order")],
        [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(orders_msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(orders_msg, reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "main_menu":
        await start(update, context)
        return CHOOSING
    elif data == "order":
        return await start_order(update, context)
    elif data == "my_orders":
        await show_my_orders(update, context)
        return CHOOSING
    elif data == "check_my_payments":
        await query.edit_message_text("🔄 កំពុងពិនិត្យទូទាត់ទាំងអស់...")
        await check_payments_background(context)
        await query.edit_message_text("✅ បានពិនិត្យទូទាត់ទាំងអស់!")
        return CHOOSING
    elif data.startswith("select_"):
        return await select_product(update, context)
    elif data == "generate_khqr":
        return await generate_khqr_payment(update, context)
    elif data.startswith("check_"):
        await check_payment_status(update, context)
        return WAITING_PAYMENT
    
    return CHOOSING

# ===================== MAIN FUNCTION =====================
def main():
    """Start the bot"""
    print("=" * 60)
    print("🤖 Telegram Book Shop Bot with REAL KHQR Payments")
    print("=" * 60)
    
    # Debug info
    print(f"🔧 DEBUG INFO:")
    print(f"   Python Version: {os.sys.version}")
    print(f"   KHQR Available: {KHQR_AVAILABLE}")
    print(f"   BAKONG_TOKEN: {'Set' if BAKONG_TOKEN else 'NOT SET'}")
    print(f"   BAKONG_ACCOUNT: {BAKONG_ACCOUNT}")
    
    if not KHQR_AVAILABLE:
        print("\n❌ ERROR: bakong_khqr library not found!")
        print("   Run: pip3 install bakong-khqr")
        print("   Or: pip3 install bakong-khqr[image] (for QR images)")
    
    if not BAKONG_TOKEN:
        print("\n⚠️  WARNING: No BAKONG_TOKEN!")
        print("   Get token from: https://api-bakong.nbc.gov.kh/register/")
        print("   Or use RBK Token: https://bakongrelay.com/")
    
    # Create application
    try:
        application = Application.builder().token(TOKEN).build()
        
        # Add job queue for background payment checks
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_repeating(check_payments_background, interval=30, first=10)
            print("✅ Background checker: Every 30 seconds")
        
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
        application.add_handler(CallbackQueryHandler(handle_callback))
        
        print("\n🚀 Bot is starting...")
        print("💳 Payment: REAL KHQR with auto MD5 verification")
        print("=" * 60)
        
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
