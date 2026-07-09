"""
Game engine: pure functions that transition GameState.
All functions are side-effect free — they return a new (mutated copy) GameState.
"""
from __future__ import annotations

import copy

from app.game.cards import Card, CardName, WIN, LOSE
from app.game.models import (
    AIDifficulty,
    EndReason,
    GameMode,
    GamePhase,
    GameResult,
    GameState,
    PendingPlay,
    Player,
    Team,
    TeamId,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clone(state: GameState) -> GameState:
    return state.model_copy(deep=True)


def _next_active(state: GameState) -> int:
    """Return next non-eliminated player index."""
    n = len(state.players)
    idx = (state.active_player_index + 1) % n
    for _ in range(n):
        if not state.players[idx].eliminated:
            return idx
        idx = (idx + 1) % n
    return state.active_player_index  # all eliminated? shouldn't happen


def _opponent_of(state: GameState, player_id: str) -> Player | None:
    """For 1v1 or solo: return the other player."""
    for p in state.players:
        if p.id != player_id:
            return p
    return None


def _team_of(state: GameState, player_id: str) -> Team | None:
    if not state.teams:
        return None
    player = state.get_player(player_id)
    if player is None:
        return None
    return next((t for t in state.teams if player_id in t.player_ids), None)


def _opposing_team(state: GameState, team_id: TeamId) -> Team | None:
    if not state.teams:
        return None
    return next((t for t in state.teams if t.id != team_id), None)


def _move_pawn(position: int, steps: int, board_size: int) -> int:
    return (position + steps) % board_size


# ---------------------------------------------------------------------------
# Movement resolution
# ---------------------------------------------------------------------------

def resolve_movement(state: GameState, player_id: str, card: Card) -> GameState:
    """Move the player's pawn according to the card they just recruited."""
    state = _clone(state)
    player = state.get_player(player_id)
    if player is None:
        return state

    copies = player.count_in_play(card.name)
    value = card.get_movement_value(copies)

    if isinstance(value, int) and value != 0:
        if state.mode in (GameMode.LOCAL_2V2, GameMode.LOCAL_2V1):
            team = _team_of(state, player_id)
            if team:
                team.total_steps += value
                team.meeple_position = _move_pawn(team.meeple_position, value, state.board_size)
        else:
            player.total_steps += value
            player.position = _move_pawn(player.position, value, state.board_size)

    return state


# ---------------------------------------------------------------------------
# Draw cards
# ---------------------------------------------------------------------------

def draw_to_hand(state: GameState, player_id: str) -> GameState:
    """Draw cards from the deck until the player has their hand size limit."""
    state = _clone(state)
    player = state.get_player(player_id)
    if player is None:
        return state

    limit = player.hand_size_limit()
    while len(player.hand) < limit and state.deck:
        card = state.draw_card()
        if card:
            player.hand.append(card.name.value)

    return state


# ---------------------------------------------------------------------------
# Discard (optional before playing)
# ---------------------------------------------------------------------------

def discard_card(state: GameState, player_id: str, card_name: str) -> tuple[GameState, str | None]:
    """Player discards one card from hand to draw a new one. Returns (new_state, error)."""
    state = _clone(state)
    player = state.get_player(player_id)
    if player is None:
        return state, "Player not found"
    if not state.deck:
        return state, "Deck is empty — cannot discard to draw"
    if player.discards_used >= player.max_discards:
        return state, f"No discards remaining (used {player.discards_used}/{player.max_discards})"
    if card_name not in player.hand:
        return state, "Card not in hand"

    player.hand.remove(card_name)
    state.discard_pile.append(card_name)
    player.discards_used += 1

    new_card = state.draw_card()
    if new_card:
        player.hand.append(new_card.name.value)

    return state, None


# ---------------------------------------------------------------------------
# Step 1: Play
# ---------------------------------------------------------------------------

def play_cards(
    state: GameState,
    player_id: str,
    face_up: str,
    face_down: str,
    target_id: str | None = None,
) -> tuple[GameState, str | None]:
    """Player places 2 cards (face-up + face-down). Returns (new_state, error)."""
    state = _clone(state)
    player = state.get_player(player_id)
    if player is None:
        return state, "Player not found"
    if state.phase not in (GamePhase.PLAY, GamePhase.FFA_TARGET):
        return state, f"Wrong phase: {state.phase}"

    # Validate cards exist in hand
    hand_copy = list(player.hand)
    if face_up not in hand_copy:
        return state, f"Card '{face_up}' not in hand"
    hand_copy.remove(face_up)
    if face_down not in hand_copy:
        return state, f"Card '{face_down}' not in hand"

    # Cards must have different names (unless player has no choice)
    unique_names = set(player.hand)
    if face_up == face_down and len(unique_names) > 1:
        return state, "Cards must have different names"

    # FFA: target must be specified and valid
    if state.mode == GameMode.LOCAL_FFA:
        if target_id is None:
            return state, "Must specify a target in FFA mode"
        target = state.get_player(target_id)
        if target is None or target.eliminated:
            return state, "Invalid target"

    # Remove cards from hand
    player.hand.remove(face_up)
    player.hand.remove(face_down)

    state.pending_play = PendingPlay(
        face_up=face_up,
        face_down=face_down,
        actor_id=player_id,
        target_id=target_id,
    )
    state.phase = GamePhase.RECRUIT
    return state, None


# ---------------------------------------------------------------------------
# Step 2: Recruit
# ---------------------------------------------------------------------------

def recruit(
    state: GameState,
    recruiting_player_id: str,
    choice: str,  # "face_up" or "face_down"
) -> tuple[GameState, str | None]:
    """
    Opponent recruits one card; actor recruits the other.
    Moves both pawns, then draws both back to hand limit.
    Returns (new_state, error).
    """
    if state.pending_play is None:
        return state, "No pending play"
    if choice not in ("face_up", "face_down"):
        return state, "Choice must be 'face_up' or 'face_down'"

    state = _clone(state)
    pending = state.pending_play
    actor = state.get_player(pending.actor_id)
    recruiter = state.get_player(recruiting_player_id)

    if actor is None or recruiter is None:
        return state, "Player not found"

    # Determine which card each player gets
    if choice == "face_up":
        recruiter_card_name = pending.face_up
        actor_card_name = pending.face_down
    else:
        recruiter_card_name = pending.face_down
        actor_card_name = pending.face_up

    recruiter_card = Card(CardName(recruiter_card_name))
    actor_card = Card(CardName(actor_card_name))

    # Recruiter (opponent) takes their card
    recruiter.recruit_card(recruiter_card)
    # Actor takes their card
    actor.recruit_card(actor_card)

    state.pending_play = None

    # Move both pawns
    state = resolve_movement(state, recruiting_player_id, recruiter_card)
    state = resolve_movement(state, pending.actor_id, actor_card)

    # Draw back to hand limit
    state = draw_to_hand(state, recruiting_player_id)
    state = draw_to_hand(state, pending.actor_id)

    state.phase = GamePhase.END_CHECK
    return state, None


# ---------------------------------------------------------------------------
# Step 3: End — check win/lose conditions
# ---------------------------------------------------------------------------

def _position_of(state: GameState, player: Player) -> int:
    if state.mode in (GameMode.LOCAL_2V2, GameMode.LOCAL_2V1):
        team = _team_of(state, player.id)
        return team.meeple_position if team else player.position
    return player.position


def _has_caught(state: GameState, chaser: Player, target: Player) -> bool:
    """
    True if chaser's pawn has reached or passed target's pawn (clockwise).

    Uses cumulative signed total_steps so backward movement never creates
    false positives.  Chaser catches target when chaser's total progress
    from chaser's home >= target's head start + target's own total progress.

    Head start = (target.home - chaser.home) mod board_size
    Condition:  chaser.total_steps >= head_start + target.total_steps
                AND chaser.total_steps > 0  (must have moved forward at least once)
    """
    if state.mode in (GameMode.LOCAL_2V2, GameMode.LOCAL_2V1):
        # Team mode: compare team total_steps
        chaser_team = _team_of(state, chaser.id)
        target_team = _team_of(state, target.id)
        if chaser_team is None or target_team is None:
            return False
        head_start = (target_team.home_position - chaser_team.home_position) % state.board_size
        return chaser_team.total_steps >= head_start + target_team.total_steps and chaser_team.total_steps > 0

    # FFA: pawns catching each other — same space counts OR overtake
    if state.mode == GameMode.LOCAL_FFA:
        return chaser.position == target.position and chaser.position != chaser.home_position

    # 1v1 / solo: use cumulative steps
    head_start = (target.home_position - chaser.home_position) % state.board_size
    return chaser.total_steps >= head_start + target.total_steps and chaser.total_steps > 0


def check_end_conditions(state: GameState) -> GameState:
    """
    Evaluate all win/lose conditions. If game ends, set state.result and phase=FINISHED.
    If not, advance to next player's turn.
    """
    state = _clone(state)

    if state.mode in (GameMode.SOLO, GameMode.LOCAL_1V1):
        state = _check_1v1_end(state)
    elif state.mode in (GameMode.LOCAL_2V2, GameMode.LOCAL_2V1):
        state = _check_team_end(state)
    elif state.mode == GameMode.LOCAL_FFA:
        state = _check_ffa_end(state)

    if not state.is_finished():
        state.active_player_index = _next_active(state)
        state.phase = GamePhase.PLAY
        state.turn_number += 1
        # Reset turn clock — client will send turn_ready after animations to start it
        state.timer.turn_start = None
        state.timer.turn_active = False

    return state


def _check_1v1_end(state: GameState) -> GameState:
    active = state.active_player()
    other = _opponent_of(state, active.id)
    if other is None:
        return state

    active_wins: list[EndReason] = []
    active_loses: list[EndReason] = []

    # A: catch
    if _has_caught(state, active, other):
        active_wins.append(EndReason.CAUGHT)
    if _has_caught(state, other, active):
        active_loses.append(EndReason.CAUGHT)

    # B: 3 Codebreakers
    if active.count_in_play(CardName.CODEBREAKER) >= 3:
        active_wins.append(EndReason.THREE_MASTERMINDS)
    if other.count_in_play(CardName.CODEBREAKER) >= 3:
        active_loses.append(EndReason.THREE_MASTERMINDS)

    # C: 3 Daredevils
    if active.count_in_play(CardName.DAREDEVIL) >= 3:
        active_loses.append(EndReason.THREE_SHOW_OFFS)
    if other.count_in_play(CardName.DAREDEVIL) >= 3:
        active_wins.append(EndReason.THREE_SHOW_OFFS)

    game_ends = bool(active_wins or active_loses)

    # Running out of cards
    if not game_ends and not state.deck and len(other.hand) < 2:
        _finish_by_distance_1v1(state, active, other)
        return state

    if not game_ends:
        return state

    # Tie → active player wins
    if active_wins and not active_loses:
        state.result = GameResult(winner_id=active.id, loser_id=other.id, reason=active_wins[0])
    elif active_loses and not active_wins:
        state.result = GameResult(winner_id=other.id, loser_id=active.id, reason=active_loses[0])
    else:
        # Tie: active player wins
        state.result = GameResult(winner_id=active.id, loser_id=other.id, reason=active_wins[0] if active_wins else active_loses[0])

    state.phase = GamePhase.FINISHED
    return state


def _finish_by_distance_1v1(state: GameState, p1: Player, p2: Player) -> None:
    # The player closer to catching the opponent wins
    dist_p1 = state.board_distance(p1.position, p2.position)
    dist_p2 = state.board_distance(p2.position, p1.position)
    active = state.active_player()
    if dist_p1 < dist_p2:
        state.result = GameResult(winner_id=p1.id, loser_id=p2.id, reason=EndReason.OUT_OF_CARDS)
    elif dist_p2 < dist_p1:
        state.result = GameResult(winner_id=p2.id, loser_id=p1.id, reason=EndReason.OUT_OF_CARDS)
    else:
        state.result = GameResult(winner_id=active.id, reason=EndReason.OUT_OF_CARDS)
    state.phase = GamePhase.FINISHED


def _check_team_end(state: GameState) -> GameState:
    if not state.teams:
        return state
    team_a, team_b = state.teams[0], state.teams[1]

    def team_masterminds(team: Team) -> int:
        return team.recruited.count(CardName.CODEBREAKER.value)

    def team_show_offs(team: Team) -> int:
        return team.recruited.count(CardName.DAREDEVIL.value)

    def caught(chaser: Team, target: Team) -> bool:
        home = target.home_position
        dc = (chaser.meeple_position - home) % state.board_size
        dt = (target.meeple_position - home) % state.board_size
        return dc >= dt and dc > 0

    a_wins: list[EndReason] = []
    a_loses: list[EndReason] = []

    if caught(team_a, team_b):
        a_wins.append(EndReason.CAUGHT)
    if caught(team_b, team_a):
        a_loses.append(EndReason.CAUGHT)
    if team_masterminds(team_a) >= 3:
        a_wins.append(EndReason.THREE_MASTERMINDS)
    if team_masterminds(team_b) >= 3:
        a_loses.append(EndReason.THREE_MASTERMINDS)
    if team_show_offs(team_a) >= 3:
        a_loses.append(EndReason.THREE_SHOW_OFFS)
    if team_show_offs(team_b) >= 3:
        a_wins.append(EndReason.THREE_SHOW_OFFS)

    active = state.active_player()
    active_team_id = active.team

    if not (a_wins or a_loses):
        return state

    if a_wins and not a_loses:
        winner_team = team_a if active_team_id == TeamId.TEAM_A else team_b
        loser_team = team_b if active_team_id == TeamId.TEAM_A else team_a
        state.result = GameResult(winner_id=winner_team.id, reason=a_wins[0])
    elif a_loses and not a_wins:
        winner_team = team_b if active_team_id == TeamId.TEAM_A else team_a
        state.result = GameResult(winner_id=winner_team.id, reason=a_loses[0])
    else:
        state.result = GameResult(winner_id=str(active_team_id), reason=EndReason.CAUGHT)

    state.phase = GamePhase.FINISHED
    return state


def _check_ffa_end(state: GameState) -> GameState:
    active = state.active_player()
    alive = [p for p in state.players if not p.eliminated]

    # Check 3 Daredevils → elimination
    for p in list(alive):
        if p.count_in_play(CardName.DAREDEVIL) >= 3:
            p.eliminated = True
            alive = [x for x in alive if not x.eliminated]

    # Check 3 Codebreakers → instant win
    for p in alive:
        if p.count_in_play(CardName.CODEBREAKER) >= 3:
            state.result = GameResult(winner_id=p.id, reason=EndReason.THREE_MASTERMINDS)
            state.phase = GamePhase.FINISHED
            return state

    # Check catch: active player caught any other
    for other in alive:
        if other.id == active.id:
            continue
        if _has_caught(state, active, other):
            state.result = GameResult(winner_id=active.id, loser_id=other.id, reason=EndReason.CAUGHT)
            state.phase = GamePhase.FINISHED
            return state

    # Only one player left → they win
    alive = [p for p in state.players if not p.eliminated]
    if len(alive) == 1:
        state.result = GameResult(winner_id=alive[0].id, reason=EndReason.THREE_SHOW_OFFS)
        state.phase = GamePhase.FINISHED
        return state

    return state


# ---------------------------------------------------------------------------
# Full turn for AI (combines play + recruit + end)
# ---------------------------------------------------------------------------

def apply_ai_turn(state: GameState, ai_play: tuple[str, str], human_choice: str) -> tuple[GameState, str | None]:
    """
    Apply a full AI turn: AI plays 2 cards, human (opponent) recruits, then end check.
    ai_play: (face_up, face_down)
    human_choice: "face_up" or "face_down"
    """
    ai_player = state.active_player()
    face_up, face_down = ai_play

    state, err = play_cards(state, ai_player.id, face_up, face_down)
    if err:
        return state, err

    # Human recruits
    human = _opponent_of(state, ai_player.id)
    if human is None:
        return state, "No opponent"

    state, err = recruit(state, human.id, human_choice)
    if err:
        return state, err

    state = check_end_conditions(state)
    return state, None
