import asyncio
import json
import random
import string
from concurrent.futures import ThreadPoolExecutor

import aiohttp
from yandex_music import Client, Track

executor = ThreadPoolExecutor(max_workers=4)


async def create_ynison_ws(ya_token: str, ws_proto: dict, session: aiohttp.ClientSession) -> dict:
    async with session.ws_connect(
        "wss://ynison.music.yandex.ru/redirector.YnisonRedirectService/GetRedirectToYnison",
        headers={
            "Sec-WebSocket-Protocol": f"Bearer, v2, {json.dumps(ws_proto)}",
            "Origin": "http://music.yandex.ru",
            "Authorization": f"OAuth {ya_token}",
        },
    ) as ws:
        response = await ws.receive()
        return json.loads(response.data)


def generate_device_id(length: int = 16) -> str:
    return ''.join(random.choices(string.ascii_lowercase, k=length))


async def get_current_track_beta(ya_token: str, session: aiohttp.ClientSession):
    device_id = generate_device_id()
    ws_proto = {
        "Ynison-Device-Id": device_id,
        "Ynison-Device-Info": json.dumps({"app_name": "Chrome", "type": 1}),
    }
    data = await create_ynison_ws(ya_token, ws_proto, session)

    ws_proto["Ynison-Redirect-Ticket"] = data["redirect_ticket"]

    payload = {
        "update_full_state": {
            "player_state": {
                "player_queue": {
                    "current_playable_index": -1,
                    "entity_id": "",
                    "entity_type": "VARIOUS",
                    "playable_list": [],
                    "options": {"repeat_mode": "NONE"},
                    "entity_context": "BASED_ON_ENTITY_BY_DEFAULT",
                    "version": {"device_id": device_id, "version": 9021243204784341000, "timestamp_ms": 0},
                    "from_optional": "",
                },
                "status": {
                    "duration_ms": 0,
                    "paused": True,
                    "playback_speed": 1,
                    "progress_ms": 0,
                    "version": {"device_id": device_id, "version": 8321822175199937000, "timestamp_ms": 0},
                },
            },
            "device": {
                "capabilities": {"can_be_player": True, "can_be_remote_controller": False, "volume_granularity": 16},
                "info": {
                    "device_id": device_id,
                    "type": "WEB",
                    "title": "Chrome Browser",
                    "app_name": "Chrome",
                },
                "volume_info": {"volume": 0},
                "is_shadow": True,
            },
            "is_currently_active": False,
        },
        "rid": "ac281c26-a047-4419-ad00-e4fbfda1cba3",
        "player_action_timestamp_ms": 0,
        "activity_interception_type": "DO_NOT_INTERCEPT_BY_DEFAULT",
    }

    async with session.ws_connect(
            f"wss://{data['host']}/ynison_state.YnisonStateService/PutYnisonState",
            headers={
                "Sec-WebSocket-Protocol": f"Bearer, v2, {json.dumps(ws_proto)}",
                "Origin": "http://music.yandex.ru",
                "Authorization": f"OAuth {ya_token}",
            }
    ) as ws:
        await ws.send_str(json.dumps(payload))
        response = await ws.receive()
        ynison = json.loads(response.data)

    track = ynison["player_state"]["player_queue"]["playable_list"][
        ynison["player_state"]["player_queue"]["current_playable_index"]
    ]

    return {
        "paused": ynison["player_state"]["status"]["paused"],
        "duration_ms": ynison["player_state"]["status"]["duration_ms"],
        "progress_ms": ynison["player_state"]["status"]["progress_ms"],
        "entity_id": ynison["player_state"]["player_queue"]["entity_id"],
        "entity_type": ynison["player_state"]["player_queue"]["entity_type"],
        "track": track["playable_id"],
    }


def _sync_get_track_info(ya_token: str, track_id: str) -> tuple[Track, str]:
    client = Client(ya_token).init()
    tracks = client.tracks([track_id])
    track = tracks[0]
    info = track.get_specific_download_info('mp3', 192)
    return track, info.get_direct_link()


def _sync_search_tracks(ya_token: str, query: str, limit: int) -> list[Track]:
    client = Client(ya_token).init()
    search_result = client.search(query, type_="track")

    if not search_result or not search_result.tracks:
        return []

    return search_result.tracks.results[:limit]


async def get_current_track(ya_token: str, session: aiohttp.ClientSession) -> tuple[Track, str]:
    track_data = await get_current_track_beta(ya_token, session)
    track_id = track_data["track"]

    loop = asyncio.get_event_loop()
    track, download_url = await loop.run_in_executor(
        executor,
        _sync_get_track_info,
        ya_token,
        track_id
    )

    return track, download_url


async def search_tracks(ya_token: str, query: str, limit: int = 3) -> list[Track]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        executor,
        _sync_search_tracks,
        ya_token,
        query,
        limit
    )
