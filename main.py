import os
import uuid
import time
import asyncio
import tempfile
import logging
import requests

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==========================================
# LITTLE ORBIT STUDIOS - TELEGRAM BOT
# ==========================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# Credentials come from Railway Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
PIXVERSE_API_KEY = os.getenv("PIXVERSE_API_KEY")

# PixVerse configuration
BASE_URL = "https://app-api.pixverse.ai"
MODEL = "v6"
DURATION = 5
QUALITY = "720p"
ASPECT_RATIO = "16:9"

MAX_WAIT = 600
POLL_INTERVAL = 5

# ==========================================
# STARTUP CHECK
# ==========================================

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is missing!")

if not PIXVERSE_API_KEY:
    raise RuntimeError("PIXVERSE_API_KEY is missing!")


# ==========================================
# PIXVERSE API FUNCTIONS
# ==========================================

def get_headers():
    return {
        "API-KEY": PIXVERSE_API_KEY,
        "Ai-trace-id": str(uuid.uuid4()),
    }


def api_request(method, endpoint, **kwargs):
    url = f"{BASE_URL}{endpoint}"

    response = requests.request(
        method,
        url,
        headers=get_headers(),
        timeout=60,
        **kwargs,
    )

    response.raise_for_status()

    try:
        data = response.json()
    except ValueError:
        raise Exception("PixVerse returned an invalid response.")

    if data.get("ErrCode") != 0:
        raise Exception(
            f"PixVerse error: {data.get('ErrMsg', 'Unknown error')}"
        )

    return data.get("Resp", {})


# ==========================================
# IMAGE UPLOAD
# ==========================================

def upload_image(image_path):

    with open(image_path, "rb") as image:

        response = requests.post(
            f"{BASE_URL}/openapi/v2/image/upload",
            headers=get_headers(),
            files={
                "image": (
                    "reference.jpg",
                    image,
                    "image/jpeg",
                )
            },
            timeout=120,
        )

    response.raise_for_status()

    data = response.json()

    if data.get("ErrCode") != 0:
        raise Exception(
            f"Image upload failed: {data.get('ErrMsg')}"
        )

    return data["Resp"]["img_id"]


# ==========================================
# TEXT TO VIDEO
# ==========================================

def create_text_video(prompt):

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "duration": DURATION,
        "quality": QUALITY,
        "aspect_ratio": ASPECT_RATIO,
        "generate_audio_switch": False,
    }

    result = api_request(
        "POST",
        "/openapi/v2/video/text/generate",
        json=payload,
    )

    return result["video_id"]


# ==========================================
# IMAGE TO VIDEO
# ==========================================

def create_image_video(prompt, img_id):

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "img_id": img_id,
        "duration": DURATION,
        "quality": QUALITY,
        "generate_audio_switch": False,
    }

    result = api_request(
        "POST",
        "/openapi/v2/video/img/generate",
        json=payload,
    )

    return result["video_id"]


# ==========================================
# CHECK VIDEO STATUS
# ==========================================

def wait_for_video(video_id):

    endpoint = f"/openapi/v2/video/result/{video_id}"

    deadline = time.monotonic() + MAX_WAIT

    while time.monotonic() < deadline:

        result = api_request(
            "GET",
            endpoint,
        )

        status = result.get("status")

        if status == 1:

            video_url = result.get("url")

            if not video_url:
                raise Exception(
                    "Video finished but PixVerse returned no URL."
                )

            return video_url

        elif status == 7:
            raise Exception(
                "Video was rejected by PixVerse moderation."
            )

        elif status == 8:
            raise Exception(
                "PixVerse could not generate this video."
            )

        logger.info(
            "Video %s status: %s",
            video_id,
            status,
        )

        time.sleep(POLL_INTERVAL)

    raise Exception(
        "Video generation timed out. Check PixVerse task status."
    )


# ==========================================
# TELEGRAM MESSAGE HANDLER
# ==========================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.effective_message

    if not message:
        return

    status_message = await message.reply_text(
        "🌙 Little Orbit Studios\n\n"
        "Preparing your animation... 🎬"
    )

    image_path = None

    try:

        # IMAGE + PROMPT
        if message.photo:

            prompt = (
                message.caption
                or "Animate this image naturally while preserving its original appearance."
            )

            await status_message.edit_text(
                "🖼️ Downloading your reference image..."
            )

            photo = await message.photo[-1].get_file()

            with tempfile.NamedTemporaryFile(
                suffix=".jpg",
                delete=False,
            ) as temp:

                image_path = temp.name

            await photo.download_to_drive(image_path)

            await status_message.edit_text(
                "📤 Uploading reference to PixVerse..."
            )

            img_id = await asyncio.to_thread(
                upload_image,
                image_path,
            )

            await status_message.edit_text(
                "🎥 Creating your animation..."
            )

            video_id = await asyncio.to_thread(
                create_image_video,
                prompt,
                img_id,
            )

        # TEXT ONLY
        elif message.text:

            prompt = message.text.strip()

            if not prompt:
                await status_message.edit_text(
                    "Please send a video prompt."
                )
                return

            await status_message.edit_text(
                "✨ Creating your video from text..."
            )

            video_id = await asyncio.to_thread(
                create_text_video,
                prompt,
            )

        else:

            await status_message.edit_text(
                "Please send a photo with a caption or a text prompt."
            )
            return

        # WAIT FOR GENERATION
        await status_message.edit_text(
            f"🚀 Video submitted!\n\n"
            f"Task ID: {video_id}\n\n"
            f"PixVerse is rendering your scene..."
        )

        video_url = await asyncio.to_thread(
            wait_for_video,
            video_id,
        )

        # SEND FINISHED VIDEO
        await status_message.edit_text(
            "🎉 Your animation is ready! Sending it now..."
        )

        await message.reply_video(
            video=video_url,
            caption="🌙 Little Orbit Studios | Animation complete",
            read_timeout=180,
            write_timeout=180,
            connect_timeout=30,
        )

        await status_message.delete()

    except Exception as error:

        logger.exception("Video generation failed")

        try:
            await status_message.edit_text(
                "❌ Something went wrong.\n\n"
                f"{str(error)[:700]}\n\n"
                "Please check your Railway logs if this continues."
            )
        except Exception:
            logger.exception("Could not send error message")

    finally:

        if image_path and os.path.exists(image_path):

            try:
                os.remove(image_path)
            except OSError:
                logger.warning("Could not remove temporary image")


# ==========================================
# BOT STARTUP
# ==========================================

def main():

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT | filters.PHOTO,
            handle_message,
        )
    )

    logger.info(
        "Little Orbit Studios bot is starting..."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
