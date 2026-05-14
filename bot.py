import os
import json
import base64
import tempfile
import time

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, Update
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from dotenv import load_dotenv

from openai import OpenAI


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
RAILWAY_STATIC_URL = os.getenv("RAILWAY_STATIC_URL")

ALLOWED_USER_ID = 456174801

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{RAILWAY_STATIC_URL}{WEBHOOK_PATH}"

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()

app = FastAPI()

last_request_time = {}


@dp.message(F.photo)
async def photo_handler(message: Message):

    user_id = message.from_user.id
    now = time.time()

    if user_id in last_request_time:
        if now - last_request_time[user_id] < 20:
            await message.answer(
                "Подожди 20 секунд перед следующим фото."
            )
            return

    last_request_time[user_id] = now

    if user_id != ALLOWED_USER_ID:
        return

    try:

        photo = message.photo[-1]

        file = await bot.get_file(photo.file_id)

        with tempfile.NamedTemporaryFile(suffix=".jpg") as temp:

            await bot.download_file(file.file_path, temp.name)

            with open(temp.name, "rb") as image_file:
                base64_image = base64.b64encode(
                    image_file.read()
                ).decode("utf-8")

            completion = client.chat.completions.create(
                model="google/gemma-3-27b-it:free",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": """
                                Определи еду на фото.

                                Верни строго JSON:

                                {
                                  "name": "",
                                  "weight_g": 0,
                                  "calories": 0,
                                  "protein": 0,
                                  "fat": 0,
                                  "carbs": 0
                                }
                                """
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ]
            )

            text = completion.choices[0].message.content

            text = (
                text
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

            try:

                data = json.loads(text)

                answer = f"""
<b>{data.get('name', 'Неизвестное блюдо')}</b>

Вес: ~{data.get('weight_g', '?')} г
Калории: ~{data.get('calories', '?')} ккал

Б: {data.get('protein', '?')} г
Ж: {data.get('fat', '?')} г
У: {data.get('carbs', '?')} г
"""

                await message.answer(answer)

            except Exception:

                await message.answer(text)

    except Exception as e:

        print(e)

        await message.answer(
            "Ошибка обработки фото."
        )


@app.on_event("startup")
async def startup():

    await bot.set_webhook(WEBHOOK_URL)


@app.on_event("shutdown")
async def shutdown():

    await bot.delete_webhook()


@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):

    data = await request.json()

    update = Update.model_validate(data)

    await dp.feed_update(bot, update)

    return {"ok": True}