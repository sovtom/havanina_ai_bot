import os
import json
import tempfile
import asyncio
import time

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from dotenv import load_dotenv

from google import genai
from PIL import Image


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

ALLOWED_USER_ID = 456174801

client = genai.Client(api_key=GEMINI_API_KEY)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()

last_request_time = {}


@dp.message(F.photo)
async def photo_handler(message: Message):

    user_id = message.from_user.id
    now = time.time()

    # Ограничение запросов
    if user_id in last_request_time:
        if now - last_request_time[user_id] < 20:
            await message.answer(
                "Подожди 20 секунд перед следующим фото."
            )
            return

    last_request_time[user_id] = now

    # Только твой доступ
    if user_id != ALLOWED_USER_ID:
        return

    try:

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

            try:

                response = client.models.generate_content(
                    model="gemini-2.0-flash-lite",
                    contents=[prompt, image]
                )

            except Exception as e:

                print(e)

                await message.answer(
                    "Лимит Gemini временно достигнут.\nПопробуй через пару минут."
                )

                return

            text = (
                response.text
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

                await message.answer(
                    f"Ошибка обработки ответа:\n\n{text}"
                )

    except Exception as e:

        print(e)

        await message.answer(
            "Произошла ошибка при обработке фото."
        )


async def main():

    await bot.delete_webhook(drop_pending_updates=True)

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())