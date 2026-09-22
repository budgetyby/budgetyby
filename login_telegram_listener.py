"""
One-Time Telegram MTProto Authentication Helper.
Run this script ONCE in your terminal to save your login session on your laptop.
"""
import os
import sys
import re
from telethon.sync import TelegramClient
from dotenv import load_dotenv

load_dotenv()

API_ID_RAW = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")

if not API_ID_RAW or not API_HASH:
    print("❌ Error: TG_API_ID and TG_API_HASH must be configured in your .env file.")
    sys.exit(1)

API_ID = int(API_ID_RAW)
SESSION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_user.session")

def phone_getter():
    phone = input("Please enter your phone number (e.g. +917060435399): ").strip()
    # Auto-format 10 digit Indian number if user omitted +91
    clean_digits = re.sub(r'[^\d]', '', phone)
    if len(clean_digits) == 10:
        phone = f"+91{clean_digits}"
    elif not phone.startswith("+"):
        phone = f"+{clean_digits}"
    print(f"Using normalized phone number: {phone}")
    return phone

def login():
    print("=" * 60)
    print("🚀 Telegram User Listener Authentication (One-Time Setup)")
    print("=" * 60)
    print(f"API ID: {API_ID}")
    print(f"API Hash: {API_HASH[:8]}...")
    print(f"Session Storage: {SESSION_PATH}")
    print("-" * 60)

    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    client.start(phone=phone_getter)
    
    me = client.get_me()
    print("\n" + "=" * 60)
    print(f"🎉 SUCCESS! Logged in as: {me.first_name} {me.last_name or ''} (@{me.username or 'NoUsername'})")
    print("Your session has been saved to: telegram_user.session")
    print("Now your bot daemon will automatically monitor all your private channels 24/7!")
    print("=" * 60)

if __name__ == "__main__":
    login()
