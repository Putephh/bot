#!/usr/bin/env python3
"""
Complete Telegram Book Shop Bot for Railway
with KHQR Payment & Screenshot Verification
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
from telegram.constants import ParseMode

# For QR code generation
import qrcode
from PIL import Image

# KHQR SDK
try:
    import bakong_khqr
    KHQR_AVAILABLE = True
except ImportError:
    KHQR_AVAILABLE = False
    print("⚠️  KHQR SDK not installed. Using simulated payment.")

# ===================== CONFIGURATION =====================
TOKEN = os.getenv('TOKEN', '8502848831:AAG184UsX7tirVtPSCsAcjzPBN8_t4PQ42E')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '1273972944').split(',')]

# Create necessary directories
os.makedirs('payment_images', exist_ok=True)

# Product catalog with Khmer names
PRODUCTS = {
    "math": {
        "name_kh": "សៀវភៅគណិតវិទ្យា",
        "name_en": "Math Book",
        "price": 1.70,
        "description_kh": "សៀវភៅគណិតវិទ្យាសម្រាប់និស្សិត",
        "currency": "USD"
    },
    "human": {
        "name_kh": "Human & Society",
        "name_en": "Human & Society",
        "price": 1.99,
        "description_kh": "សៀវភៅមនុស្ស និងសង្គម",
        "currency": "USD"
    },
    "business": {
        "name_kh": "គោលការណ៍អាជីវកម្ម",
        "name_en": "Principle of Business",
        "price": 1.99,
        "description_kh": "គោលការណ៍គ្រឹះនៃអាជីវកម្ម",
        "currency": "USD"
    },
    "computer": {
        "name_kh": "សៀវភៅកុំព្យូទ័រ",
        "name_en": "Computer Book",
        "price": 2.50,
        "description_kh": "សៀវភៅវិទ្យាសាស្ត្រកុំព្យូទ័រ",
        "currency": "USD"
    }
}

# Conversation states
(
    CHOOSING, SELECT_PRODUCT, GET_QUANTITY, 
    GET_NAME, GET_GROUP, GET_PHONE, 
    PAYMENT, UPLOAD_SCREENSHOT, 
    ADMIN_PANEL, ADMIN_VIEW_ORDER, ADMIN_CONTACT
) = range(10)

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===================== DATABASE =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('bookshop.db', check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.create_tables()
    
    def create_tables(self):
        # Orders table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                student_group TEXT,
                phone TEXT,
                product_id TEXT,
                product_name TEXT,
                quantity INTEGER,
                price REAL,
                total_amount REAL,
                payment_status TEXT DEFAULT 'pending',
                payment_method TEXT DEFAULT 'KHQR',
                transaction_id TEXT,
                screenshot_path TEXT,
                order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                admin_notes TEXT
            )
        ''')
        
        # Products table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name_kh TEXT,
                name_en TEXT,
                price REAL,
                description_kh TEXT,
                description_en TEXT,
                currency TEXT,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # Insert default products
        for pid, product in PRODUCTS.items():
            self.cursor.execute('''
                INSERT OR IGNORE INTO products 
                (id, name_kh, name_en, price, description_kh, description_en, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                pid, product['name_kh'], product['name_en'], product['price'],
                product['description_kh'], 'description_en' in product and product['description_en'] or '',
                product['currency']
            ))
        
        self.conn.commit()
    
    def add_order(self, order_data: Dict) -> int:
        self.cursor.execute('''
            INSERT INTO orders 
            (user_id, username, full_name, student_group, phone, 
             product_id, product_name, quantity, price, total_amount,
             payment_status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            order_data['user_id'],
            order_data.get('username', ''),
            order_data['full_name'],
            order_data['student_group'],
            order_data.get('phone', ''),
            order_data['product_id'],
            order_data['product_name'],
            order_data['quantity'],
            order_data['price'],
            order_data['total_amount'],
            order_data.get('payment_status', 'pending'),
            order_data.get('notes', '')
        ))
        order_id = self.cursor.lastrowid
        self.conn.commit()
        return order_id
    
    def update_order(self, order_id: int, updates: Dict):
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values())
        values.append(order_id)
        
        self.cursor.execute(f'''
            UPDATE orders SET {set_clause} WHERE id = ?
        ''', values)
        self.conn.commit()
    
    def get_orders(self, status: str = None, limit: int = 100) -> List[Dict]:
        if status:
            self.cursor.execute('''
                SELECT * FROM orders 
                WHERE payment_status = ? 
                ORDER BY order_date DESC LIMIT ?
            ''', (status, limit))
        else:
            self.cursor.execute('SELECT * FROM orders ORDER BY order_date DESC LIMIT ?', (limit,))
        return [dict(row) for row in self.cursor.fetchall()]
    
    def get_user_orders(self, user_id: int) -> List[Dict]:
        self.cursor.execute('SELECT * FROM orders WHERE user_id = ? ORDER BY order_date DESC', (user_id,))
        return [dict(row) for row in self.cursor.fetchall()]
    
    def get_order(self, order_id: int) -> Dict:
        self.cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
        row = self.cursor.fetchone()
        return dict(row) if row else None
    
    def get_pending_orders(self) -> List[Dict]:
        self.cursor.execute('''
            SELECT * FROM orders 
            WHERE payment_status IN ('pending', 'uploaded') 
            ORDER BY order_date DESC
        ''')
        return [dict(row) for row in self.cursor.fetchall()]

db = Database()

# ===================== KHQR PAYMENT =====================
class KHQRPayment:
    def __init__(self):
        self.merchant_account = "sin_soktep@bkrt"
        self.merchant_name = "Pu-Tephh Mnus Sahav"
        self.merchant_city = "Phnom Penh"
    
    def generate_khqr_code(self, amount: float, order_id: int) -> Tuple[str, str, Image.Image]:
        """Generate KHQR code and image"""
        try:
            if KHQR_AVAILABLE:
                # Real KHQR generation
                individual_info = bakong_khqr.IndividualInfo(
                    accountId=self.merchant_account,
                    merchantName=self.merchant_name,
                    merchantCity=self.merchant_city,
                    currency="USD",
                    amount=amount
                )
                
                khqr_response = bakong_khqr.BakongKHQR.generateIndividual(individual_info)
                
                if khqr_response.status.code == 0:
                    qr_data = khqr_response.data.qr
                    transaction_id = f"KHQR_{order_id}_{hashlib.md5(qr_data.encode()).hexdigest()[:8]}"
                    
                    # Generate QR code image
                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=10,
                        border=4,
                    )
                    qr.add_data(qr_data)
                    qr.make(fit=True)
                    
                    img = qr.make_image(fill_color="black", back_color="white")
                    return qr_data, transaction_id, img
            else:
                # Fallback: Generate simple QR code
                qr_data = f"KHQR Payment\nOrder: #{order_id}\nAmount: ${amount:.2f}\nMerchant: {self.merchant_name}\nScan with Bakong App"
                transaction_id = f"SIM_{order_id}_{int(datetime.now().timestamp())}"
                
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=10,
                    border=4,
                )
                qr.add_data(qr_data)
                qr.make(fit=True)
                
                img = qr.make_image(fill_color="black", back_color="white")
                return qr_data, transaction_id, img
                
        except Exception as e:
            logger.error(f"Error generating KHQR: {e}")
            # Generate fallback QR
            qr_data = f"Order #{order_id} - ${amount:.2f}"
            transaction_id = f"ERR_{order_id}"
            
            qr = qrcode.QRCode()
            qr.add_data(qr_data)
            img = qr.make_image()
            return qr_data, transaction_id, img

khqr_payment = KHQRPayment()

# ===================== BOT HANDLERS =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    welcome_msg = f"""👋 សួស្តី {user.first_name}!

📚 **ស្វាគមន៍មកកាន់ហាងសៀវភៅសម្រាប់មិត្តរួមថ្នាក់**

🏪 **របៀបបញ្ជាទិញ៖**
1. ជ្រើសរើសសៀវភៅ
2. បញ្ចូលចំនួន
3. បំពេញព័ត៌មាន
4. ទូទាត់តាម KHQR
5. ថតរូបភាពការទូទាត់
6. រង់ចាំការបញ្ជាក់ពីអ្នកគ្រប់គ្រង

📱 **បញ្ជា៖**
/start - ចាប់ផ្តើម
/catalog - មើលសៀវភៅ
/order - បញ្ជាទិញ
/myorders - ការបញ្ជាទិញរបស់ខ្ញុំ
/help - ជំនួយ
"""
    
    keyboard = [
        [InlineKeyboardButton("📚 មើលសៀវភៅ", callback_data="catalog")],
        [InlineKeyboardButton("🛒 បញ្ជាទិញថ្មី", callback_data="order")],
        [InlineKeyboardButton("📋 ការបញ្ជាទិញរបស់ខ្ញុំ", callback_data="my_orders")],
        [InlineKeyboardButton("ℹ️ ជំនួយ", callback_data="help")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(welcome_msg, reply_markup=reply_markup)
    
    return CHOOSING

async def show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show book catalog"""
    query = update.callback_query
    if query:
        await query.answer()
    
    catalog_msg = "📚 **សៀវភៅទាំងអស់៖**\n\n"
    
    for i, (pid, product) in enumerate(PRODUCTS.items(), 1):
        catalog_msg += f"{i}. **{product['name_kh']}**\n"
        catalog_msg += f"   💰 តម្លៃ: ${product['price']:.2f}\n"
        catalog_msg += f"   📖 {product['description_kh']}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("🛒 បញ្ជាទិញឥឡូវនេះ", callback_data="order")],
        [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(catalog_msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(catalog_msg, reply_markup=reply_markup)

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
    
    keyboard.append([InlineKeyboardButton("❌ បោះបង់", callback_data="cancel")])
    
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
        "(សរសេរលេខពី ១ ទៅ ១០)៖"
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
        
        # Start collecting information
        await update.message.reply_text(
            f"✅ **ចំនួន៖** {quantity}\n"
            f"💰 **សរុប៖** ${total:.2f}\n\n"
            "📝 **សូមបញ្ចូលព័ត៌មានរបស់អ្នក៖**\n"
            "តើ **ឈ្មោះពេញ** របស់អ្នកគឺជាអ្វី?"
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
        "(ឧទាហរណ៍៖ Civil M3, Civil M4)៖"
    )
    return GET_GROUP

async def get_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get student group"""
    group = update.message.text.strip()
    
    if not group:
        await update.message.reply_text("❌ សូមបញ្ចូលក្រុមសិក្សា។")
        return GET_GROUP
    
    context.user_data['group'] = group
    
    # Ask for phone (optional)
    keyboard = [[
        KeyboardButton("📱 ចែករំលែកលេខទូរស័ព្ទ", request_contact=True),
        KeyboardButton("លុបចោលលេខទូរស័ព្ទ")
    ]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        f"✅ **ក្រុម៖** {group}\n\n"
        "📱 **លេខទូរស័ព្ទ (មិនចាំបាច់)៖**\n"
        "ចុចប៊ូតុងខាងក្រោមដើម្បីចែករំលែក ឬសរសេរដោយដៃ។",
        reply_markup=reply_markup
    )
    return GET_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get phone number"""
    phone = ""
    
    if update.message.contact:
        phone = update.message.contact.phone_number
    elif update.message.text and update.message.text != "លុបចោលលេខទូរស័ព្ទ":
        phone = update.message.text.strip()
    
    context.user_data['phone'] = phone
    
    # Show summary and proceed to payment
    product = context.user_data['product']
    quantity = context.user_data['quantity']
    total = context.user_data['total']
    name = context.user_data['name']
    group = context.user_data['group']
    
    summary = f"""
✅ **សង្ខេបការបញ្ជាទិញ៖**

📘 **សៀវភៅ៖** {product['name_kh']}
🔢 **ចំនួន៖** {quantity}
💰 **សរុប៖** ${total:.2f}

👤 **ព័ត៌មានអ្នកទិញ៖**
ឈ្មោះ៖ {name}
ក្រុម៖ {group}
ទូរស័ព្ទ៖ {phone if phone else 'មិនបានផ្តល់'}

💳 **បន្តទៅការទូទាត់?**
"""
    
    keyboard = [
        [InlineKeyboardButton("💳 បង្កើតកូដ KHQR", callback_data="generate_khqr")],
        [InlineKeyboardButton("❌ បោះបង់", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        summary, 
        reply_markup=reply_markup,
        reply_to_message_id=update.message.message_id
    )
    return PAYMENT

async def generate_khqr_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate KHQR code for payment"""
    query = update.callback_query
    await query.answer()
    
    # Save order to database first
    user = update.effective_user
    product = context.user_data['product']
    product_id = context.user_data['product_id']
    quantity = context.user_data['quantity']
    total = context.user_data['total']
    name = context.user_data['name']
    group = context.user_data['group']
    phone = context.user_data.get('phone', '')
    
    # Create order in database
    order_data = {
        'user_id': user.id,
        'username': user.username or '',
        'full_name': name,
        'student_group': group,
        'phone': phone,
        'product_id': product_id,
        'product_name': product['name_kh'],
        'quantity': quantity,
        'price': product['price'],
        'total_amount': total,
        'payment_status': 'pending',
        'notes': f"ការបញ្ជាទិញតាម KHQR"
    }
    
    order_id = db.add_order(order_data)
    
    # Generate KHQR code
    qr_data, transaction_id, qr_image = khqr_payment.generate_khqr_code(total, order_id)
    
    # Update order with transaction ID
    db.update_order(order_id, {'transaction_id': transaction_id})
    
    # Save QR code image
    qr_path = f"payment_images/qr_{order_id}.png"
    qr_image.save(qr_path)
    
    # Store order ID in context
    context.user_data['order_id'] = order_id
    context.user_data['transaction_id'] = transaction_id
    
    # Convert QR image to send via Telegram
    bio = BytesIO()
    qr_image.save(bio, 'PNG')
    bio.seek(0)
    
    payment_msg = f"""
💳 **ការទូទាត់តាម KHQR**

📘 សៀវភៅ៖ {product['name_kh']}
🔢 ចំនួន៖ {quantity}
💰 ចំនួនទឹកប្រាក់៖ **${total:.2f}**
📝 លេខការបញ្ជាទិញ៖ **#{order_id}**
🔗 លេខដឹកជញ្ជូន៖ {transaction_id}

⬇️ **សូមស្កេនកូដ QR ខាងក្រោម៖**

⚠️ **របៀបទូទាត់៖**
1. បើកកម្មវិធី **Bakong** នៅលើទូរស័ព្ទរបស់អ្នក
2. ស្កេនកូដ QR ខាងលើ
3. បញ្ជាក់ការទូទាត់
4. **ថតរូបភាពអេក្រង់** នៃការទូទាត់ដែលបានជោគជ័យ
5. បញ្ចូលរូបភាពទៅក្នុងបូតុងនេះ

📸 **បន្ទាប់ពីទូទាត់ សូមផ្ញើរូបភាពអេក្រង់មកខ្ញុំ!**
"""
    
    keyboard = [
        [InlineKeyboardButton("📸 ផ្ញើរូបភាពការទូទាត់", callback_data="upload_screenshot")],
        [InlineKeyboardButton("❌ បោះបង់ការបញ្ជាទិញ", callback_data="cancel_order")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send QR code image
    await query.message.reply_photo(
        photo=bio,
        caption=payment_msg,
        reply_markup=reply_markup
    )
    
    return UPLOAD_SCREENSHOT

async def request_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Request payment screenshot"""
    query = update.callback_query
    await query.answer()
    
    await query.message.reply_text(
        "📸 **សូមផ្ញើរូបភាពអេក្រង់ការទូទាត់៖**\n\n"
        "1. បើកកម្មវិធី Bakong របស់អ្នក\n"
        "2. ស្កេនកូដ QR\n"
        "3. បញ្ជាក់ការទូទាត់\n"
        "4. ថតរូបភាពអេក្រង់នៃការទូទាត់ដែលបានជោគជ័យ\n"
        "5. ផ្ញើរូបភាពមកទីនេះ\n\n"
        "⚠️ **យើងនឹងពិនិត្យរូបភាពរបស់អ្នកជាមុនសិន មុនពេលយកចិត្តទុកដាក់។**"
    )
    
    return UPLOAD_SCREENSHOT

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded screenshot"""
    if not update.message or not update.message.photo:
        await update.message.reply_text("❌ សូមផ្ញើរូបភាពអេក្រង់ការទូទាត់។")
        return UPLOAD_SCREENSHOT
    
    # Get the highest resolution photo
    photo = update.message.photo[-1]
    file = await photo.get_file()
    
    # Generate unique filename
    order_id = context.user_data.get('order_id', 'unknown')
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"payment_images/screenshot_{order_id}_{timestamp}.jpg"
    
    # Download and save the photo
    await file.download_to_drive(filename)
    
    # Update order status
    if 'order_id' in context.user_data:
        db.update_order(context.user_data['order_id'], {
            'payment_status': 'uploaded',
            'screenshot_path': filename
        })
    
    # Notify user
    await update.message.reply_text(
        "✅ **រូបភាពត្រូវបានទទួល!**\n\n"
        "អ្នកគ្រប់គ្រងនឹងពិនិត្យរូបភាពការទូទាត់របស់អ្នកជាមុនសិន។\n"
        "យើងនឹងទំនាក់ទំនងអ្នកវិញក្នុងពេលឆាប់ៗនេះ។\n\n"
        "🙏 សូមអរគុណសម្រាប់ការរង់ចាំ!"
    )
    
    # Notify all admins
    order_info = f"""
📢 **ការបញ្ជាទិញថ្មីត្រូវបានផ្ញើរូបភាព!**

🆔 លេខការបញ្ជាទិញ: #{order_id if 'order_id' in context.user_data else 'N/A'}
👤 អ្នកទិញ: {context.user_data.get('name', 'N/A')}
🎓 ក្រុម: {context.user_data.get('group', 'N/A')}
📱 ទូរស័ព្ទ: {context.user_data.get('phone', 'មិនបានផ្តល់')}
📘 សៀវភៅ: {context.user_data.get('product', {}).get('name_kh', 'N/A')}
💰 ចំនួនទឹកប្រាក់: ${context.user_data.get('total', 0):.2f}

សូមពិនិត្យរូបភាព និងធ្វើការបញ្ជាក់។
"""
    
    for admin_id in ADMIN_IDS:
        try:
            # Send order info
            await context.bot.send_message(
                chat_id=admin_id,
                text=order_info
            )
            
            # Send the screenshot
            with open(filename, 'rb') as photo_file:
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=photo_file,
                    caption=f"📸 រូបភាពការទូទាត់សម្រាប់ការបញ្ជាទិញ #{order_id}"
                )
            
            # Send admin actions
            keyboard = [
                [
                    InlineKeyboardButton("✅ យល់ព្រម", callback_data=f"approve_{order_id}"),
                    InlineKeyboardButton("❌ បដិសេធ", callback_data=f"reject_{order_id}")
                ],
                [InlineKeyboardButton("📞 ទាក់ទងអ្នកទិញ", callback_data=f"contact_{order_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"⚙️ **សកម្មភាពសម្រាប់ការបញ្ជាទិញ #{order_id}:**",
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")
    
    # Clear user data
    context.user_data.clear()
    
    keyboard = [
        [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")],
        [InlineKeyboardButton("📋 មើលការបញ្ជាទិញរបស់ខ្ញុំ", callback_data="my_orders")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "អ្នកអាចត្រឡប់ទៅម单ដើម ឬមើលស្ថានភាពការបញ្ជាទិញរបស់អ្នក៖",
        reply_markup=reply_markup
    )
    
    return CHOOSING

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
    
    orders_msg = f"📋 **ការបញ្ជាទិញរបស់អ្នក ({len(orders)})៖**\n\n"
    
    status_emojis = {
        'pending': '⏳',
        'uploaded': '📸',
        'approved': '✅',
        'rejected': '❌',
        'completed': '🎉'
    }
    
    for order in orders[:10]:  # Show first 10
        emoji = status_emojis.get(order['payment_status'], '❓')
        orders_msg += f"**#{order['id']}** - {order['product_name']}\n"
        orders_msg += f"{emoji} ស្ថានភាព: {order['payment_status']}\n"
        orders_msg += f"🔢 ចំនួន: {order['quantity']}\n"
        orders_msg += f"💰 តម្លៃ: ${order['total_amount']:.2f}\n"
        orders_msg += f"📅 កាលបរិច្ឆេទ: {order['order_date'][:10]}\n\n"
    
    if len(orders) > 10:
        orders_msg += f"... និង {len(orders) - 10} ការបញ្ជាទិញផ្សេងទៀត\n"
    
    keyboard = [
        [InlineKeyboardButton("🛒 បញ្ជាទិញថ្មី", callback_data="order")],
        [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(orders_msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(orders_msg, reply_markup=reply_markup)

# ===================== ADMIN FUNCTIONS =====================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ អ្នកមិនមានសិទ្ធិប្រើប្រាស់ការគ្រប់គ្រងទេ។")
        return CHOOSING
    
    # Get statistics
    all_orders = db.get_orders()
    pending_count = len([o for o in all_orders if o['payment_status'] in ['pending', 'uploaded']])
    
    admin_msg = f"""
👑 **ផ្ទាំងគ្រប់គ្រង**

📊 **ស្ថិតិ៖**
📋 សរុបការបញ្ជាទិញ: {len(all_orders)}
⏳ កំពុងរង់ចាំការពិនិត្យ: {pending_count}
✅ បានយល់ព្រម: {len([o for o in all_orders if o['payment_status'] == 'approved'])}

⚙️ **សកម្មភាព៖**
"""
    
    keyboard = [
        [InlineKeyboardButton("📸 មើលការបញ្ជាទិញដែលត្រូវពិនិត្យ", callback_data="admin_pending")],
        [InlineKeyboardButton("📋 មើលការបញ្ជាទិញទាំងអស់", callback_data="admin_all")],
        [InlineKeyboardButton("📊 ស្ថិតិលម្អិត", callback_data="admin_stats")],
        [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(admin_msg, reply_markup=reply_markup)
    return ADMIN_PANEL

async def admin_pending_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show pending orders for admin"""
    query = update.callback_query
    await query.answer()
    
    pending_orders = db.get_pending_orders()
    
    if not pending_orders:
        await query.edit_message_text("✅ គ្មានការបញ្ជាទិញណាដែលត្រូវពិនិត្យទេ។")
        return ADMIN_PANEL
    
    orders_msg = f"📸 **ការបញ្ជាទិញដែលត្រូវពិនិត្យ ({len(pending_orders)})៖**\n\n"
    
    for order in pending_orders[:5]:
        orders_msg += f"**#{order['id']}** - {order['product_name']}\n"
        orders_msg += f"👤 {order['full_name']} ({order['student_group']})\n"
        orders_msg += f"💰 ${order['total_amount']:.2f} | {order['payment_status']}\n"
        orders_msg += f"📅 {order['order_date'][:10]}\n"
        
        # Add action buttons
        orders_msg += f"[✅](t.me/{context.bot.username}?start=approve_{order['id']}) "
        orders_msg += f"[❌](t.me/{context.bot.username}?start=reject_{order['id']}) "
        orders_msg += f"[📞](t.me/{context.bot.username}?start=contact_{order['id']})\n\n"
    
    keyboard = []
    for order in pending_orders[:3]:
        keyboard.append([
            InlineKeyboardButton(
                f"#{order['id']} - {order['full_name']} - ${order['total_amount']:.2f}",
                callback_data=f"admin_view_{order['id']}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("🔄 ធ្វើបច្ចុប្បន្នភាព", callback_data="admin_pending")])
    keyboard.append([InlineKeyboardButton("⬅️ ត្រឡប់", callback_data="admin_back")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(orders_msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def admin_view_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View specific order details"""
    query = update.callback_query
    await query.answer()
    
    order_id = int(query.data.replace("admin_view_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await query.edit_message_text("❌ រកមិនឃើញការបញ្ជាទិញនេះទេ។")
        return ADMIN_PANEL
    
    status_text = {
        'pending': '⏳ កំពុងរង់ចាំ',
        'uploaded': '📸 បានផ្ញើរូបភាព',
        'approved': '✅ បានយល់ព្រម',
        'rejected': '❌ បដិសេធ',
        'completed': '🎉 បានបញ្ចប់'
    }
    
    order_msg = f"""
📋 **ព័ត៌មានលម្អិតការបញ្ជាទិញ #{order['id']}**

🆔 លេខការបញ្ជាទិញ: #{order['id']}
📘 សៀវភៅ: {order['product_name']}
🔢 ចំនួន: {order['quantity']}
💰 តម្លៃ: ${order['price']:.2f}
💰 សរុប: ${order['total_amount']:.2f}

👤 **ព័ត៌មានអ្នកទិញ៖**
ឈ្មោះ: {order['full_name']}
ក្រុម: {order['student_group']}
ទូរស័ព្ទ: {order['phone'] or 'មិនបានផ្តល់'}
អ្នកប្រើ: @{order['username'] or 'N/A'}

📊 **ស្ថានភាព៖**
{status_text.get(order['payment_status'], order['payment_status'])}
📅 កាលបរិច្ឆេទ: {order['order_date']}

"""
    
    if order['screenshot_path'] and os.path.exists(order['screenshot_path']):
        order_msg += "📸 រូបភាពការទូទាត់: មាន\n"
    
    if order['admin_notes']:
        order_msg += f"📝 កំណត់ចំណាំ: {order['admin_notes']}\n"
    
    keyboard = [
        [
            InlineKeyboardButton("✅ យល់ព្រម", callback_data=f"approve_{order['id']}"),
            InlineKeyboardButton("❌ បដិសេធ", callback_data=f"reject_{order['id']}")
        ],
        [InlineKeyboardButton("📞 ទាក់ទងអ្នកទិញ", callback_data=f"contact_{order['id']}")],
        [InlineKeyboardButton("📝 បន្ថែមកំណត់ចំណាំ", callback_data=f"note_{order['id']}")],
        [InlineKeyboardButton("⬅️ ត្រឡប់", callback_data="admin_pending")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Try to send screenshot if exists
    try:
        if order['screenshot_path'] and os.path.exists(order['screenshot_path']):
            with open(order['screenshot_path'], 'rb') as photo:
                await query.message.reply_photo(
                    photo=photo,
                    caption=order_msg,
                    reply_markup=reply_markup
                )
        else:
            await query.edit_message_text(order_msg, reply_markup=reply_markup)
    except:
        await query.edit_message_text(order_msg, reply_markup=reply_markup)

async def admin_approve_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin approves an order"""
    query = update.callback_query
    await query.answer()
    
    order_id = int(query.data.replace("approve_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await query.edit_message_text("❌ រកមិនឃើញការបញ្ជាទិញនេះទេ។")
        return
    
    # Update order status
    db.update_order(order_id, {
        'payment_status': 'approved',
        'admin_notes': 'បានយល់ព្រមដោយអ្នកគ្រប់គ្រង'
    })
    
    # Notify user
    try:
        user_msg = f"""
🎉 **ការបញ្ជាទិញរបស់អ្នកត្រូវបានយល់ព្រម!**

🆔 លេខការបញ្ជាទិញ: #{order_id}
📘 សៀវភៅ: {order['product_name']}
💰 ចំនួនទឹកប្រាក់: ${order['total_amount']:.2f}

✅ ការទូទាត់របស់អ្នកត្រូវបានបញ្ជាក់!
សៀវភៅរបស់អ្នកនឹងត្រូវបានដឹកជញ្ជូនឆាប់ៗនេះ។

🙏 សូមអរគុណសម្រាប់ការទិញ!
"""
        await context.bot.send_message(chat_id=order['user_id'], text=user_msg)
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")
    
    await query.edit_message_text(f"✅ ការបញ្ជាទិញ #{order_id} ត្រូវបានយល់ព្រម។")
    
    # Show next action
    keyboard = [
        [InlineKeyboardButton("📸 មើលការបញ្ជាទិញផ្សេងទៀត", callback_data="admin_pending")],
        [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text("អ្វីបន្ទាប់ទៀត?", reply_markup=reply_markup)

async def admin_reject_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin rejects an order"""
    query = update.callback_query
    await query.answer()
    
    order_id = int(query.data.replace("reject_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await query.edit_message_text("❌ រកមិនឃើញការបញ្ជាទិញនេះទេ។")
        return
    
    # Ask for reason
    context.user_data['rejecting_order'] = order_id
    await query.message.reply_text(
        f"❌ បដិសេធការបញ្ជាទិញ #{order_id}\n\n"
        "សូមបញ្ចូលមូលហេតុសម្រាប់ការបដិសេធ (ឬចុច /cancel):"
    )
    
    return ADMIN_PANEL

async def admin_contact_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin wants to contact user"""
    query = update.callback_query
    await query.answer()
    
    order_id = int(query.data.replace("contact_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await query.edit_message_text("❌ រកមិនឃើញការបញ្ជាទិញនេះទេ។")
        return
    
    context.user_data['contacting_order'] = order_id
    context.user_data['contacting_user'] = order['user_id']
    
    await query.message.reply_text(
        f"📞 ទាក់ទងអ្នកទិញសម្រាប់ការបញ្ជាទិញ #{order_id}\n\n"
        "សូមសរសេរសារដើម្បីផ្ញើទៅអ្នកទិញ (ឬចុច /cancel):"
    )
    
    return ADMIN_PANEL

async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin's messages (for rejection reasons or contacting users)"""
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        return CHOOSING
    
    message_text = update.message.text
    
    # Check if admin is rejecting an order
    if 'rejecting_order' in context.user_data:
        order_id = context.user_data['rejecting_order']
        order = db.get_order(order_id)
        
        if order:
            # Update order status
            db.update_order(order_id, {
                'payment_status': 'rejected',
                'admin_notes': f"បដិសេធ: {message_text}"
            })
            
            # Notify user
            try:
                user_msg = f"""
❌ **ការបញ្ជាទិញរបស់អ្នកត្រូវបានបដិសេធ**

🆔 លេខការបញ្ជាទិញ: #{order_id}
📘 សៀវភៅ: {order['product_name']}

📝 **មូលហេតុ៖**
{message_text}

សូមទាក់ទងអ្នកគ្រប់គ្រងប្រសិនបើអ្នកមានសំណួរ។
"""
                await context.bot.send_message(chat_id=order['user_id'], text=user_msg)
            except Exception as e:
                logger.error(f"Failed to notify user: {e}")
            
            await update.message.reply_text(f"✅ ការបញ្ជាទិញ #{order_id} ត្រូវបានបដិសេធ។")
        
        del context.user_data['rejecting_order']
        
        keyboard = [
            [InlineKeyboardButton("📸 មើលការបញ្ជាទិញផ្សេងទៀត", callback_data="admin_pending")],
            [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text("អ្វីបន្ទាប់ទៀត?", reply_markup=reply_markup)
        return ADMIN_PANEL
    
    # Check if admin is contacting a user
    elif 'contacting_order' in context.user_data:
        order_id = context.user_data['contacting_order']
        user_id = context.user_data['contacting_user']
        order = db.get_order(order_id)
        
        if order:
            # Send message to user
            try:
                user_msg = f"""
📞 **សារពីអ្នកគ្រប់គ្រង**

ដោយឡែកពីការបញ្ជាទិញ #{order_id}

💬 **សារ៖**
{message_text}

សូមឆ្លើយតបតាមរយៈបូតុងនេះ ឬទាក់ទងអ្នកគ្រប់គ្រងដោយផ្ទាល់។
"""
                await context.bot.send_message(chat_id=user_id, text=user_msg)
                await update.message.reply_text(f"✅ សារត្រូវបានផ្ញើទៅអ្នកទិញសម្រាប់ការបញ្ជាទិញ #{order_id}។")
            except Exception as e:
                await update.message.reply_text(f"❌ មិនអាចផ្ញើសារទៅអ្នកទិញបានទេ។ កំហុស: {e}")
        
        del context.user_data['contacting_order']
        del context.user_data['contacting_user']
        
        return ADMIN_PANEL
    
    return CHOOSING

# ===================== HELPER FUNCTIONS =====================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help"""
    help_text = """
🆘 **ជំនួយ**

📚 **អំពីហាងសៀវភៅ៖**
នេះគឺជាហាងសៀវភៅសម្រាប់មិត្តរួមថ្នាក់។ អ្នកអាចទិញសៀវភៅសិក្សាតាមរយៈប្រព័ន្ធទូទាត់ KHQR។

💰 **របៀបទូទាត់៖**
1. ជ្រើសរើសសៀវភៅ
2. បញ្ចូលចំនួន
3. បំពេញព័ត៌មាន
4. ស្កេនកូដ KHQR ដោយប្រើកម្មវិធី Bakong
5. ថតរូបភាពអេក្រង់ការទូទាត់
6. ផ្ញើរូបភាពមកបូតុង
7. រង់ចាំការបញ្ជាក់ពីអ្នកគ្រប់គ្រង

📱 **បញ្ជា៖**
/start - ចាប់ផ្តើម
/catalog - មើលសៀវភៅទាំងអស់
/order - បញ្ជាទិញសៀវភៅ
/myorders - មើលការបញ្ជាទិញរបស់ខ្ញុំ
/admin - ផ្ទាំងគ្រប់គ្រង (សម្រាប់អ្នកគ្រប់គ្រងប៉ុណ្ណោះ)
/help - ជំនួយ
/cancel - បោះបង់ប្រតិបត្តិការបច្ចុប្បន្ន

📞 **ទាក់ទង៖**
ប្រសិនបើមានបញ្ហា សូមទាក់ទងអ្នកគ្រប់គ្រង។
"""
    
    await update.message.reply_text(help_text)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation"""
    context.user_data.clear()
    await update.message.reply_text("❌ ប្រតិបត្តិការត្រូវបានបោះបង់។")
    return await start(update, context)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "main_menu":
        return await start(update, context)
    elif data == "catalog":
        return await show_catalog(update, context)
    elif data == "order":
        return await start_order(update, context)
    elif data == "my_orders":
        return await show_my_orders(update, context)
    elif data == "help":
        await help_command(update, context)
        return CHOOSING
    elif data.startswith("select_"):
        return await select_product(update, context)
    elif data == "generate_khqr":
        return await generate_khqr_payment(update, context)
    elif data == "upload_screenshot":
        return await request_screenshot(update, context)
    elif data == "cancel" or data == "cancel_order":
        return await cancel(update, context)
    elif data == "admin":
        return await admin_panel(update, context)
    elif data == "admin_pending":
        return await admin_pending_orders(update, context)
    elif data == "admin_all":
        # Show all orders
        orders = db.get_orders()
        await query.edit_message_text(f"📋 សរុបការបញ្ជាទិញ: {len(orders)}")
        return ADMIN_PANEL
    elif data == "admin_back":
        return await admin_panel(update, context)
    elif data.startswith("admin_view_"):
        return await admin_view_order(update, context)
    elif data.startswith("approve_"):
        return await admin_approve_order(update, context)
    elif data.startswith("reject_"):
        return await admin_reject_order(update, context)
    elif data.startswith("contact_"):
        return await admin_contact_user(update, context)
    
    return CHOOSING

# ===================== MAIN FUNCTION =====================
def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('order', start_order),
            CommandHandler('admin', admin_panel),
            CallbackQueryHandler(handle_callback)
        ],
        states={
            CHOOSING: [
                CallbackQueryHandler(handle_callback),
                CommandHandler('start', start),
                CommandHandler('catalog', show_catalog),
                CommandHandler('order', start_order),
                CommandHandler('myorders', show_my_orders),
                CommandHandler('help', help_command),
                CommandHandler('admin', admin_panel),
                CommandHandler('cancel', cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_message)
            ],
            SELECT_PRODUCT: [
                CallbackQueryHandler(handle_callback),
                CommandHandler('cancel', cancel)
            ],
            GET_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_quantity),
                CommandHandler('cancel', cancel),
                CallbackQueryHandler(handle_callback)
            ],
            GET_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_name),
                CommandHandler('cancel', cancel),
                CallbackQueryHandler(handle_callback)
            ],
            GET_GROUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_group),
                CommandHandler('cancel', cancel),
                CallbackQueryHandler(handle_callback)
            ],
            GET_PHONE: [
                MessageHandler(filters.TEXT | filters.CONTACT, get_phone),
                CommandHandler('cancel', cancel),
                CallbackQueryHandler(handle_callback)
            ],
            PAYMENT: [
                CallbackQueryHandler(handle_callback),
                CommandHandler('cancel', cancel)
            ],
            UPLOAD_SCREENSHOT: [
                MessageHandler(filters.PHOTO, handle_screenshot),
                CallbackQueryHandler(handle_callback),
                CommandHandler('cancel', cancel)
            ],
            ADMIN_PANEL: [
                CallbackQueryHandler(handle_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_message),
                CommandHandler('cancel', cancel)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Add handlers
    application.add_handler(conv_handler)
    
    # Add command handlers
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('cancel', cancel))
    
    # Start the bot
    print("🤖 Bot is running...")
    print("📚 Book Shop Bot with KHQR Payments")
    print("📸 Screenshot Verification System")
    print("👑 Admin Approval System")
    print("🚀 Ready for Railway Deployment")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()