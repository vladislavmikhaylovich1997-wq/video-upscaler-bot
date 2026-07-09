import os
import cv2
import uuid
import logging
import subprocess
import telebot
from flask import Flask
import threading

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it in Space Settings -> Secrets.")

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.reply_to(
        message,
        "Привіт! Надішли MP4-відео, і я зроблю апскейл до 2K (2560x1440) зі збереженням звуку."
    )

@bot.message_handler(content_types=["video", "document"])
def handle_video(message):
    video_file = None
    if message.content_type == "video":
        video_file = message.video
    elif (
        message.content_type == "document"
        and message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("video/")
    ):
        video_file = message.document

    if not video_file:
        bot.reply_to(message, "Надішли саме відеофайл.")
        return

    status_msg = bot.reply_to(message, "⏳ Завантажую відео...")
    sid = str(uuid.uuid4())
    input_path = f"input_{sid}.mp4"
    temp_output = f"temp_output_{sid}.mp4"
    final_output = f"output_{sid}.mp4"
    cap = None
    out = None

    try:
        file_info = bot.get_file(video_file.file_id)
        data = bot.download_file(file_info.file_path)
        with open(input_path, "wb") as f:
            f.write(data)

        bot.edit_message_text("⚙️ Аналізую відео...", chat_id=message.chat.id, message_id=status_msg.message_id)

        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise RuntimeError("Не вдалося відкрити відео")

        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0 or fps > 120:
            fps = 25.0

        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        ret, frame = cap.read()
        if not ret:
            raise RuntimeError("Не вдалося прочитати відео")

        h, w = frame.shape[:2]
        tw = 2560
        th = int(h * (tw / w))
        if th % 2:
            th += 1

        out = cv2.VideoWriter(temp_output, cv2.VideoWriter_fourcc(*"mp4v"), fps, (tw, th))

        processed = 0
        while ret:
            out.write(cv2.resize(frame, (tw, th), interpolation=cv2.INTER_LANCZOS4))
            processed += 1
            ret, frame = cap.read()

        cap.release()
        out.release()
        cap = out = None

        subprocess.run([
            "ffmpeg","-y","-i",temp_output,"-i",input_path,
            "-map","0:v","-map","1:a?","-c:v","libx264",
            "-pix_fmt","yuv420p","-c:a","aac","-shortest",final_output
        ], check=True)

        with open(final_output,"rb") as f:
            try:
                bot.send_video(message.chat.id,f,caption="✅ Готово в 2K!")
            except Exception:
                f.seek(0)
                bot.send_document(message.chat.id,f,caption="✅ Готово (файлом)!")

    except Exception as e:
        logger.exception("Processing error")
        bot.reply_to(message, f"Помилка: {e}")

    finally:
        if cap: cap.release()
        if out: out.release()
        for p in (input_path,temp_output,final_output):
            if os.path.exists(p):
                try: os.remove(p)
                except: pass
if __name__ == "__main__":
    logger.info("Bot started")

    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=int(os.getenv("PORT", 7860))),
        daemon=True
    ).start()

    bot.infinity_polling(
        timeout=60,
        long_polling_timeout=60,
        skip_pending=True
    )
