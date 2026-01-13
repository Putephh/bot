#!/usr/bin/env python3
"""
Simple Telegram Book Shop Bot for Railway
Working version with QR code generation
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

# For QR code generation
import qrcode
from PIL import Image, ImageDraw, ImageFont
import textwrap

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
        # Simple orders table
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
    
    def update_order(self, order_id, status, screenshot=None):
        if screenshot:
            self.cursor.execute('''
                UPDATE orders SET payment_status = ?, screenshot_path = ? WHERE id = ?
            ''', (status, screenshot, order_id))
        else:
            self.cursor.execute('''
                UPDATE orders SET payment_status = ? WHERE id = ?
            ''', (status, order_id))
        self.conn.commit()
    
    def get_pending_orders(self):
        self.cursor.execute('SELECT * FROM orders WHERE payment_status = "pending"')
        return self.cursor.fetchall()
    
    def get_user_orders(self, user_id):
        self.cursor.execute('SELECT * FROM orders WHERE user_id = ?', (user_id,))
        return self.cursor.fetchall()
    
    def get_order(self, order_id):
        self.cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
        return self.cursor.fetchone()

db = SimpleDB()

# ===================== QR CODE GENERATION =====================
def generate_real_khqr(order_id, amount, product_name, user_data):
    """Generate real KHQR payment code"""
    try:
        # Get your token from environment variable
        token = os.getenv('BAKONG_TOKEN')
        if not token:
            return None, None, "No Bakong token configured"
        
        khqr = KHQR(token)
        
        qr_data = khqr.create_qr(
            bank_account='sin_soktep@bkrt',  # Your Bakong account
            merchant_name='Pu-Tephh Kilo Sahav',
            merchant_city='Phnom Penh',
            amount=amount,
            currency='USD',
            store_label='Telegram Bot',
            phone_number='85512345678',  # Your contact
            bill_number=f'BOOK{order_id}',
            terminal_label=f'Order_{order_id}',
            static=False
        )
        
        md5_hash = khqr.generate_md5(qr_data)
        
        # Generate QR image
        qr_image = khqr.qr_image(qr_data, format='png')
        
        return qr_data, md5_hash, qr_image
        
    except Exception as e:
        logger.error(f"KHQR generation error: {e}")
        return None, None, str(e)
    
    # Create QR code image
    qr_image = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to RGB for adding text
    qr_image = qr_image.convert("RGB")
    
    # Create a new image with text below QR code
    qr_width, qr_height = qr_image.size
    text_height = 100
    new_image = Image.new("RGB", (qr_width, qr_height + text_height), "white")
    
    # Paste QR code
    new_image.paste(qr_image, (0, 0))
    
    # Add text
    draw = ImageDraw.Draw(new_image)
    
    # Simple text (no font loading to avoid issues)
    text_lines = [
        f"Order #{order_id}",
        f"Amount: ${amount:.2f}",
        "Scan with Bakong App",
        "Then upload screenshot"
    ]
    
    y_position = qr_height + 10
    for line in text_lines:
        # Draw simple text (using default font)
        draw.text((10, y_position), line, fill="black")
        y_position += 20
    
    return new_image

# ===================== BOT HANDLERS =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    welcome_msg = f"""👋 សួស្តី {user.first_name}!

📚 **ស្វាគមន៍មកកាន់ហាងសៀវភៅសម្រាប់មិត្តរួមថ្នាក់**

**សៀវភៅទាំងអស់៖**
1. សៀវភៅគណិតវិទ្យា - $1.70
2. Human & Society - $1.99
3. គោលការណ៍អាជីវកម្ម - $1.99
4. សៀវភៅកុំព្យូទ័រ - $2.50

ចុចប៊ូតុងខាងក្រោមដើម្បីចាប់ផ្តើម៖
"""
    
    keyboard = [
        [InlineKeyboardButton("📚 មើលសៀវភៅ", callback_data="catalog")],
        [InlineKeyboardButton("🛒 បញ្ជាទិញឥឡូវនេះ", callback_data="order")],
        [InlineKeyboardButton("📋 ការបញ្ជាទិញរបស់ខ្ញុំ", callback_data="my_orders")],
        [InlineKeyboardButton("ℹ️ ជំនួយ", callback_data="help")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_msg, reply_markup=reply_markup)
    return CHOOSING

async def show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show book catalog"""
    query = update.callback_query
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
    
    await query.edit_message_text(catalog_msg, reply_markup=reply_markup)

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
    
    # Simple phone input
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
    """Generate KHQR code for payment"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    product = context.user_data['product']
    quantity = context.user_data['quantity']
    total = context.user_data['total']
    name = context.user_data['name']
    group = context.user_data['group']
    phone = context.user_data.get('phone', '')
    
    # Save order to database
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
    
    # Generate QR code
    qr_image = generate_payment_qr(order_id, total, product['name_kh'])
    
    # Save QR code
    qr_path = f"payment_images/qr_{order_id}.png"
    qr_image.save(qr_path)
    
    # Store order ID in context
    context.user_data['order_id'] = order_id
    
    # Convert to bytes for Telegram
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
    
    return UPLOAD_SCREENSHOT

async def request_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Request payment screenshot"""
    query = update.callback_query
    await query.answer()
    
    order_id = context.user_data.get('order_id', 'N/A')
    
    await query.message.reply_text(
        f"📸 **សូមផ្ញើរូបភាពអេក្រង់ការទូទាត់៖**\n\n"
        f"ការបញ្ជាទិញ #{order_id}\n\n"
        "1. បើកកម្មវិធី Bakong\n"
        "2. ស្កេនកូដ QR\n"
        "3. បញ្ជាក់ការទូទាត់\n"
        "4. ថតរូបភាពអេក្រង់\n"
        "5. ផ្ញើរូបភាពមកទីនេះ\n\n"
        "អ្នកគ្រប់គ្រងនឹងពិនិត្យរូបភាពរបស់អ្នក។"
    )
    
    return UPLOAD_SCREENSHOT

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded screenshot"""
    if not update.message or not update.message.photo:
        await update.message.reply_text("❌ សូមផ្ញើរូបភាពអេក្រង់។")
        return UPLOAD_SCREENSHOT
    
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
        db.update_order(context.user_data['order_id'], 'uploaded', filename)
    
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

សូមពិនិត្យរូបភាព។
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
            
            # Send admin actions
            keyboard = [
                [
                    InlineKeyboardButton("✅ យល់ព្រម", callback_data=f"approve_{order_id}"),
                    InlineKeyboardButton("❌ បដិសេធ", callback_data=f"reject_{order_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"សកម្មភាពសម្រាប់ការបញ្ជាទិញ #{order_id}:",
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
    
    # Clear context
    context.user_data.clear()
    
    keyboard = [
        [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")],
        [InlineKeyboardButton("📋 ការបញ្ជាទិញរបស់ខ្ញុំ", callback_data="my_orders")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("អ្វីបន្ទាប់?", reply_markup=reply_markup)
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
    
    orders_msg = "📋 **ការបញ្ជាទិញរបស់អ្នក៖**\n\n"
    
    status_emojis = {
        'pending': '⏳',
        'uploaded': '📸',
        'approved': '✅',
        'rejected': '❌'
    }
    
    for order in orders:
        emoji = status_emojis.get(order[9], '❓')  # payment_status is at index 9
        orders_msg += f"**#{order[0]}** - {order[6]}\n"  # id and product_name
        orders_msg += f"{emoji} ស្ថានភាព: {order[9]}\n"
        orders_msg += f"🔢 ចំនួន: {order[7]}\n"
        orders_msg += f"💰 តម្លៃ: ${order[8]:.2f}\n"
        orders_msg += f"📅 កាលបរិច្ឆេទ: {order[11][:10]}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("🛒 បញ្ជាទិញថ្មី", callback_data="order")],
        [InlineKeyboardButton("🏠 ទៅផ្ទះ", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(orders_msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(orders_msg, reply_markup=reply_markup)

async def admin_approve_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin approves an order"""
    query = update.callback_query
    await query.answer()
    
    try:
        order_id = int(query.data.replace("approve_", ""))
        order = db.get_order(order_id)
        
        if order:
            db.update_order(order_id, 'approved')
            
            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=order[1],  # user_id
                    text=f"🎉 **ការបញ្ជាទិញរបស់អ្នកត្រូវបានយល់ព្រម!**\n\n"
                         f"🆔 លេខការបញ្ជាទិញ: #{order_id}\n"
                         f"✅ ការទូទាត់ត្រូវបានបញ្ជាក់!\n"
                         f"សៀវភៅរបស់អ្នកនឹងត្រូវបានដឹកជញ្ជូនឆាប់ៗនេះ។"
                )
            except:
                pass
            
            await query.edit_message_text(f"✅ ការបញ្ជាទិញ #{order_id} ត្រូវបានយល់ព្រម។")
    except:
        await query.edit_message_text("❌ មានបញ្ហាក្នុងការយល់ព្រម។")

async def admin_reject_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin rejects an order"""
    query = update.callback_query
    await query.answer()
    
    try:
        order_id = int(query.data.replace("reject_", ""))
        db.update_order(order_id, 'rejected')
        await query.edit_message_text(f"❌ ការបញ្ជាទិញ #{order_id} ត្រូវបានបដិសេធ។")
    except:
        await query.edit_message_text("❌ មានបញ្ហាក្នុងការបដិសេធ។")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help"""
    help_text = """
🆘 **ជំនួយ**

📚 **របៀបបញ្ជាទិញ៖**
1. ជ្រើសរើសសៀវភៅ
2. បញ្ចូលចំនួន
3. បំពេញព័ត៌មាន
4. ស្កេនកូដ KHQR
5. ថតរូបភាពការទូទាត់
6. ផ្ញើរូបភាពមកបូតុង

📱 **បញ្ជា៖**
/start - ចាប់ផ្តើម
/help - ជំនួយ
/cancel - បោះបង់

🙏 **សូមអរគុណសម្រាប់ការប្រើប្រាស់!**
"""
    
    await update.message.reply_text(help_text)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation"""
    context.user_data.clear()
    await update.message.reply_text("❌ ប្រតិបត្តិការត្រូវបានបោះបង់។")
    return await start(update, context)

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to main menu"""
    return await start(update, context)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "main_menu":
        return await main_menu(update, context)
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
    elif data.startswith("approve_"):
        await admin_approve_order(update, context)
        return CHOOSING
    elif data.startswith("reject_"):
        await admin_reject_order(update, context)
        return CHOOSING
    
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
            CommandHandler('help', help_command),
            CallbackQueryHandler(handle_callback)
        ],
        states={
            CHOOSING: [
                CallbackQueryHandler(handle_callback),
                CommandHandler('start', start),
                CommandHandler('help', help_command),
                CommandHandler('cancel', cancel)
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
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone),
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
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Add handlers
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('cancel', cancel))
    
    # Start the bot
    print("🤖 Bot is running...")
    print(f"📚 Products: {len(PRODUCTS)} books")
    print(f"👑 Admins: {ADMIN_IDS}")
    print("🚀 Ready on Railway!")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
