"""
Music Bot — Telegram Spotify downloader for Hugging Face Spaces (Docker).
Send a Spotify track/album/playlist link, get MP3s back (320k).
Inspired by arashnm80/spot-seek-bot (MIT). For personal use only.
"""

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import telebot

BOT_TOKEN = os.environ["BOT_TOKEN"]
PORT = int(os.environ.get("PORT", 7860))
MAX_TG_FILE = 50_000_000  # Telegram bot API upload limit
DOWNLOAD_TIMEOUT = 1200   # seconds for one spotdl run

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

SPOTIFY_LINK = re.compile(
    r"https?://open\.spotify\.com/(?:intl-[a-zA-Z]{2}/)?"
    r"(track|album|playlist)/[a-zA-Z0-9]+"
)

busy_users = set()
busy_lock = threading.Lock()

WELCOME = (
    "سلام! 👋\n"
    "لینک ترک، آلبوم یا پلی‌لیست اسپاتیفای را بفرست تا برایت MP3 با کیفیت 320k بفرستم.\n\n"
    "مثال:\n`https://open.spotify.com/track/734dz1YaFITwawPpM25fSt`"
)


@bot.message_handler(commands=["start", "help"])
def start(msg):
    bot.reply_to(msg, WELCOME)


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle(msg):
    match = SPOTIFY_LINK.search(msg.text or "")
    if not match:
        bot.reply_to(msg, "این لینک اسپاتیفای معتبر نیست. یک لینک track/album/playlist بفرست.")
        return

    uid = msg.from_user.id
    with busy_lock:
        if uid in busy_users:
            bot.reply_to(msg, "دانلود قبلی‌ات هنوز تمام نشده، کمی صبر کن ⏳")
            return
        busy_users.add(uid)

    try:
        link = match.group(0)
        kind = match.group(1)
        note = " (آلبوم/پلی‌لیست ممکن است چند دقیقه طول بکشد)" if kind != "track" else ""
        status = bot.reply_to(msg, f"در حال دانلود... 🎧{note}")

        workdir = tempfile.mkdtemp(prefix="dl_")
        try:
            proc = subprocess.run(
                ["spotdl", "--bitrate", "320k", "--output", "{artist} - {title}.{output-ext}",
                 "download", link],
                cwd=workdir, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT,
            )
            mp3s = sorted(
                os.path.join(root, f)
                for root, _, files in os.walk(workdir)
                for f in files if f.endswith(".mp3")
            )
            if not mp3s:
                tail = (proc.stdout or "")[-400:]
                bot.edit_message_text(
                    "متأسفم، دانلود ناموفق بود ❌ کمی بعد دوباره امتحان کن.",
                    status.chat.id, status.message_id)
                print("spotdl failed:", tail, flush=True)
                return

            sent = 0
            for path in mp3s:
                if os.path.getsize(path) > MAX_TG_FILE:
                    bot.send_message(msg.chat.id,
                                     f"فایل `{os.path.basename(path)}` بزرگ‌تر از ۵۰MB است و تلگرام اجازه ارسالش را نمی‌دهد.")
                    continue
                with open(path, "rb") as f:
                    bot.send_audio(msg.chat.id, f, timeout=120,
                                   reply_to_message_id=msg.message_id)
                sent += 1
            bot.edit_message_text(
                f"تمام شد ✅ ({sent} فایل ارسال شد)" if sent else "فایلی قابل ارسال نبود ❌",
                status.chat.id, status.message_id)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    except subprocess.TimeoutExpired:
        bot.send_message(msg.chat.id, "دانلود بیش از حد طول کشید و متوقف شد ⏱ لینک کوچک‌تری امتحان کن.")
    except Exception as e:
        print("error:", e, flush=True)
        try:
            bot.send_message(msg.chat.id, "خطای غیرمنتظره‌ای پیش آمد ❌")
        except Exception:
            pass
    finally:
        with busy_lock:
            busy_users.discard(uid)


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("🎵 Music bot is running.".encode())

    def log_message(self, *args):
        pass


def run_health_server():
    ThreadingHTTPServer(("0.0.0.0", PORT), Health).serve_forever()


if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    print("Bot polling started.", flush=True)
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=25)
        except Exception as e:
            print("polling crashed, restarting:", e, flush=True)
            time.sleep(5)
