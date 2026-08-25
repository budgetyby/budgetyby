"""
One-Time Telegram MTProto Authentication Helper.
Run this script ONCE in your terminal to save your login session on your laptop.
"""
import os
import sys
from telethon.sync import TelegramClient
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("TG_API_ID", "31137769"))
API_HASH = os.getenv("TG_API_HASH", "950fe9035f62264b68f02b5ae31559c6")
SESSION_PATH = os.path.join(r"c:\Users\jaysi\.gemini\antigravity\scratch\budget-by", "telegram_user.session")

def login():
    print("=" * 60)
    print("🚀 Telegram User Listener Authentication (One-Time Setup)")
    print("=" * 60)
    print(f"API ID: {API_ID}")
    print(f"API Hash: {API_HASH[:8]}...")
    print(f"Session Storage: {SESSION_PATH}")
    print("\nPlease enter your phone number when prompted below (e.g. +919876543210):")
    print("-" * 60)

    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    client.start()
    
    me = client.get_me()
    print("\n" + "=" * 60)
    print(f"🎉 SUCCESS! Logged in as: {me.first_name} (@{me.username or 'NoUsername'})")
    print("Your session has been saved to: telegram_user.session")
    print("Now your bot daemon will automatically monitor all your private channels 24/7!")
    print("=" * 60)

if __name__ == "__main__":
    login()
