import os
import json
import tempfile

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from dotenv import load_dotenv

import google.generativeai as genai
from PIL import Image

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

ALLOWED_USER_ID = 456174801

genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel("models/gemini-1.5-flash")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()


@dp.message(F.photo)
async def photo_handler(message: Message):

    if message.from_user.id != ALLOWED_USER_ID:
        return

    photo = message.photo[-1]

    file = await bot.get_file(photo.file_id)

    with tempfile.NamedTemporaryFile(suffix=".jpg") as temp:

        await bot.download_file(file.file_path, temp.name)

        image = Image.open(temp.name)

        prompt = """
        Ты анализатор питания.

        Определи:
        - название блюда
        - примерный вес
        - калории
        - белки
        - жиры
        - углеводы

        Ответ строго JSON:

        {
          "name": "",
          "weight_g": 0,
          "calories": 0,
          "protein": 0,
          "fat": 0,
          "carbs": 0
        }
        """

        response = model.generate_content([prompt, image])

        text = (
            response.text
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )

        try:
            data = json.loads(text)

            answer = f"""
<b>{data['name']}</b>

Вес: ~{data['weight_g']} г
Калории: ~{data['calories']} ккал

Б: {data['protein']} г
Ж: {data['fat']} г
У: {data['carbs']} г
"""

            await message.answer(answer)

        except Exception:
            await message.answer(text)


if __name__ == "__main__":
    dp.run_polling(bot)