import io
import logging
import asyncio
import qrcode
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from bakong_khqr import KHQR

# --- CONFIGURATION ---
TOKEN = "8502848831:AAG184UsX7tirVtPSCsAcjzPBN8_t4PQ42E"
BAKONG_ACCOUNT_ID = "sin_soktep@bkrt"
MERCHANT_NAME = "Soktep Book Store"
MERCHANT_CITY = "Phnom Penh"

# To check payment status, you MUST have an API Token from Bakong
# Get it here: https://api-bakong.nbc.gov.kh/
BAKONG_API_TOKEN = "YOUR_BAKONG_API_TOKEN"

# Initialize KHQR
khqr = KHQR()

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📚 Welcome to {MERCHANT_NAME}!\n"
        "Please type the amount you want to pay (e.g., 0.01 or 1):"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        amount = float(text)
        await update.message.reply_text(f"⏳ Generating KHQR for ${amount:.2f}...")

        # 1. Generate KHQR String (Standard 0.1.4 logic)
        qr_data = khqr.create_qr(
            bank_account=BAKONG_ACCOUNT_ID,
            merchant_name=MERCHANT_NAME,
            merchant_city=MERCHANT_CITY,
            amount=amount,
            currency='USD',
            store_label='Telegram Bot',
            terminal_label='Online Shop'
        )

        # 2. Generate MD5 for status checking (as per Bakong standard)
        # Note: In 0.1.4, you manually hash or use the API check
        import hashlib
        md5_hash = hashlib.md5(qr_data.encode()).hexdigest()

        # 3. Create Real Photo QR
        qr_img = qrcode.QRCode(version=1, box_size=10, border=5)
        qr_img.add_data(qr_data)
        qr_img.make(fit=True)
        img = qr_img.make_image(fill_color="black", back_color="white")
        
        bio = io.BytesIO()
        img.save(bio, format='PNG')
        bio.seek(0)

        # 4. Send QR to User
        await update.message.reply_photo(
            photo=bio,
            caption=(
                f"✅ **Invoice for {MERCHANT_NAME}**\n"
                f"💰 **Amount:** ${amount:.2f}\n"
                f"🆔 **MD5:** `{md5_hash}`\n\n"
                "Please scan and pay within 10 minutes."
            ),
            parse_mode="Markdown"
        )

        # 5. Start Verification Task (10 Minutes)
        asyncio.create_task(verify_payment(update, md5_hash, amount))

    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number.")

async def verify_payment(update, md5, amount):
    """Checks Bakong API for 10 minutes (60 tries * 10 seconds)"""
    url = f"https://api-bakong.nbc.gov.kh/v1/check_transaction_by_md5"
    headers = {"Authorization": f"Bearer {BAKONG_API_TOKEN}"}
    payload = {"md5": md5}

    for _ in range(60): 
        await asyncio.sleep(10)
        try:
            # This requires the real API Token to work
            response = requests.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                # Check if 'data' status is success
                if data.get("responseCode") == 0: 
                    await update.message.reply_text(f"🎉 SUCCESS! Received payment of ${amount:.2f}.")
                    return
        except Exception as e:
            logging.error(f"Check Error: {e}")
            
    await update.message.reply_text(f"⏰ Payment for ${amount:.2f} expired after 10 minutes.")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Bot is active...")
    app.run_polling()

if __name__ == "__main__":
    main()
