import os
import asyncio
import logging
import io
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from bakong_khqr import KHQR

# --- CONFIGURATION ---
TOKEN = "8502848831:AAG184UsX7tirVtPSCsAcjzPBN8_t4PQ42E"
BAKONG_ACCOUNT_ID = "sin_soktep@bkrt"
MERCHANT_NAME = "Soktep Book Store"
MERCHANT_CITY = "Phnom Penh"
# Note: You still need a Bakong API Token for MD5 verification to work
BAKONG_API_TOKEN = "YOUR_BAKONG_OPEN_API_TOKEN" 

# Initialize KHQR
khqr = KHQR(BAKONG_API_TOKEN)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📚 Welcome to {MERCHANT_NAME}!\n\n"
        "Just type the amount you want to pay (e.g., 0.01 or 1 or 5) "
        "and I will generate a real KHQR for you."
    )

async def generate_custom_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    
    try:
        # Convert input to float (e.g., "1" becomes 1.0)
        amount = float(user_input)
        if amount <= 0:
            await update.message.reply_text("Please enter an amount greater than 0.")
            return

        await update.message.reply_text(f"⏳ Generating KHQR for ${amount}...")

        # 1. Create the KHQR String
        qr_data = khqr.create_qr(
            bank_account=BAKONG_ACCOUNT_ID,
            merchant_name=MERCHANT_NAME,
            merchant_city=MERCHANT_CITY,
            amount=amount,
            currency="USD",
            store_label="TelegramBot",
            terminal_label="Bot01"
        )
        
        # 2. Generate the MD5 for verification
        payment_md5 = khqr.generate_md5(qr_data)
        
        # 3. Generate the Image
        # If your library version doesn't support .qr_image, we use qrcode library
        import qrcode
        img = qrcode.make(qr_data)
        bio = io.BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)
        
        await update.message.reply_photo(
            photo=bio,
            caption=(
                f"✅ **Invoice: {MERCHANT_NAME}**\n"
                f"💰 **Amount:** ${amount:.2f}\n"
                f"🕒 **Expires in:** 10 minutes\n\n"
                f"Scan with Bakong or any KHQR-supported app."
            ),
            parse_mode="Markdown"
        )

        # 4. Start 10-minute Verification Loop
        asyncio.create_task(verify_payment(update, payment_md5, amount))

    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number (e.g., 0.01).")

async def verify_payment(update, md5, amount):
    # Check status every 10 seconds for 10 minutes
    for _ in range(60): 
        await asyncio.sleep(10)
        # Note: check_payment requires a valid BAKONG_API_TOKEN
        status = khqr.check_payment(md5) 
        if status == "PAID":
            await update.message.reply_text(f"🎉 SUCCESS! Payment of ${amount:.2f} received. Thank you!")
            return
    
    await update.message.reply_text(f"⚠️ Payment window for ${amount:.2f} has expired.")

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, generate_custom_qr))
    
    print("Bot is running... Send the amount in Telegram.")
    app.run_polling()

if __name__ == "__main__":
    main()
