import asyncio
from os import getenv

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, \
    InlineQueryResultCachedAudio, BufferedInputFile
from yandex_music import Track

import YmClient
from db import UserRepository

TOKEN = getenv("BOT_TOKEN")
DB_URL = getenv("DATABASE_URL")

dp = Dispatcher()
bot = Bot(token=TOKEN)
user_repository = UserRepository(DB_URL)

TMP_DIR = "./tmp"
CACHE_CHANNEL_ID = getenv("CACHE_CHANNEL_ID", "-1003800975838")

http_session = None


@dp.message(Command("start"))
async def command_start_handler(message: Message) -> None:
    await message.answer(
        ("Привет! Я помогу тебе отображать текущий проигрываемый трек в яндекс музыке.\n"
         "Для этого мне потребуется твой Oauth токен\n\n"
         "Ты можешь мне доверять, потому что я не буду использовать для личных целей, а исходный код бота открыт\n"
         "Если хочешь получить подробную инструкцию напиши /help\n\n"
         "Также как получить токен расписано в инструкции https://github.com/MarshalX/yandex-music-api/discussions/513#discussioncomment-2729781\n\n"
         "Как получишь токен пиши /token &lt;Oauth токен&gt;\n\n"
         "<b>Использование:</b>\n"
         "• @ya_music_dobro_bot –> отправить текущий трек\n"
         "• @ya_music_dobro_bot Metallica –> найти треки по запросу"),
        parse_mode="HTML"
    )

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


async def get_http_session() -> aiohttp.ClientSession:
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession()
    return http_session


async def download_file(url: str) -> bytes:
    session = await get_http_session()
    async with session.get(url) as resp:
        resp.raise_for_status()
        return await resp.read()


async def upload_track_to_cache(track) -> InlineQueryResultCachedAudio | None:
    try:
        track_id = str(track.id)
        info = track.get_specific_download_info('mp3', 192)
        if not info:
            return None

        download_url = info.get_direct_link()

        session = await get_http_session()
        async with session.get(download_url) as resp:
            if resp.status != 200:
                return None
            audio_data = await resp.read()

        thumb_data = None
        if track.cover_uri:
            try:
                cover_url = track.get_cover_url(size='200x200')
                async with session.get(cover_url) as resp:
                    if resp.status == 200:
                        thumb_data = await resp.read()
            except Exception as e:
                print(f"Failed to download cover for {track_id}: {e}")

        audio_file = BufferedInputFile(audio_data, filename=f"{track_id}.mp3")
        thumb_file = BufferedInputFile(thumb_data, filename="thumb.jpg") if thumb_data else None

        msg = await bot.send_audio(
            chat_id=CACHE_CHANNEL_ID,
            audio=audio_file,
            title=track.title,
            performer=", ".join(track.artists_name()) if track.artists else "Unknown",
            duration=track.duration_ms // 1000 if track.duration_ms else None,
            thumbnail=thumb_file,
        )

        user_repository.set_cached_file_id(track_id, msg.audio.file_id)

        return InlineQueryResultCachedAudio(
            id=track_id,
            audio_file_id=msg.audio.file_id,
        )
    except Exception as e:
        print(f"Error uploading track {track.id}: {e}")
        return None


async def handle_search_query(query: InlineQuery, user_token: str, search_query: str):
    tracks = await YmClient.search_tracks(user_token, search_query, limit=3)

    if not tracks:
        await query.answer(
            create_inline_query_with_text(
                query.id,
                "Ничего не найдено",
                f"По запросу '{search_query}' треков не найдено"
            ),
            is_personal=True,
            cache_time=0
        )
        return

    results = []
    tracks_to_upload = []

    for track in tracks:
        track_id = str(track.id)
        file_id = user_repository.get_cached_file_id(track_id)

        if file_id:
            results.append(InlineQueryResultCachedAudio(
                id=track_id,
                audio_file_id=file_id,
            ))
        else:
            tracks_to_upload.append(track)

    if tracks_to_upload:
        upload_tasks = [upload_track_to_cache(track) for track in tracks_to_upload]
        uploaded_results = await asyncio.gather(*upload_tasks)
        results.extend([r for r in uploaded_results if r is not None])

    if not results:
        await query.answer(
            create_inline_query_with_text(
                query.id,
                "Треки недоступны",
                "Найденные треки недоступны для загрузки."
            ),
            is_personal=True,
            cache_time=0
        )
        return

    await query.answer(results, is_personal=True, cache_time=30)


async def handle_current_track(query: InlineQuery, user_token: str):
    session = await get_http_session()
    track, download_url = await YmClient.get_current_track(user_token, session)

    if track is None:
        await query.answer(
            create_inline_query_with_text(query.id, "Ошибка!", "Сейчас ничего не играет!"),
            is_personal=True,
            cache_time=0
        )
        return

    track_id = str(track.id)
    file_id = user_repository.get_cached_file_id(track_id)

    if file_id:
        await query.answer(
            [InlineQueryResultCachedAudio(
                id=query.id,
                audio_file_id=file_id,
            )],
            is_personal=True,
            cache_time=0
        )
        return

    cover_url = track.get_cover_url()
    audio_data, cover_data = await asyncio.gather(
        download_file(download_url),
        download_file(cover_url)
    )

    msg = await bot.send_audio(
        chat_id=CACHE_CHANNEL_ID,
        audio=BufferedInputFile(audio_data, filename=f"{track_id}.mp3"),
        thumbnail=BufferedInputFile(cover_data, filename="cover.jpg"),
        title=format_track_name(track),
    )

    user_repository.set_cached_file_id(track_id, msg.audio.file_id)

    await query.answer(
        [InlineQueryResultCachedAudio(
            id=query.id,
            audio_file_id=msg.audio.file_id,
        )],
        is_personal=True,
        cache_time=0
    )


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
    search_query = query.query.strip()

    if search_query:
        try:
            await handle_search_query(query, user_token, search_query)
        except Exception as e:
            print(f"Search error: {e}")
            await query.answer(
                create_inline_query_with_text(
                    query.id,
                    "Ошибка поиска",
                    "Не удалось выполнить поиск. Попробуйте позже."
                ),
                is_personal=True,
                cache_time=0
            )
    else:
        await handle_current_track(query, user_token)


async def main() -> None:
    print("Bot started")

    try:
        await dp.start_polling(bot)
    finally:
        global http_session

        if http_session and not http_session.closed:
            await http_session.close()

        user_repository.close()


if __name__ == "__main__":
    asyncio.run(main())
