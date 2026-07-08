"""
REST endpoints for solo (vs AI) and local multiplayer modes.
All game state is kept server-side in an in-memory dict keyed by game_id.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.game.cards import CardName
from app.game.engine import (
    check_end_conditions,
    discard_card,
    play_cards,
    recruit,
)
from app.game.ai import ai_choose_play, ai_choose_recruit
from app.game.models import (
    AIDifficulty,
    GameMode,
    GamePhase,
    GameState,
    PlayerType,
    init_game,
)

router = APIRouter(prefix="/api")

# In-memory store: game_id → GameState
_games: dict[str, GameState] = {}


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class NewSoloGameRequest(BaseModel):
    player_name: str = "Player"
    difficulty: AIDifficulty = AIDifficulty.BEGINNER


class NewLocalGameRequest(BaseModel):
    mode: GameMode
    player_names: list[str]


class PlayCardsRequest(BaseModel):
    game_id: str
    player_id: str
    face_up: str
    face_down: str
    target_id: str | None = None  # FFA only


class RecruitRequest(BaseModel):
    game_id: str
    player_id: str
    choice: str  # "face_up" or "face_down"


class DiscardRequest(BaseModel):
    game_id: str
    player_id: str
    card_name: str


class AITurnRequest(BaseModel):
    game_id: str
    human_choice: str  # "face_up" or "face_down" — which card human wants


def _state_to_dict(state: GameState) -> dict[str, Any]:
    """Serialize GameState to JSON-safe dict, hiding AI hand from humans."""
    d = state.model_dump()
    # Hide the hand of AI players
    for p in d.get("players", []):
        player_obj = state.get_player(p["id"])
        if player_obj and player_obj.type == PlayerType.AI:
            p["hand"] = ["?" for _ in p["hand"]]
    return d


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health")
def health() -> dict:
    return {"status": "ok", "active_games": len(_games)}


# ---------------------------------------------------------------------------
# Solo mode
# ---------------------------------------------------------------------------

@router.post("/solo/new")
def new_solo_game(req: NewSoloGameRequest) -> dict:
    state = init_game(
        mode=GameMode.SOLO,
        player_names=[req.player_name, "__AI__"],
        ai_difficulty=req.difficulty,
        first_player_index=0,
    )
    # Mark AI player
    for p in state.players:
        if p.name == "__AI__":
            p.name = f"AI ({req.difficulty.value.capitalize()})"
            p.type = PlayerType.AI
            p.ai_difficulty = req.difficulty

    _games[state.id] = state
    return {"game_id": state.id, "state": _state_to_dict(state)}


@router.post("/solo/ai-turn")
def solo_ai_turn(req: AITurnRequest) -> dict:
    """
    Called when it's the AI's turn.
    The server computes the AI play, applies it, then the human recruits.
    Returns the updated state after the AI plays and human recruits.
    """
    state = _get_game(req.game_id)
    ai_player = next((p for p in state.players if p.type == PlayerType.AI), None)
    if ai_player is None:
        raise HTTPException(400, "No AI player in this game")
    if state.active_player().id != ai_player.id:
        raise HTTPException(400, "It's not the AI's turn")

    face_up, face_down = ai_choose_play(state, ai_player.id)
    state, err = play_cards(state, ai_player.id, face_up, face_down)
    if err:
        raise HTTPException(400, err)

    # Now human recruits
    human = next((p for p in state.players if p.type == PlayerType.AI), None)
    # Actually find the human (non-AI)
    human = next((p for p in state.players if p.type != PlayerType.AI), None)
    if human is None:
        raise HTTPException(400, "No human player")

    state, err = recruit(state, human.id, req.human_choice)
    if err:
        raise HTTPException(400, err)

    state = check_end_conditions(state)
    _games[req.game_id] = state
    return {"state": _state_to_dict(state), "ai_played": {"face_up": face_up, "face_down": face_down}}


# ---------------------------------------------------------------------------
# Shared endpoints (solo + local)
# ---------------------------------------------------------------------------

@router.post("/local/new")
def new_local_game(req: NewLocalGameRequest) -> dict:
    if req.mode not in (
        GameMode.LOCAL_1V1, GameMode.LOCAL_2V2, GameMode.LOCAL_2V1, GameMode.LOCAL_FFA
    ):
        raise HTTPException(400, f"Mode {req.mode} is not a local mode")

    expected_players = {
        GameMode.LOCAL_1V1: 2,
        GameMode.LOCAL_2V2: 4,
        GameMode.LOCAL_2V1: 3,
        GameMode.LOCAL_FFA: 4,
    }
    expected = expected_players[req.mode]
    if len(req.player_names) != expected:
        raise HTTPException(400, f"Mode {req.mode} requires {expected} players")

    state = init_game(mode=req.mode, player_names=req.player_names)
    _games[state.id] = state
    return {"game_id": state.id, "state": _state_to_dict(state)}


@router.get("/game/{game_id}")
def get_game(game_id: str) -> dict:
    state = _get_game(game_id)
    return {"state": _state_to_dict(state)}


@router.post("/game/discard")
def discard(req: DiscardRequest) -> dict:
    state = _get_game(req.game_id)
    state, err = discard_card(state, req.player_id, req.card_name)
    if err:
        raise HTTPException(400, err)
    _games[req.game_id] = state
    return {"state": _state_to_dict(state)}


@router.post("/game/play")
def play(req: PlayCardsRequest) -> dict:
    state = _get_game(req.game_id)
    state, err = play_cards(state, req.player_id, req.face_up, req.face_down, req.target_id)
    if err:
        raise HTTPException(400, err)
    _games[req.game_id] = state

    # If it's solo mode and the next phase is RECRUIT but the recruiter is AI,
    # auto-resolve AI recruit
    if state.mode == GameMode.SOLO and state.phase == GamePhase.RECRUIT:
        pending = state.pending_play
        if pending:
            ai_player = next((p for p in state.players if p.type == PlayerType.AI), None)
            if ai_player and pending.actor_id != ai_player.id:
                # AI is the recruiter (human just played, AI recruits)
                ai_choice = ai_choose_recruit(state, ai_player.id, pending.face_up, pending.face_down)
                state, err = recruit(state, ai_player.id, ai_choice)
                if err:
                    raise HTTPException(400, err)
                state = check_end_conditions(state)
                _games[req.game_id] = state
                return {"state": _state_to_dict(state), "ai_recruited": ai_choice}

    return {"state": _state_to_dict(state)}


@router.post("/game/recruit")
def do_recruit(req: RecruitRequest) -> dict:
    state = _get_game(req.game_id)
    state, err = recruit(state, req.player_id, req.choice)
    if err:
        raise HTTPException(400, err)
    state = check_end_conditions(state)
    _games[req.game_id] = state

    # Solo mode: if it's now the AI's turn, compute AI play automatically
    response: dict[str, Any] = {"state": _state_to_dict(state)}
    if state.mode == GameMode.SOLO and not state.is_finished():
        ai_player = next((p for p in state.players if p.type == PlayerType.AI), None)
        if ai_player and state.active_player().id == ai_player.id:
            face_up, face_down = ai_choose_play(state, ai_player.id)
            state, err = play_cards(state, ai_player.id, face_up, face_down)
            if not err:
                _games[req.game_id] = state
                response["state"] = _state_to_dict(state)
                response["ai_played"] = {"face_up": face_up, "face_down": face_down}

    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_game(game_id: str) -> GameState:
    state = _games.get(game_id)
    if state is None:
        raise HTTPException(404, "Game not found")
    if state.is_finished():
        raise HTTPException(400, "Game is already finished")
    return state
