#!/usr/bin/env python3
"""
Fixed Telegram Book Shop Bot with proper KHQR integration
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

# Try to import bakong-khqr, but have fallback
try:
    from bakong_khqr import KHQR
    KHQR_AVAILABLE = True
    print("✅ KHQR library imported successfully")
except ImportError as e:
    print(f"⚠️  KHQR library not available: {e}")
    print("ℹ️  Install with: pip install bakong-khqr[image]")
    KHQR_AVAILABLE = False
except Exception as e:
    print(f"⚠️  Error importing KHQR: {e}")
    KHQR_AVAILABLE = False

# For fallback QR code
import qrcode
from PIL import Image

# ===================== CONFIGURATION =====================
TOKEN = os.getenv('TOKEN', '8502848831:AAG184UsX7tirVtPSCsAcjzPBN8_t4PQ42E')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '1273972944').split(',')]
BAKONG_TOKEN = os.getenv('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7ImlkIjoiM2VhMzg3OTRkMDJlNDZkYyJ9LCJpYXQiOjE3NjgyNzg0NzMsImV4cCI6MTc3NjA1NDQ3M30.gybhfjIvzzVCxbLUXHa5JPv6FaDtty1nEmZWBykfIrM', '')  # Your Bakong token

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
    PAYMENT, UPLOAD_SCREENSHOT
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
                khqr_data TEXT,
                khqr_md5 TEXT,
                screenshot_path TEXT,
                order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
    
    def add_order(self, user_id, username, full_name, group, phone, product_name, quantity, total):
        self.cursor.execute('''
            INSERT INTO orders 
            (user_id, username, full_name, student_group, phone, product_name, quantity, total_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, username, full_name, group, phone, product_name, quantity, total))
        order_id = self.cursor.lastrowid
        self.conn.commit()
        return order_id
    
    def update_khqr_data(self, order_id, khqr_data, khqr_md5):
        self.cursor.execute('''
            UPDATE orders SET khqr_data = ?, khqr_md5 = ? WHERE id = ?
        ''', (khqr_data, khqr_md5, order_id))
        self.conn.commit()
    
    def update_screenshot(self, order_id, screenshot_path):
        self.cursor.execute('''
            UPDATE orders SET payment_status = 'uploaded', screenshot_path = ? WHERE id = ?
        ''', (screenshot_path, order_id))
        self.conn.commit()
    
    def get_user_orders(self, user_id):
        self.cursor.execute('SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC', (user_id,))
        return self.cursor.fetchall()
    
    def get_order(self, order_id):
        self.cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
        return self.cursor.fetchone()

db = SimpleDB()

# ===================== KHQR PAYMENT GENERATION =====================
class KHQRPayment:
    def __init__(self):
        self.token = BAKONG_TOKEN
        self.khqr_instance = None
        
        if KHQR_AVAILABLE and self.token:
            try:
                self.khqr_instance = KHQR(self.token)
                print("✅ KHQR instance created successfully")
            except Exception as e:
                print(f"⚠️  Failed to create KHQR instance: {e}")
                self.khqr_instance = None
    
    def generate_real_khqr(self, order_id: int, amount: float, phone: str = "85512345678") -> Tuple[str, str, Image.Image]:
        """Generate real KHQR code using bakong-khqr library"""
        try:
            if not self.khqr_instance:
                raise Exception("KHQR not initialized. Check BAKONG_TOKEN.")
            
            print(f"🔧 Generating KHQR for order #{order_id}, amount: ${amount}")
            
            # Generate QR data
            qr_data = self.khqr_instance.create_qr(
                bank_account='sin_soktep@bkrt',  # ⚠️ CHANGE THIS to your actual Bakong account
                merchant_name='Pu-Tephh M3',
                merchant_city='Phnom Penh',
                amount=amount,
                currency='USD',
                store_label='Telegram Book Shop',
                phone_number=phone,
                bill_number=f'BOOK{order_id:06d}',
                terminal_label=f'Order_{order_id}',
                static=False
            )
            
            print(f"✅ KHQR data generated: {qr_data[:50]}...")
            
            # Generate MD5 hash
            md5_hash = self.khqr_instance.generate_md5(qr_data)
            print(f"✅ MD5 hash: {md5_hash}")
            
            # Generate QR image
            try:
                qr_image_path = self.khqr_instance.qr_image(qr_data, output_path=f"payment_images/khqr_{order_id}.png")
                qr_image = Image.open(qr_image_path)
                print(f"✅ QR image saved: {qr_image_path}")
            except Exception as img_error:
                print(f"⚠️  Could not generate KHQR image: {img_error}")
                # Create simple QR as fallback
                qr_image = self.create_simple_qr(qr_data, order_id, amount)
            
            return qr_data, md5_hash, qr_image
            
        except Exception as e:
            print(f"❌ KHQR generation error: {e}")
            # Fallback to simple QR
            return self.generate_fallback_qr(order_id, amount)
    
    def create_simple_qr(self, qr_data: str, order_id: int, amount: float) -> Image.Image:
        """Create a simple QR code from the KHQR data"""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="white")
    
    def generate_fallback_qr(self, order_id: int, amount: float) -> Tuple[str, str, Image.Image]:
        """Generate fallback QR code when KHQR fails"""
        print(f"🔄 Using fallback QR for order #{order_id}")
        
        # Create simple payment info
        payment_info = f"""
        Book Shop Payment
        Order: #{order_id}
        Amount: ${amount:.2f}
        Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}
        Status: Pending
        Please upload screenshot after payment.
        """
        
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(payment_info)
        qr.make(fit=True)
        
        qr_image = qr.make_image(fill_color="black", back_color="white")
        
        # Create simple MD5-like hash
        md5_hash = hashlib.md5(f"order_{order_id}_{amount}_{datetime.now().timestamp()}".encode()).hexdigest()[:16]
        
        return payment_info, f"FALLBACK_{md5_hash}", qr_image

# Initialize payment handler
khqr_payment = KHQRPayment()

# ===================== BOT HANDLERS =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    # Check if KHQR is available
    khqr_status = "✅" if KHQR_AVAILABLE and BAKONG_TOKEN else "❌"
    
    welcome_msg = f"""👋 សួស្តី {user.first_name}!

📚 **ស្វាគមន៍មកកាន់ហាងសៀវភៅសម្រាប់មិត្តរួមថ្នាក់**

💳 **ប្រព័ន្ធទូទាត់:** {khqr_status} KHQR
    
**សៀវភៅទាំងអស់៖**
1. សៀវភៅគណិតវិទ្យា - $1.70
2. Human & Society - $1.99
3. គោលការណ៍អាជីវកម្ម - $1.99
4. សៀវភៅកុំព្យូទ័រ - $2.50
"""
    
    keyboard = [
        [InlineKeyboardButton("📚 មើលសៀវភៅ", callback_data="catalog")],
        [InlineKeyboardButton("🛒 បញ្ជាទិញឥឡូវនេះ", callback_data="order")],
        [InlineKeyboardButton("📋 ការបញ្ជាទិញរបស់ខ្ញុំ", callback_data="my_orders")],
        [InlineKeyboardButton("⚙️ ពិនិត្យស្ថានភាព", callback_data="check_status")]
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
        "បញ្ចូលលេខទូរស័ព្ទ ឬសរសេរ 'skip' ដើម្បីលោត៖"
    )
    return GET_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get phone number"""
    phone = update.message.text.strip()
    
    if phone.lower() == 'skip':
        phone = "85500000000"  # Default phone
    
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
ទូរស័ព្ទ៖ {phone if phone != "85500000000" else 'មិនបានផ្តល់'}

💳 ចុចប៊ូតុងខាងក្រោមដើម្បីបង្កើតកូដទូទាត់៖
"""
    
    keyboard = [
        [InlineKeyboardButton("💳 បង្កើតកូដ KHQR", callback_data="generate_khqr")],
        [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(summary, reply_markup=reply_markup)
    return PAYMENT

async def generate_khqr_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate KHQR code for payment - FIXED VERSION"""
    query = update.callback_query
    await query.answer()
    
    try:
        user = update.effective_user
        product = context.user_data['product']
        quantity = context.user_data['quantity']
        total = context.user_data['total']
        name = context.user_data['name']
        group = context.user_data['group']
        phone = context.user_data.get('phone', '85500000000')
        
        # Show generating message
        await query.edit_message_text("🔄 **កំពុងបង្កើតកូដ KHQR...**\n\nសូមរង់ចាំបន្តិច។")
        
        # Save order to database first
        order_id = db.add_order(
            user.id,
            user.username or "",
            name,
            group,
            phone,
            product['name_kh'],
            quantity,
            total
        )
        
        print(f"📝 Created order #{order_id} for user {user.id}")
        
        # Generate KHQR
        print(f"🔧 Starting KHQR generation for order #{order_id}")
        qr_data, md5_hash, qr_image = khqr_payment.generate_real_khqr(order_id, total, phone)
        
        # Save KHQR data to database
        db.update_khqr_data(order_id, qr_data, md5_hash)
        
        # Store order ID in context
        context.user_data['order_id'] = order_id
        
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

⬇️ **សូមស្កេនកូដ QR ខាងក្រោម៖**

⚠️ **របៀបទូទាត់៖**
1. បើកកម្មវិធី **Bakong**
2. ស្កេនកូដ QR
3. បញ្ជាក់ការទូទាត់
4. **ថតរូបភាពអេក្រង់**
5. ផ្ញើរូបភាពមកទីនេះ

📸 **បន្ទាប់ពីទូទាត់ សូមផ្ញើរូបភាពមកខ្ញុំ!**
"""
        
        # Add debug info if using fallback
        if md5_hash.startswith("FALLBACK_"):
            payment_msg += "\n\n⚠️ **សំគាល់៖** ប្រើប្រព័ន្ធទូទាត់ជំនួស។"
        
        keyboard = [
            [InlineKeyboardButton("📸 ផ្ញើរូបភាពការទូទាត់", callback_data="upload_screenshot")],
            [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_photo(
            photo=bio,
            caption=payment_msg,
            reply_markup=reply_markup
        )
        
        print(f"✅ Successfully sent KHQR for order #{order_id}")
        
        return UPLOAD_SCREENSHOT
        
    except Exception as e:
        print(f"❌ Error in generate_khqr_payment: {e}")
        import traceback
        traceback.print_exc()
        
        # Send error message to user
        error_msg = f"""
❌ **មានបញ្ហាក្នុងការបង្កើតកូដទូទាត់**

កំហុស៖ {str(e)}

សូម៖
1. ព្យាយាមម្តងទៀត
2. ទាក់ទងអ្នកគ្រប់គ្រង
3. ប្រើប្រព័ន្ធទូទាត់ផ្សេង
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 ព្យាយាមម្តងទៀត", callback_data="order")],
            [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await query.edit_message_text(error_msg, reply_markup=reply_markup)
        else:
            await update.message.reply_text(error_msg, reply_markup=reply_markup)
        
        return CHOOSING

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded screenshot"""
    if not update.message or not update.message.photo:
        await update.message.reply_text("❌ សូមផ្ញើរូបភាពអេក្រង់។")
        return UPLOAD_SCREENSHOT
    
    try:
        # Get the photo
        photo = update.message.photo[-1]
        file = await photo.get_file()
        
        # Save screenshot
        order_id = context.user_data.get('order_id', 'unknown')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"payment_images/screenshot_{order_id}_{timestamp}.jpg"
        
        await file.download_to_drive(filename)
        
        # Update order status
        if 'order_id' in context.user_data:
            db.update_screenshot(context.user_data['order_id'], filename)
        
        # Notify user
        await update.message.reply_text(
            "✅ **រូបភាពត្រូវបានទទួល!**\n\n"
            "អ្នកគ្រប់គ្រងនឹងពិនិត្យរូបភាពការទូទាត់របស់អ្នក។\n"
            "យើងនឹងទំនាក់ទំនងអ្នកវិញក្នុងពេលឆាប់ៗនេះ។\n\n"
            "🙏 សូមអរគុណ!"
        )
        
        # Notify admins
        order_info = f"""
📢 **ការបញ្ជាទិញថ្មីត្រូវបានផ្ញើរូបភាព!**

🆔 លេខការបញ្ជាទិញ: #{order_id}
👤 អ្នកទិញ: {context.user_data.get('name', 'N/A')}
🎓 ក្រុម: {context.user_data.get('group', 'N/A')}
📘 សៀវភៅ: {context.user_data.get('product', {}).get('name_kh', 'N/A')}
💰 ចំនួនទឹកប្រាក់: ${context.user_data.get('total', 0):.2f}
"""
        
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=order_info)
                
                # Send screenshot
                with open(filename, 'rb') as photo_file:
                    await context.bot.send_photo(
                        chat_id=admin_id,
                        photo=photo_file,
                        caption=f"📸 រូបភាពសម្រាប់ការបញ្ជាទិញ #{order_id}"
                    )
                
            except Exception as e:
                print(f"Failed to notify admin {admin_id}: {e}")
        
        # Clear context
        context.user_data.clear()
        
        keyboard = [
            [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")],
            [InlineKeyboardButton("📋 ការបញ្ជាទិញរបស់ខ្ញុំ", callback_data="my_orders")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text("អ្វីបន្ទាប់?", reply_markup=reply_markup)
        return CHOOSING
        
    except Exception as e:
        print(f"Error handling screenshot: {e}")
        await update.message.reply_text("❌ មានបញ្ហាក្នុងការទទួលរូបភាព។")
        return UPLOAD_SCREENSHOT

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "main_menu":
        await start(update, context)
        return CHOOSING
    elif data == "catalog":
        await show_catalog(update, context)
        return CHOOSING
    elif data == "order":
        return await start_order(update, context)
    elif data == "generate_khqr":
        return await generate_khqr_payment(update, context)
    elif data == "upload_screenshot":
        await query.message.reply_text("📸 សូមផ្ញើរូបភាពអេក្រង់ការទូទាត់៖")
        return UPLOAD_SCREENSHOT
    
    return CHOOSING

# ===================== MAIN FUNCTION =====================
def main():
    """Start the bot"""
    print("=" * 50)
    print("🤖 Telegram Book Shop Bot")
    print("=" * 50)
    
    # Check requirements
    print(f"📦 KHQR Available: {KHQR_AVAILABLE}")
    print(f"🔑 BAKONG_TOKEN set: {'✅' if BAKONG_TOKEN else '❌'}")
    print(f"🤖 TELEGRAM_TOKEN set: {'✅' if TOKEN and TOKEN != 'YOUR_BOT_TOKEN_HERE' else '❌'}")
    
    if not KHQR_AVAILABLE:
        print("\n⚠️  WARNING: bakong-khqr library not installed!")
        print("   Install with: pip install bakong-khqr[image]")
        print("   Or using fallback QR system")
    
    if not BAKONG_TOKEN:
        print("\n⚠️  WARNING: BAKONG_TOKEN not set!")
        print("   Get token from: https://api-bakong.nbc.gov.kh/register/")
        print("   Or use RBK Token from: https://bakongrelay.com/")
        print("   Will use fallback system")
    
    # Create application
    try:
        application = Application.builder().token(TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CallbackQueryHandler(handle_callback))
        
        # Message handlers
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_quantity), group=1)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_name), group=2)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_group), group=3)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone), group=4)
        application.add_handler(MessageHandler(filters.PHOTO, handle_screenshot), group=5)
        
        print("\n🚀 Bot is starting...")
        print("📚 Products loaded:", len(PRODUCTS))
        print("👑 Admin IDs:", ADMIN_IDS)
        
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
