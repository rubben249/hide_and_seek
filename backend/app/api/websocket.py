"""
WebSocket handler for online multiplayer mode.

Security flow:
  1. Client connects to /ws
  2. Client must send {"type":"auth","password":"...","player_name":"..."} within 5 seconds
  3. Server validates password (rate-limited per IP)
  4. On success: issues {"type":"auth_ok","token":"<UUID>"}
  5. All subsequent messages must include {"token":"..."}
  6. Client can create/join rooms and play
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.security import (
    check_rate_limit,
    create_session,
    invalidate_session,
    reset_rate_limit,
    validate_password,
    validate_session,
)
from app.game.engine import (
    check_end_conditions,
    discard_card,
    play_cards,
    recruit,
)
from app.game.models import GameMode, GamePhase, GameState, Player, init_game

# All timing constants come from config — nothing hardcoded here


# ---------------------------------------------------------------------------
# Room management
# ---------------------------------------------------------------------------

VALID_REACTIONS = {
    "good_play", "haha", "wow", "fire", "cry", "angry", "celebrate", "well_played"
}

REACTION_EMOJI = {
    "good_play": "👍",
    "haha": "😂",
    "wow": "😮",
    "fire": "🔥",
    "cry": "😢",
    "angry": "😡",
    "celebrate": "🎉",
    "well_played": "👏",
}


@dataclass
class RoomPlayer:
    token: str
    player_id: str
    player_name: str
    ws: WebSocket
    team_id: str | None = None  # set when game starts for team modes


@dataclass
class Room:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8].upper())
    mode: GameMode = GameMode.LOCAL_1V1
    max_players: int = 2
    players: list[RoomPlayer] = field(default_factory=list)
    state: GameState | None = None
    created_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)

    def is_full(self) -> bool:
        return len(self.players) >= self.max_players

    def is_idle(self) -> bool:
        return time.monotonic() - self.last_activity > settings.room_idle_timeout

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def get_player(self, token: str) -> RoomPlayer | None:
        return next((p for p in self.players if p.token == token), None)


_rooms: dict[str, Room] = {}
_room_timer_tasks: dict[str, asyncio.Task] = {}  # room_id → background timer coroutine


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}  # token → ws

    def register(self, token: str, ws: WebSocket) -> None:
        self._connections[token] = ws

    def unregister(self, token: str) -> None:
        self._connections.pop(token, None)

    async def send(self, token: str, data: dict) -> None:
        ws = self._connections.get(token)
        if ws:
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                pass

    async def broadcast_room(self, room: Room, data: dict) -> None:
        for rp in room.players:
            await self.send(rp.token, data)

    async def broadcast_team(self, room: Room, team_id: str, data: dict) -> None:
        for rp in room.players:
            if rp.team_id == team_id:
                await self.send(rp.token, data)


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Main WebSocket handler
# ---------------------------------------------------------------------------

async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    client_ip = websocket.client.host if websocket.client else "unknown"
    token: str | None = None

    try:
        # --- Phase 1: Authentication (must happen within ws_auth_timeout seconds) ---
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=settings.ws_auth_timeout)
        except asyncio.TimeoutError:
            await _send_error(websocket, "auth_timeout", "Authentication timeout")
            await websocket.close(code=4001)
            return

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await _send_error(websocket, "invalid_json", "Invalid JSON")
            await websocket.close(code=4002)
            return

        if msg.get("type") != "auth":
            await _send_error(websocket, "auth_required", "First message must be auth")
            await websocket.close(code=4003)
            return

        if not check_rate_limit(client_ip):
            await _send_error(websocket, "rate_limited", "Too many attempts. Try again in 1 minute.")
            await websocket.close(code=4029)
            return

        password = msg.get("password", "")
        if not validate_password(password):
            await _send_error(websocket, "auth_failed", "Invalid password")
            await websocket.close(code=4004)
            return

        reset_rate_limit(client_ip)
        player_name = str(msg.get("player_name", "Player"))[:32]
        token = create_session(client_ip, player_name)
        manager.register(token, websocket)

        await websocket.send_text(json.dumps({
            "type": "auth_ok",
            "token": token,
            "player_name": player_name,
        }))

        # --- Phase 2: Lobby / game messages ---
        async for raw_msg in _receive_loop(websocket):
            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                await _send_error(websocket, "invalid_json", "Invalid JSON")
                continue

            # Validate session token on every message
            msg_token = msg.get("token", "")
            session = validate_session(msg_token)
            if session is None or msg_token != token:
                await _send_error(websocket, "unauthorized", "Invalid or expired session token")
                continue

            msg_type = msg.get("type", "")
            try:
                await _handle_message(websocket, token, session.player_name, msg_type, msg)
            except Exception as e:
                await _send_error(websocket, "server_error", str(e))

    except WebSocketDisconnect:
        pass
    finally:
        if token:
            manager.unregister(token)
            invalidate_session(token)
            await _handle_disconnect(token)


async def _receive_loop(ws: WebSocket):
    """Yield messages from a websocket until disconnect."""
    try:
        while True:
            yield await ws.receive_text()
    except WebSocketDisconnect:
        return


# ---------------------------------------------------------------------------
# Message handlers
# ---------------------------------------------------------------------------

async def _handle_message(
    ws: WebSocket,
    token: str,
    player_name: str,
    msg_type: str,
    msg: dict,
) -> None:
    if msg_type == "create_room":
        await _handle_create_room(ws, token, player_name, msg)
    elif msg_type == "join_room":
        await _handle_join_room(ws, token, player_name, msg)
    elif msg_type == "leave_room":
        await _handle_leave_room(ws, token)
    elif msg_type == "list_rooms":
        await _handle_list_rooms(ws)
    elif msg_type == "start_game":
        await _handle_start_game(ws, token, msg)
    elif msg_type == "discard":
        await _handle_discard(ws, token, msg)
    elif msg_type == "play_cards":
        await _handle_play(ws, token, msg)
    elif msg_type == "recruit":
        await _handle_recruit(ws, token, msg)
    elif msg_type == "turn_ready":
        await _handle_turn_ready(ws, token)
    elif msg_type == "chat_all":
        await _handle_chat_all(ws, token, player_name, msg)
    elif msg_type == "chat_team":
        await _handle_chat_team(ws, token, player_name, msg)
    elif msg_type == "reaction":
        await _handle_reaction(ws, token, player_name, msg)
    elif msg_type == "ping":
        await ws.send_text(json.dumps({"type": "pong"}))
    else:
        await _send_error(ws, "unknown_type", f"Unknown message type: {msg_type}")


async def _handle_create_room(ws: WebSocket, token: str, player_name: str, msg: dict) -> None:
    if len(_rooms) >= settings.max_rooms:
        await _send_error(ws, "rooms_full", "Server has reached maximum room capacity")
        return

    mode_str = msg.get("mode", "local_1v1")
    try:
        mode = GameMode(mode_str)
    except ValueError:
        await _send_error(ws, "invalid_mode", f"Unknown mode: {mode_str}")
        return

    max_players = {
        GameMode.LOCAL_1V1: 2,
        GameMode.LOCAL_2V2: 4,
        GameMode.LOCAL_2V1: 3,
        GameMode.LOCAL_FFA: 4,
        GameMode.ONLINE: 2,
    }.get(mode, 2)

    room = Room(mode=mode, max_players=max_players)
    room_player = RoomPlayer(token=token, player_id=str(uuid.uuid4()), player_name=player_name, ws=ws)
    room.players.append(room_player)
    _rooms[room.id] = room

    await ws.send_text(json.dumps({
        "type": "room_created",
        "room_id": room.id,
        "mode": mode.value,
        "max_players": max_players,
        "players": [{"name": p.player_name} for p in room.players],
    }))


async def _handle_join_room(ws: WebSocket, token: str, player_name: str, msg: dict) -> None:
    room_id = msg.get("room_id", "").upper()
    room = _rooms.get(room_id)
    if room is None:
        await _send_error(ws, "room_not_found", "Room not found")
        return
    if room.is_full():
        await _send_error(ws, "room_full", "Room is full")
        return
    if room.get_player(token):
        await _send_error(ws, "already_in_room", "You are already in this room")
        return

    room_player = RoomPlayer(token=token, player_id=str(uuid.uuid4()), player_name=player_name, ws=ws)
    room.players.append(room_player)
    room.touch()

    player_list = [{"name": p.player_name} for p in room.players]
    await manager.broadcast_room(room, {
        "type": "player_joined",
        "room_id": room.id,
        "players": player_list,
        "ready": room.is_full(),
    })


async def _handle_leave_room(ws: WebSocket, token: str) -> None:
    room = _find_room_by_token(token)
    if room is None:
        return
    room.players = [p for p in room.players if p.token != token]
    if not room.players:
        _cancel_room_timer(room.id)
        del _rooms[room.id]
    else:
        await manager.broadcast_room(room, {
            "type": "player_left",
            "room_id": room.id,
            "players": [{"name": p.player_name} for p in room.players],
        })


async def _handle_list_rooms(ws: WebSocket) -> None:
    visible = [
        {"room_id": r.id, "mode": r.mode.value, "players": len(r.players), "max_players": r.max_players}
        for r in _rooms.values()
        if not r.is_idle()
    ]
    await ws.send_text(json.dumps({"type": "room_list", "rooms": visible}))


async def _handle_start_game(ws: WebSocket, token: str, msg: dict) -> None:
    room = _find_room_by_token(token)
    if room is None:
        await _send_error(ws, "not_in_room", "You are not in a room")
        return
    if not room.is_full():
        await _send_error(ws, "not_enough_players", "Waiting for more players")
        return
    if room.state is not None:
        await _send_error(ws, "game_started", "Game already started")
        return

    player_names = [p.player_name for p in room.players]
    state = init_game(mode=room.mode, player_names=player_names)

    # Map room player ids to game player ids and assign team info for chat
    for rp, gp in zip(room.players, state.players):
        rp.player_id = gp.id
        rp.team_id = gp.team.value if gp.team else None

    room.state = state
    room.touch()

    await manager.broadcast_room(room, {
        "type": "game_started",
        "state": _safe_state(state),
    })

    # Start background timer enforcement task for this room
    task = asyncio.create_task(_room_timer_task(room.id))
    _room_timer_tasks[room.id] = task


async def _handle_discard(ws: WebSocket, token: str, msg: dict) -> None:
    room, rp = _get_room_and_player(ws, token)
    if room is None or rp is None:
        return
    state = room.state
    if state is None:
        await _send_error(ws, "no_game", "Game not started")
        return

    card_name = msg.get("card_name", "")
    state, err = discard_card(state, rp.player_id, card_name)
    if err:
        await _send_error(ws, "discard_error", err)
        return

    room.state = state
    room.touch()
    await manager.broadcast_room(room, {"type": "game_state", "state": _safe_state(state)})


async def _handle_play(ws: WebSocket, token: str, msg: dict) -> None:
    room, rp = _get_room_and_player(ws, token)
    if room is None or rp is None:
        return
    state = room.state
    if state is None:
        await _send_error(ws, "no_game", "Game not started")
        return

    face_up = msg.get("face_up", "")
    face_down = msg.get("face_down", "")
    target_id = msg.get("target_id")

    _record_turn_time(state, rp.player_id)
    state, err = play_cards(state, rp.player_id, face_up, face_down, target_id)
    if err:
        await _send_error(ws, "play_error", err)
        return

    room.state = state
    room.touch()
    await manager.broadcast_room(room, {"type": "game_state", "state": _safe_state(state)})


async def _handle_recruit(ws: WebSocket, token: str, msg: dict) -> None:
    room, rp = _get_room_and_player(ws, token)
    if room is None or rp is None:
        return
    state = room.state
    if state is None:
        await _send_error(ws, "no_game", "Game not started")
        return

    choice = msg.get("choice", "")
    _record_turn_time(state, rp.player_id)
    state, err = recruit(state, rp.player_id, choice)
    if err:
        await _send_error(ws, "recruit_error", err)
        return

    state = check_end_conditions(state)
    room.state = state
    room.touch()
    await manager.broadcast_room(room, {"type": "game_state", "state": _safe_state(state)})

    if state.is_finished():
        await manager.broadcast_room(room, {"type": "game_over", "result": state.result.model_dump() if state.result else {}})


async def _handle_turn_ready(ws: WebSocket, token: str) -> None:
    """Client signals animations are done — start the turn clock now."""
    room, rp = _get_room_and_player(ws, token)
    if room is None or rp is None or room.state is None:
        return

    state = room.state
    if state.is_finished() or state.timer.turn_active:
        return  # already running or game over

    state.timer.turn_start = time.time()
    state.timer.turn_active = True
    room.state = state

    await manager.broadcast_room(room, {
        "type": "timer_update",
        "turn_remaining": float(settings.turn_time_limit),
        "player_remaining": float(settings.player_time_limit)
            - state.timer.player_time_used.get(state.active_player().id, 0.0),
        "game_remaining": float(settings.game_time_limit)
            - (time.time() - (state.timer.game_start or time.time())),
        "active_player_id": state.active_player().id,
        "countdown_active": False,
    })


async def _handle_chat_all(ws: WebSocket, token: str, player_name: str, msg: dict) -> None:
    room = _find_room_by_token(token)
    if room is None:
        await _send_error(ws, "not_in_room", "You are not in a room")
        return
    text = str(msg.get("text", "")).strip()[:500]
    if not text:
        return
    room.touch()
    await manager.broadcast_room(room, {
        "type": "chat_all",
        "from": player_name,
        "text": text,
        "ts": time.time(),
    })


async def _handle_chat_team(ws: WebSocket, token: str, player_name: str, msg: dict) -> None:
    room = _find_room_by_token(token)
    if room is None:
        await _send_error(ws, "not_in_room", "You are not in a room")
        return

    sender = room.get_player(token)
    if sender is None or sender.team_id is None:
        await _send_error(ws, "no_team", "You are not on a team or the game hasn't started")
        return

    text = str(msg.get("text", "")).strip()[:500]
    if not text:
        return

    room.touch()
    payload = {
        "type": "chat_team",
        "team": sender.team_id,
        "from": player_name,
        "text": text,
        "ts": time.time(),
    }
    # Send only to teammates (same team_id)
    for rp in room.players:
        if rp.team_id == sender.team_id:
            await manager.send(rp.token, payload)


async def _handle_reaction(ws: WebSocket, token: str, player_name: str, msg: dict) -> None:
    room = _find_room_by_token(token)
    if room is None:
        await _send_error(ws, "not_in_room", "You are not in a room")
        return

    reaction = str(msg.get("reaction", "")).lower()
    if reaction not in VALID_REACTIONS:
        await _send_error(ws, "invalid_reaction", f"Valid reactions: {', '.join(sorted(VALID_REACTIONS))}")
        return

    room.touch()
    await manager.broadcast_room(room, {
        "type": "reaction",
        "from": player_name,
        "reaction": reaction,
        "emoji": REACTION_EMOJI[reaction],
        "ts": time.time(),
    })


async def _room_timer_task(room_id: str) -> None:
    """Per-room background task: enforces turn/player/game time limits for online mode."""
    try:
        while True:
            await asyncio.sleep(1.0)
            room = _rooms.get(room_id)
            if room is None or room.state is None or room.state.is_finished():
                return

            state = room.state
            timer = state.timer
            now = time.time()

            # 1. Game time limit
            if timer.game_start and (now - timer.game_start) >= settings.game_time_limit:
                state = _force_game_timeout(state)
                room.state = state
                await manager.broadcast_room(room, {"type": "game_state", "state": _safe_state(state)})
                await manager.broadcast_room(room, {
                    "type": "game_over",
                    "result": state.result.model_dump() if state.result else {},
                    "reason": "game_time_expired",
                })
                return

            # 2. Auto-start clock after animation_grace_seconds if client never sent turn_ready
            if not timer.turn_active and timer.turn_start is None and timer.game_start:
                game_elapsed = now - timer.game_start
                # Use last_activity as proxy for when the turn began
                turn_idle = time.monotonic() - room.last_activity
                if turn_idle >= settings.animation_grace_seconds:
                    timer.turn_start = now - turn_idle + settings.animation_grace_seconds
                    timer.turn_active = True

            if not timer.turn_active or timer.turn_start is None:
                continue

            # 3. Compute elapsed / remaining
            turn_elapsed = now - timer.turn_start
            active = state.active_player()
            player_used_total = timer.player_time_used.get(active.id, 0.0) + turn_elapsed

            turn_remaining = settings.turn_time_limit - turn_elapsed
            player_remaining = settings.player_time_limit - player_used_total
            game_remaining = settings.game_time_limit - (now - (timer.game_start or now))

            # 4. Broadcast live timer update
            await manager.broadcast_room(room, {
                "type": "timer_update",
                "turn_remaining": max(0.0, round(turn_remaining, 1)),
                "player_remaining": max(0.0, round(player_remaining, 1)),
                "game_remaining": max(0.0, round(game_remaining, 1)),
                "active_player_id": active.id,
                "countdown_active": 0 < turn_remaining <= settings.turn_countdown_threshold,
            })

            # 5. Player time warnings
            fractions = settings.player_warning_fractions_list
            fraction_used = player_used_total / settings.player_time_limit if settings.player_time_limit > 0 else 1.0
            already_sent = timer.player_warnings_sent.get(active.id, [])
            for frac in fractions:
                if fraction_used >= frac and frac not in already_sent:
                    already_sent.append(frac)
                    timer.player_warnings_sent[active.id] = already_sent
                    pct = int(frac * 100)
                    await manager.broadcast_room(room, {
                        "type": "timer_warning",
                        "player_id": active.id,
                        "player_name": active.name,
                        "fraction_used": frac,
                        "percent_used": pct,
                        "player_remaining": max(0.0, round(player_remaining, 1)),
                        "message": f"{active.name} has used {pct}% of their time ({_fmt_time(player_remaining)} remaining)",
                    })

            # 6. Player time limit exceeded → player loses
            if player_remaining <= 0:
                state = _finish_by_timeout(state, active.id, reason="player_time_expired")
                room.state = state
                await manager.broadcast_room(room, {"type": "game_state", "state": _safe_state(state)})
                await manager.broadcast_room(room, {
                    "type": "game_over",
                    "result": state.result.model_dump() if state.result else {},
                    "reason": "player_time_expired",
                    "player_id": active.id,
                })
                return

            # 7. Turn time limit exceeded → auto-advance
            if turn_remaining <= 0:
                state = await _auto_advance_turn(room, state, active)
                room.state = state
                await manager.broadcast_room(room, {"type": "game_state", "state": _safe_state(state)})
                if state.is_finished():
                    await manager.broadcast_room(room, {
                        "type": "game_over",
                        "result": state.result.model_dump() if state.result else {},
                    })
                    return

    except asyncio.CancelledError:
        pass
    finally:
        _room_timer_tasks.pop(room_id, None)


async def _auto_advance_turn(room: Room, state: GameState, active: Player) -> GameState:
    """Force-advance a timed-out turn: auto-play cards or auto-recruit."""
    # Record time used for this player
    if state.timer.turn_start:
        elapsed = time.time() - state.timer.turn_start
        state.timer.player_time_used[active.id] = (
            state.timer.player_time_used.get(active.id, 0.0) + elapsed
        )
    state.timer.turn_start = None
    state.timer.turn_active = False

    await manager.broadcast_room(room, {
        "type": "timer_event",
        "event": "turn_timeout",
        "player_id": active.id,
        "player_name": active.name,
        "message": f"{active.name}'s turn timed out — auto-advancing",
    })

    if state.phase == GamePhase.PLAY:
        hand = list(active.hand)
        if len(hand) >= 2:
            state, err = play_cards(state, active.id, hand[0], hand[1])
        if state.phase == GamePhase.RECRUIT:
            recruiter_id = _get_auto_recruiter_id(state)
            if recruiter_id:
                state, _ = recruit(state, recruiter_id, "face_up")
                state = check_end_conditions(state)

    elif state.phase == GamePhase.RECRUIT:
        recruiter_id = _get_auto_recruiter_id(state)
        if recruiter_id:
            state, _ = recruit(state, recruiter_id, "face_up")
            state = check_end_conditions(state)

    return state


def _get_auto_recruiter_id(state: GameState) -> str | None:
    if state.pending_play is None:
        return None
    # FFA: target is the recruiter
    if state.pending_play.target_id:
        return state.pending_play.target_id
    # 1v1 / solo: any non-actor alive player
    actor_id = state.pending_play.actor_id
    for p in state.players:
        if p.id != actor_id and not p.eliminated:
            return p.id
    return None


def _finish_by_timeout(state: GameState, timed_out_player_id: str, reason: str) -> GameState:
    from app.game.models import EndReason, GameResult
    other = next((p for p in state.players if p.id != timed_out_player_id), None)
    state.result = GameResult(
        winner_id=other.id if other else None,
        loser_id=timed_out_player_id,
        reason=EndReason.OUT_OF_CARDS,  # closest available reason; frontend reads reason from event
    )
    state.phase = GamePhase.FINISHED
    return state


def _force_game_timeout(state: GameState) -> GameState:
    """End game by clockwise distance when game time limit is reached."""
    from app.game.models import EndReason, GameResult
    if len(state.players) == 2:
        p1, p2 = state.players[0], state.players[1]
        d1 = state.board_distance(p1.position, p2.position)
        d2 = state.board_distance(p2.position, p1.position)
        winner = p1 if d1 <= d2 else p2
        loser = p2 if winner.id == p1.id else p1
        state.result = GameResult(winner_id=winner.id, loser_id=loser.id, reason=EndReason.OUT_OF_CARDS)
    else:
        alive = [p for p in state.players if not p.eliminated]
        if alive:
            state.result = GameResult(winner_id=alive[0].id, reason=EndReason.OUT_OF_CARDS)
    state.phase = GamePhase.FINISHED
    return state


def _fmt_time(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _cancel_room_timer(room_id: str) -> None:
    task = _room_timer_tasks.pop(room_id, None)
    if task and not task.done():
        task.cancel()


async def _handle_disconnect(token: str) -> None:
    room = _find_room_by_token(token)
    if room is None:
        return
    room.players = [p for p in room.players if p.token != token]
    if room.players:
        await manager.broadcast_room(room, {"type": "player_disconnected"})
    else:
        _cancel_room_timer(room.id)
        _rooms.pop(room.id, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_room_by_token(token: str) -> Room | None:
    for room in _rooms.values():
        if any(p.token == token for p in room.players):
            return room
    return None


def _get_room_and_player(ws: WebSocket, token: str) -> tuple[Room | None, RoomPlayer | None]:
    room = _find_room_by_token(token)
    if room is None:
        return None, None
    rp = room.get_player(token)
    return room, rp


def _record_turn_time(state: GameState, player_id: str) -> None:
    """Accumulate elapsed turn time into player_time_used when they act."""
    if state.timer.turn_active and state.timer.turn_start:
        elapsed = time.time() - state.timer.turn_start
        state.timer.player_time_used[player_id] = (
            state.timer.player_time_used.get(player_id, 0.0) + elapsed
        )
        state.timer.turn_start = None
        state.timer.turn_active = False


def _safe_state(state: GameState) -> dict:
    """Return state dict. In online mode each client only sees their own hand — enforced client-side by token."""
    return state.model_dump()


async def _send_error(ws: WebSocket, code: str, message: str) -> None:
    try:
        await ws.send_text(json.dumps({"type": "error", "code": code, "message": message}))
    except Exception:
        pass
