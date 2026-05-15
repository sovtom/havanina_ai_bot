import os
import json
import base64
import tempfile
import traceback
import asyncio
from datetime import datetime
from urllib.parse import quote

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
# MODELS
# =========================

VISION_MODELS = [
    "qwen/qwen2.5-vl-72b-instruct",
    "meta-llama/llama-3.2-11b-vision-instruct:free"
]

# =========================
# ACCESS SETTINGS
# =========================

MAIN_GROUP_ID = -1003923256615

TOPIC_GROUP_ID = -1003919465725

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
# CALORIES STORAGE
# =========================

calories_stats = {}

# =========================
# ACCESS CHECK
# =========================

def is_allowed(message: Message):

    if message.chat.id == MAIN_GROUP_ID:
        return True

    if (
        message.chat.id == TOPIC_GROUP_ID
        and message.message_thread_id in ALLOWED_TOPICS
    ):
        return True

    return False

# =========================
# SAVE CALORIES
# =========================

def save_calories(message: Message, calories):

    thread_id = message.message_thread_id

    key = f"{message.chat.id}_{thread_id}"

    if key not in calories_stats:

        calories_stats[key] = {
            "calories": 0,
            "chat_id": message.chat.id,
            "thread_id": thread_id
        }

    calories_stats[key]["calories"] += float(calories)

# =========================
# DAILY REPORT TASK
# =========================

async def daily_report_loop():

    while True:

        now = datetime.now()

        next_midnight = now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        if next_midnight <= now:

            from datetime import timedelta

            next_midnight += timedelta(days=1)

        sleep_seconds = (next_midnight - now).total_seconds()

        await asyncio.sleep(sleep_seconds)

        report_date = datetime.now().strftime("%d.%m.%Y")

        for key, stats in calories_stats.items():

            try:

                total = round(stats["calories"])

                text = (
                    f"Всего захавано {total} каллорий "
                    f"за {report_date}"
                )

                if stats["thread_id"]:

                    await bot.send_message(
                        chat_id=stats["chat_id"],
                        text=text,
                        message_thread_id=stats["thread_id"]
                    )

                else:

                    await bot.send_message(
                        chat_id=stats["chat_id"],
                        text=text
                    )

            except Exception:

                traceback.print_exc()

        calories_stats.clear()

# =========================
# START COMMAND
# =========================

@dp.message(F.text == "/start")
async def start_handler(message: Message):

    if not is_allowed(message):
        return

    await message.answer(
        "Бот работает.\n\n"
        "Можно отправить:\n"
        "- фото еды\n"
        "- или текст типа:\n"
        "гречка 250г"
    )

# =========================
# OPENROUTER REQUEST
# =========================

def analyze_product(prompt, image_base64=None):

    last_error = None

    for model in VISION_MODELS:

        try:

            print(f"TRY MODEL: {model}")

            payload = {
                "model": model,
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
            }

            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=120
            )

            if response.status_code != 200:

                print(response.text)

                last_error = response.text

                continue

            result = response.json()

            text = result["choices"][0]["message"]["content"]

            text = (
                text
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

            return text

        except Exception as e:

            traceback.print_exc()

            last_error = str(e)

    raise Exception(
        f"Все модели недоступны.\n\n{last_error}"
    )

# =========================
# OPEN FOOD FACTS
# =========================

def get_nutrition_data(product_name, weight_g):

    try:

        encoded = quote(product_name)

        url = (
            f"https://world.openfoodfacts.org/"
            f"cgi/search.pl"
            f"?search_terms={encoded}"
            f"&search_simple=1"
            f"&action=process"
            f"&json=1"
        )

        response = requests.get(
            url,
            timeout=30
        )

        data = response.json()

        products = data.get("products", [])

        if not products:

            return None

        product = products[0]

        nutriments = product.get(
            "nutriments",
            {}
        )

        calories_100g = nutriments.get(
            "energy-kcal_100g"
        )

        if calories_100g is None:

            return None

        calories_100g = float(calories_100g)

        total_calories = round(
            calories_100g * weight_g / 100
        )

        return {
            "calories_per_100g":
                round(calories_100g),
            "total_calories":
                total_calories
        }

    except Exception:

        traceback.print_exc()

        return None

# =========================
# PHOTO HANDLER
# =========================

@dp.message(F.photo)
async def photo_handler(message: Message):

    try:

        if not is_allowed(message):
            return

        import time

        user_id = message.from_user.id
        now = time.time()

        if user_id in last_request_time:

            if now - last_request_time[user_id] < 20:

                await message.answer(
                    "Подожди 20 секунд "
                    "перед следующим фото."
                )

                return

        last_request_time[user_id] = now

        photo = message.photo[-1]

        file = await bot.get_file(photo.file_id)

        with tempfile.NamedTemporaryFile(
            suffix=".jpg"
        ) as temp:

            await bot.download_file(
                file.file_path,
                temp.name
            )

            with open(
                temp.name,
                "rb"
            ) as image_file:

                image_base64 = base64.b64encode(
                    image_file.read()
                ).decode("utf-8")

            # =========================
            # PRODUCT DETECTION
            # =========================

            prompt = """
Ты анализатор еды.

Твоя задача:
- определить точное название продукта
- бренд
- примерный вес продукта

НЕ считай калории.

ВНИМАТЕЛЬНО анализируй:
- текст на упаковке
- бренд
- размер упаковки
- вес если он указан

Ответ строго JSON:

{
  "name": "",
  "weight_g": 0
}
"""

            text = analyze_product(
                prompt,
                image_base64
            )

            print(text)

            data = json.loads(text)

            name = data["name"]
            weight = float(data["weight_g"])

            # =========================
            # NUTRITION DATABASE
            # =========================

            nutrition = get_nutrition_data(
                name,
                weight
            )

            # fallback если не нашли
            if not nutrition:

                nutrition = {
                    "calories_per_100g": "?",
                    "total_calories": "?"
                }

            # =========================
            # SAVE CALORIES
            # =========================

            if nutrition["total_calories"] != "?":

                save_calories(
                    message,
                    nutrition["total_calories"]
                )

            # =========================
            # ANSWER
            # =========================

            answer = f"""
<b>{name}</b>

Вес: ~{round(weight)} г

Калории на 100 г:
~{nutrition['calories_per_100g']} ккал

Калории всего продукта:
~{nutrition['total_calories']} ккал
"""

            await message.answer(answer)

    except Exception as e:

        traceback.print_exc()

        await message.answer(
            f"Ошибка:\n{str(e)}"
        )

# =========================
# TEXT FOOD HANDLER
# =========================

@dp.message(F.text)
async def text_food_handler(message: Message):

    try:

        if not is_allowed(message):
            return

        text_input = message.text.strip()

        if text_input.startswith("/"):
            return

        prompt = f"""
Пользователь написал:

{text_input}

Определи:
- название продукта
- примерный вес

НЕ считай калории.

Ответ строго JSON:

{{
  "name": "",
  "weight_g": 0
}}
"""

        text = analyze_product(
            prompt,
            None
        )

        data = json.loads(text)

        name = data["name"]
        weight = float(data["weight_g"])

        nutrition = get_nutrition_data(
            name,
            weight
        )

        if not nutrition:

            nutrition = {
                "calories_per_100g": "?",
                "total_calories": "?"
            }

        if nutrition["total_calories"] != "?":

            save_calories(
                message,
                nutrition["total_calories"]
            )

        answer = f"""
<b>{name}</b>

Вес: ~{round(weight)} г

Калории на 100 г:
~{nutrition['calories_per_100g']} ккал

Калории всего продукта:
~{nutrition['total_calories']} ккал
"""

        await message.answer(answer)

    except Exception as e:

        traceback.print_exc()

        await message.answer(
            f"Ошибка:\n{str(e)}"
        )

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

    await bot.set_webhook(
        WEBHOOK_URL
    )

    asyncio.create_task(
        daily_report_loop()
    )

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