import os
import uuid
import time
import requests
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# ======================
# PASTE YOUR KEYS HERE
# ======================
TELEGRAM_TOKEN = "8590501788:AAGNfPEJ3yyqo9MCK-mnnhumvqDOT7AUhWo"
PIXVERSE_API_KEY = "sk-dd7473dfee8a62e5d160297349295274"

# PixVerse settings
BASE_URL = "https://app-api.pixverse.ai"
MODEL = "v6" # you can change to "v6-max" later if you want
DURATION = 5 # seconds (5, 8 or 10 recommended)
QUALITY = "720p"
ASPECT_RATIO = "16:9"

# ======================
# Helper functions
# ======================

def get_headers():
return {
"API-KEY": PIXVERSE_API_KEY,
"Ai-trace-id": str(uuid.uuid4()),
"Content-Type": "application/json"
}

def upload_image(image_path: str):
"""Upload image to PixVerse and return img_id"""
url = f"{BASE_URL}/openapi/v2/image/upload"
headers = {
"API-KEY": PIXVERSE_API_KEY,
"Ai-trace-id": str(uuid.uuid4())
}
with open(image_path, "rb") as f:
files = {"file": f}
response = requests.post(url, headers=headers, files=files)

data = response.json()
if data.get("ErrCode") != 0:
raise Exception(f"Image upload failed: {data.get('ErrMsg')}")

return data["Resp"]["img_id"]

def create_text_video(prompt: str):
"""Create video from text only"""
url = f"{BASE_URL}/openapi/v2/video/text/generate"
payload = {
"model": MODEL,
"prompt": prompt,
"duration": DURATION,
"quality": QUALITY,
"aspect_ratio": ASPECT_RATIO,
"generate_audio_switch": False
}
response = requests.post(url, headers=get_headers(), json=payload)
data = response.json()

if data.get("ErrCode") != 0:
raise Exception(f"Failed to create video: {data.get('ErrMsg')}")

return data["Resp"]["video_id"]

def create_image_video(prompt: str, img_id: int):
"""Create video from image + prompt"""
url = f"{BASE_URL}/openapi/v2/video/img/generate"
payload = {
"model": MODEL,
"prompt": prompt,
"img_id": img_id,
"duration": DURATION,
"quality": QUALITY,
"generate_audio_switch": False
}
response = requests.post(url, headers=get_headers(), json=payload)
data = response.json()

if data.get("ErrCode") != 0:
raise Exception(f"Failed to create video: {data.get('ErrMsg')}")

return data["Resp"]["video_id"]

def wait_for_video(video_id: int, max_wait=180):
"""Poll until the video is ready"""
url = f"{BASE_URL}/openapi/v2/video/result/{video_id}"

for _ in range(max_wait // 5):
headers = get_headers()
response = requests.get(url, headers=headers)
data = response.json()

if data.get("ErrCode") != 0:
raise Exception(f"Error checking status: {data.get('ErrMsg')}")

status = data["Resp"].get("status")

if status == 1: # completed
return data["Resp"]["url"]
elif status in [7, 8]: # failed
raise Exception("Video generation failed")

time.sleep(5)

raise Exception("Timeout waiting for video")

# ======================
# Telegram handlers
# ======================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
message = update.message
if not message:
return

status_msg = await message.reply_text("Generating your clip... please wait ⏳")

try:
# Case 1: User sent a photo + caption
if message.photo:
prompt = message.caption or "Animate this image"

# Download the photo
photo_file = await message.photo[-1].get_file()
photo_path = f"/tmp/{uuid.uuid4()}.jpg"
await photo_file.download_to_drive(photo_path)

# Upload to PixVerse
img_id = upload_image(photo_path)
video_id = create_image_video(prompt, img_id)

# Clean up
os.remove(photo_path)

# Case 2: User sent only text
else:
prompt = message.text
if not prompt:
await status_msg.edit_text("Please send a text prompt or a photo with caption.")
return
video_id = create_text_video(prompt)

# Wait for the video
video_url = wait_for_video(video_id)

# Send the finished video
await status_msg.edit_text("Clip ready! Sending...")
await message.reply_video(video=video_url, caption="Here’s your clip 🎬")
await status_msg.delete()

except Exception as e:
await status_msg.edit_text(f"Error: {str(e)}")

# ======================
# Start the bot
# ======================

def main():
app = Application.builder().token(TELEGRAM_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
print("Bot is running...")
app.run_polling()

if __name__ == "__main__":
main()
