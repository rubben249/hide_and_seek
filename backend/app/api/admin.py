"""
Admin / developer panel API.

All endpoints require the X-Admin-Password header matching ADMIN_PASSWORD in .env.
These are intentionally REST (not WS) so the admin page can do simple polling.

GET  /api/admin/status          — server overview (sessions, rooms)
GET  /api/admin/rooms           — list all active rooms with full detail
GET  /api/admin/room/{room_id}  — full game state for spectating (all hands visible)
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Import runtime state lazily to avoid circular imports
def _ws_state() -> tuple[dict, dict]:
    from app.api.websocket import _rooms, _room_timer_tasks
    return _rooms, _room_timer_tasks


def _sessions() -> dict:
    from app.core.security import get_all_sessions
    return get_all_sessions()


def _require_admin(request: Request) -> None:
    provided = request.headers.get("X-Admin-Password", "")
    if provided != settings.admin_password:
        raise HTTPException(status_code=403, detail="Invalid admin password")


@router.get("/status")
def admin_status(request: Request) -> dict[str, Any]:
    _require_admin(request)
    rooms, timer_tasks = _ws_state()
    sessions = _sessions()

    active_rooms = [r for r in rooms.values() if not r.is_idle()]
    in_game = [r for r in active_rooms if r.state is not None]

    return {
        "server_time": time.time(),
        "sessions_active": len(sessions),
        "rooms_total": len(rooms),
        "rooms_active": len(active_rooms),
        "rooms_in_game": len(in_game),
        "timer_tasks_running": len(timer_tasks),
        "sessions": [
            {
                "token_prefix": tok[:8],
                "player_name": s.player_name,
                "ip": s.ip,
                "age_seconds": round(time.monotonic() - s.created_at, 0),
            }
            for tok, s in sessions.items()
        ],
    }


@router.get("/rooms")
def admin_rooms(request: Request) -> dict[str, Any]:
    _require_admin(request)
    rooms, _ = _ws_state()

    result = []
    for room in rooms.values():
        players_info = [
            {
                "player_id": rp.player_id,
                "player_name": rp.player_name,
                "team_id": rp.team_id,
                "connected": rp.connected,
                "skip_turns": rp.skip_turns,
                "disconnected_at": rp.disconnected_at,
            }
            for rp in room.players
        ]

        state_summary = None
        if room.state:
            s = room.state
            state_summary = {
                "phase": s.phase.value,
                "turn_number": s.turn_number,
                "deck_remaining": len(s.deck),
                "active_player": s.active_player().name if s.players else None,
                "is_finished": s.is_finished(),
                "result": s.result.model_dump() if s.result else None,
                "timer": {
                    "game_start": s.timer.game_start,
                    "game_elapsed": round(time.time() - s.timer.game_start, 1) if s.timer.game_start else None,
                    "turn_active": s.timer.turn_active,
                    "player_time_used": {k: round(v, 1) for k, v in s.timer.player_time_used.items()},
                },
            }

        result.append({
            "room_id": room.id,
            "room_name": room.name,
            "mode": room.mode.value,
            "has_password": bool(room.password),
            "max_players": room.max_players,
            "created_at": room.created_at,
            "idle_seconds": round(time.monotonic() - room.last_activity, 0),
            "players": players_info,
            "state_summary": state_summary,
        })

    return {"rooms": result}


@router.get("/room/{room_id}")
def admin_room_detail(room_id: str, request: Request) -> dict[str, Any]:
    """Full game state including all players' hands — only for admin spectating."""
    _require_admin(request)
    rooms, _ = _ws_state()

    room = rooms.get(room_id.upper())
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")

    if room.state is None:
        return {"room_id": room.id, "room_name": room.name, "state": None}

    s = room.state
    players_full = []
    for p in s.players:
        rp = room.get_room_player_for_game_id(p.id)
        players_full.append({
            "id": p.id,
            "name": p.name,
            "type": p.type.value,
            "connected": rp.connected if rp else True,
            "skip_turns": rp.skip_turns if rp else 0,
            "team": p.team.value if p.team else None,
            "position": p.position,
            "home_position": p.home_position,
            "total_steps": p.total_steps,
            "hand": list(p.hand),           # all cards visible in admin
            "recruited": list(p.recruited),
            "discards_used": p.discards_used,
            "max_discards": p.max_discards,
            "eliminated": p.eliminated,
        })

    pending = None
    if s.pending_play:
        pending = {
            "face_up": s.pending_play.face_up,
            "face_down": s.pending_play.face_down,
            "actor_id": s.pending_play.actor_id,
            "target_id": s.pending_play.target_id,
        }

    timer_config = s.timer_config
    timer = {
        "game_start": s.timer.game_start,
        "game_elapsed_s": round(time.time() - s.timer.game_start, 1) if s.timer.game_start else None,
        "turn_start": s.timer.turn_start,
        "turn_active": s.timer.turn_active,
        "player_time_used": {k: round(v, 1) for k, v in s.timer.player_time_used.items()},
        "player_time_limit": timer_config.get("player_time_limit"),
        "game_time_limit": timer_config.get("game_time_limit"),
        "turn_time_limit": timer_config.get("turn_time_limit"),
    }

    return {
        "room_id": room.id,
        "room_name": room.name,
        "mode": room.mode.value,
        "state": {
            "id": s.id,
            "phase": s.phase.value,
            "turn_number": s.turn_number,
            "board_size": s.board_size,
            "deck_remaining": len(s.deck),
            "deck_top5": s.deck[:5],
            "active_player_index": s.active_player_index,
            "active_player_name": s.active_player().name if s.players else None,
            "players": players_full,
            "pending_play": pending,
            "result": s.result.model_dump() if s.result else None,
            "timer": timer,
        },
    }
