import asyncio
import os
from os import getenv
from uuid import uuid4

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, FSInputFile, \
    InlineQueryResultPhoto, InlineQueryResultAudio, InlineQueryResultCachedAudio
from aiogram.utils.keyboard import InlineKeyboardBuilder
from yandex_music import Track

import YmClient
from db import UserRepository

TOKEN = getenv("BOT_TOKEN")
DB_URL = getenv("DATABASE_URL")

dp = Dispatcher()
bot = Bot(token=TOKEN)
user_repository = UserRepository(DB_URL)

TMP_DIR = "./tmp"
CACHE_CHANNEL_ID = "-1003800975838"


@dp.message(Command("start"))
async def command_start_handler(message: Message) -> None:
    await message.answer(
        ("Привет! Я помогу тебе отображать текущий проигрываемый трек в яндекс музыке.\n"
         "Для этого мне потребуется твой Oauth токен\n\n"
         "Ты можешь мне доверять, потому что я не буду использовать для личных целей, а исходный код бота открыт\n"
         "Если хочешь получить подробную инструкцию напиши /help\n\n"
         "Также как получить токен расписано в инструкции https://github.com/MarshalX/yandex-music-api/discussions/513#discussioncomment-2729781\n\n"
         "Как получишь токен пиши /token <Oauth токен>"))

@dp.message(Command("help"))
async def command_help_handler(message: Message) -> None:
    await message.answer(
        ("<b>ИНСТРУКЦИЯ ПО ПОЛУЧЕНИЮ ТОКЕНА</b>\n\n"
         "1) Перейди на https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d и авторизуйся\n\n"
         "2) Когда перейдешь на страницу яндекс музыки скопируй URL. "
         "Он будет формата https://music.yandex.ru/#access_token=ABCDEF12345&token_type=bearer&expires_in=31448199&cid=123\n\n"
         "3) Скопируй боту то что находится после access_token и до &, затем отправь боту команду /token ABCDEF12345 с твоим токеном"
         ),
        parse_mode="HTML",
    )


@dp.message(Command("token"))
async def command_token_handler(message: Message) -> None:
    try:
        token = message.text.split()[1]
        await message.answer("Спасибо! Теперь можешь пользоваться ботом! Чтобы отправить текущий трек напиши @ya_music_dobro_bot в поле сообщения в любом чате и дождись загрузки трека")
        await message.delete()
        user_id = message.from_user.id
        user_repository.insert(user_id, token)
    except IndexError:
        await message.answer("Формат сообщения: /token <Oauth токен>")


def create_inline_query_with_text(query_id: str, title: str, message: str) -> list[InlineQueryResultArticle]:
    return [InlineQueryResultArticle(
        id=query_id,
        title=title,
        description=message,
        input_message_content=InputTextMessageContent(
            message_text=message,
            parse_mode="HTML"
        ),
    )]


def format_track_name(track: Track) -> str:
    return f"""{track.title} - {",".join(track.artists_name())}"""


async def download_cover(url: str) -> str:
    filename = f"{uuid4().hex}.jpg"
    path = os.path.join(TMP_DIR, filename)

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            with open(path, "wb") as f:
                f.write(await resp.read())

    return path

async def download_music(url: str) -> str:
    filename = f"{uuid4().hex}.mp3"
    path = os.path.join(TMP_DIR, filename)

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            with open(path, "wb") as f:
                f.write(await resp.read())

    return path

@dp.inline_query()
async def inline_handler(query: InlineQuery):
    user_id = query.from_user.id

    user_data = user_repository.get_by_user_id(user_id)

    if user_data is None:
        await query.answer(
            create_inline_query_with_text(query.id, "Ошибка!", "Вы еще не зарегестрированы в боте! Перейдите в ЛС"),
            is_personal=True,
            cache_time=0
        )
        return

    user_token = user_data.get("token")
    track, download_url = await YmClient.get_current_track(user_token)

    if track is None:
        await query.answer(
            create_inline_query_with_text(query.id, "Ошибка!", "Сейчас ничего не играет!"),
            is_personal=True,
            cache_time=0
        )
        return

    cover_path, track_file = await asyncio.gather(download_cover(track.get_cover_url()), download_music(download_url))

    msg = await bot.send_audio(
        chat_id=CACHE_CHANNEL_ID,
        audio=FSInputFile(track_file),
        thumbnail=FSInputFile(cover_path),
        title=format_track_name(track),
    )

    await query.answer(
        [InlineQueryResultCachedAudio(
            id=query.id,
            audio_file_id=msg.audio.file_id,
        )],
        is_personal=True,
        cache_time=0
    )

    os.remove(cover_path)
    os.remove(track_file)
    return


async def main() -> None:
    print("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
