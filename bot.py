import io
import logging
import asyncio
import qrcode # Ensure you ran: pip install qrcode[pil]
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from bakong_khqr import KHQR

# --- CONFIGURATION ---
TOKEN = "8502848831:AAG184UsX7tirVtPSCsAcjzPBN8_t4PQ42E"
BAKONG_ACCOUNT_ID = "sin_soktep@bkrt"
MERCHANT_NAME = "Soktep Book Store"
MERCHANT_CITY = "Phnom Penh"
# Leave this empty if you don't have one yet, but status check won't work
BAKONG_API_TOKEN = "YOUR_BAKONG_OPEN_API_TOKEN" 

# Initialize KHQR
khqr = KHQR(BAKONG_API_TOKEN)

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📚 Welcome to {MERCHANT_NAME}!\n\n"
        "Type an amount (e.g., 0.01 or 1.50) to generate a payment QR."
    )

async def generate_custom_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    try:
        amount = float(user_input)
        await update.message.reply_text(f"⏳ Generating QR for ${amount:.2f}...")

        # 1. Create the KHQR String (Standard Format)
        qr_string = khqr.create_qr(
            bank_account=BAKONG_ACCOUNT_ID,
            merchant_name=MERCHANT_NAME,
            merchant_city=MERCHANT_CITY,
            amount=amount,
            currency="USD"
        )
        
        # 2. Manual Image Generation (Ensures it works without API issues)
        qr_img = qrcode.QRCode(version=1, box_size=10, border=5)
        qr_img.add_data(qr_string)
        qr_img.make(fit=True)
        
        img = qr_img.make_image(fill_color="black", back_color="white")
        
        # Save to memory buffer
        bio = io.BytesIO()
        img.save(bio, format='PNG')
        bio.seek(0)
        
        # 3. Send the Photo
        await update.message.reply_photo(
            photo=bio,
            caption=(
                f"🧾 **Invoice: {MERCHANT_NAME}**\n"
                f"💰 **Amount:** ${amount:.2f}\n"
                f"🏦 **To:** {BAKONG_ACCOUNT_ID}\n\n"
                f"Scan to pay via Bakong or any Bank App."
            ),
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error(f"Error: {e}")
        await update.message.reply_text("❌ Failed to generate QR. Please enter a valid number.")

def main():
    # Build the application
    app = Application.builder().token(TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, generate_custom_qr))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
