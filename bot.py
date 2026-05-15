import os
import json
import base64
import tempfile
import traceback

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, Update
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from fastapi import FastAPI, Request

import uvicorn
import requests

# =========================
# LOAD ENV
# =========================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
RAILWAY_STATIC_URL = os.getenv("RAILWAY_STATIC_URL")

# =========================
# ACCESS SETTINGS
# =========================

# ГРУППА №1 — бот работает везде
MAIN_GROUP_ID = -1003923256615

# ГРУППА №2 — бот работает только в двух темах
TOPIC_GROUP_ID = -1003919465725

# РАЗРЕШЕННЫЕ ТЕМЫ
ALLOWED_TOPICS = [
    241,
    258
]

# =========================
# BOT
# =========================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()

# =========================
# RATE LIMIT
# =========================

last_request_time = {}

# =========================
# START COMMAND
# =========================

@dp.message(F.text == "/start")
async def start_handler(message: Message):

    print("WEBHOOK EVENT RECEIVED")
    print("TEXT MESSAGE: /start")
    print(f"CHAT ID: {message.chat.id}")
    print(f"THREAD ID: {message.message_thread_id}")
    print(f"USER ID: {message.from_user.id}")

    await message.answer(
        "Бот работает.\n\nОтправь фото еды."
    )

# =========================
# PHOTO HANDLER
# =========================

@dp.message(F.photo)
async def photo_handler(message: Message):

    try:

        print("WEBHOOK EVENT RECEIVED")
        print(f"PHOTO FROM: {message.from_user.id}")
        print(f"CHAT ID: {message.chat.id}")
        print(f"THREAD ID: {message.message_thread_id}")

        import time

        user_id = message.from_user.id
        now = time.time()

        # =========================
        # RATE LIMIT
        # =========================

        if user_id in last_request_time:
            if now - last_request_time[user_id] < 20:
                await message.answer(
                    "Подожди 20 секунд перед следующим фото."
                )
                return

        last_request_time[user_id] = now

        # =========================
        # ACCESS CONTROL
        # =========================

        # ГРУППА №1 — разрешено всё
        if message.chat.id == MAIN_GROUP_ID:
            pass

        # ГРУППА №2 — только две темы
        elif (
            message.chat.id == TOPIC_GROUP_ID
            and message.message_thread_id in ALLOWED_TOPICS
        ):
            pass

        # ВСЁ ОСТАЛЬНОЕ — ЗАПРЕЩЕНО
        else:
            return

        # =========================
        # GET PHOTO
        # =========================

        photo = message.photo[-1]

        file = await bot.get_file(photo.file_id)

        with tempfile.NamedTemporaryFile(suffix=".jpg") as temp:

            await bot.download_file(file.file_path, temp.name)

            with open(temp.name, "rb") as image_file:
                image_base64 = base64.b64encode(
                    image_file.read()
                ).decode("utf-8")

            # =========================
            # PROMPT
            # =========================

            prompt = """
Ты анализатор питания.

Определи по фото:
- название продукта или блюда
- примерный вес продукта в граммах
- калории на 100 грамм
- калории именно на весь продукт/порцию

Ответ строго JSON:

{
  "name": "",
  "weight_g": 0,
  "calories_per_100g": 0,
  "total_calories": 0
}
"""

            # =========================
            # OPENROUTER REQUEST
            # =========================

            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "qwen/qwen2.5-vl-72b-instruct",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": prompt
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_base64}"
                                    }
                                }
                            ]
                        }
                    ]
                },
                timeout=120
            )

            # =========================
            # OPENROUTER ERROR
            # =========================

            if response.status_code != 200:

                print("ERROR:")
                print(response.text)

                await message.answer(
                    f"Ошибка OpenRouter:\n{response.text}"
                )

                return

            # =========================
            # PARSE RESPONSE
            # =========================

            result = response.json()

            text = result["choices"][0]["message"]["content"]

            text = (
                text
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

            print("MODEL RESPONSE:")
            print(text)

            # =========================
            # JSON PARSE
            # =========================

            try:

                data = json.loads(text)

                answer = f"""
<b>{data['name']}</b>

Вес: ~{data['weight_g']} г

Калории на 100 г: ~{data['calories_per_100g']} ккал

Калории всего продукта: ~{data['total_calories']} ккал
"""

                await message.answer(answer)

            except Exception:

                await message.answer(text)

    except Exception as e:

        print("ERROR:")
        traceback.print_exc()

        await message.answer(
            f"Ошибка:\n{str(e)}"
        )

# =========================
# DEBUG HANDLER
# =========================

@dp.message()
async def debug_handler(message: Message):

    print("MESSAGE RECEIVED")
    print(f"CHAT ID: {message.chat.id}")
    print(f"THREAD ID: {message.message_thread_id}")
    print(f"USER ID: {message.from_user.id}")

# =========================
# FASTAPI
# =========================

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{RAILWAY_STATIC_URL}{WEBHOOK_PATH}"

app = FastAPI()

# =========================
# WEBHOOK
# =========================

@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):

    try:

        data = await request.json()

        update = Update.model_validate(
            data,
            context={"bot": bot}
        )

        await dp.feed_update(bot, update)

        return {"ok": True}

    except Exception:

        traceback.print_exc()

        return {"ok": False}

# =========================
# STARTUP
# =========================

@app.on_event("startup")
async def on_startup():

    print("STARTING WEBHOOK")
    print(WEBHOOK_URL)

    await bot.set_webhook(WEBHOOK_URL)

    info = await bot.get_webhook_info()

    print("WEBHOOK INFO:")
    print(info)

# =========================
# SHUTDOWN
# =========================

@app.on_event("shutdown")
async def on_shutdown():

    await bot.session.close()

# =========================
# MAIN
# =========================

if __name__ == "__main__":

    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=8080,
        reload=False
    )