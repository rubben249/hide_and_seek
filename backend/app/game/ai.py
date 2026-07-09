"""
AI module for TAG! — three difficulty levels.

All levels respect the information boundary:
- AI sees: its own hand, both players' recruited cards, board positions, deck size.
- AI does NOT see: the human's hand cards.

Beginner: random valid play.
Veteran:  1-turn minimax — maximise worst-case outcome.
Maestro:  2-3 turn minimax + deck probability tracking.
"""
from __future__ import annotations

import copy
import random
from itertools import permutations

from app.game.cards import Card, CardName, WIN, LOSE, CARD_VALUES, build_deck
from app.game.models import AIDifficulty, GameMode, GameState, Player
from app.game.engine import (
    play_cards,
    recruit,
    resolve_movement,
    check_end_conditions,
    draw_to_hand,
    _opponent_of,
    _has_caught,
    _position_of,
)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def ai_choose_play(state: GameState, ai_player_id: str) -> tuple[str, str]:
    """
    Return (face_up, face_down) card names for the AI to play.
    """
    player = state.get_player(ai_player_id)
    if player is None:
        raise ValueError("AI player not found")

    difficulty = player.ai_difficulty or AIDifficulty.BEGINNER

    if difficulty == AIDifficulty.BEGINNER:
        return _beginner_play(state, player)
    elif difficulty == AIDifficulty.VETERAN:
        return _veteran_play(state, player)
    else:
        return _maestro_play(state, player)


def ai_choose_recruit(state: GameState, ai_player_id: str, face_up: str, face_down: str) -> str:
    """
    Return 'face_up' or 'face_down' — which card the AI wants to recruit.
    Called when the AI is the *opponent* recruiting from a human's play.
    """
    player = state.get_player(ai_player_id)
    if player is None:
        return "face_up"

    difficulty = player.ai_difficulty or AIDifficulty.BEGINNER

    if difficulty == AIDifficulty.BEGINNER:
        return random.choice(["face_up", "face_down"])
    else:
        return _choose_recruit_heuristic(state, player, face_up, face_down)


# ---------------------------------------------------------------------------
# Beginner
# ---------------------------------------------------------------------------

def _beginner_play(state: GameState, player: Player) -> tuple[str, str]:
    hand = list(player.hand)
    random.shuffle(hand)
    for i in range(len(hand)):
        for j in range(len(hand)):
            if i != j and (hand[i] != hand[j] or _all_same(hand)):
                return hand[i], hand[j]
    return hand[0], hand[min(1, len(hand) - 1)]


def _all_same(hand: list[str]) -> bool:
    return len(set(hand)) == 1


# ---------------------------------------------------------------------------
# Heuristic evaluation
# ---------------------------------------------------------------------------

INF = float("inf")


def _evaluate(state: GameState, ai_id: str) -> float:
    """
    Score the state from the AI's perspective.
    Higher = better for AI.
    """
    ai = state.get_player(ai_id)
    human = _opponent_of(state, ai_id)
    if ai is None or human is None:
        return 0.0

    score = 0.0

    # Position advantage: how close is AI to catching human, minus vice versa
    ai_pos = _position_of(state, ai)
    human_pos = _position_of(state, human)
    board = state.board_size

    dist_ai_to_human = (human_pos - ai_pos) % board
    dist_human_to_ai = (ai_pos - human_pos) % board

    score += (dist_human_to_ai - dist_ai_to_human) * 2.0

    # Codebreaker progress (win condition)
    ai_mm = ai.count_in_play(CardName.CODEBREAKER)
    human_mm = human.count_in_play(CardName.CODEBREAKER)
    score += ai_mm * 15.0
    score -= human_mm * 15.0

    # Daredevil danger (lose condition)
    ai_so = ai.count_in_play(CardName.DAREDEVIL)
    human_so = human.count_in_play(CardName.DAREDEVIL)
    score -= ai_so * 20.0 * (ai_so / 3.0)
    score += human_so * 10.0

    # Sentinel investment
    ai_look = ai.count_in_play(CardName.SENTINEL)
    human_look = human.count_in_play(CardName.SENTINEL)
    score += ai_look * 5.0
    score -= human_look * 3.0

    # Terminal states
    if state.result is not None:
        if state.result.winner_id == ai_id:
            return INF
        else:
            return -INF

    return score


def _valid_plays(hand: list[str]) -> list[tuple[str, str]]:
    """Return all valid (face_up, face_down) pairs from the hand."""
    plays = set()
    for i, a in enumerate(hand):
        for j, b in enumerate(hand):
            if i != j and (a != b or _all_same(hand)):
                plays.add((a, b))
    if not plays:
        # fallback
        plays.add((hand[0], hand[min(1, len(hand) - 1)]))
    return list(plays)


def _simulate_recruit(state: GameState, ai_id: str, face_up: str, face_down: str, choice: str) -> GameState:
    """Simulate a single recruit step without modifying the original state."""
    s = state.model_copy(deep=True)
    ai = s.get_player(ai_id)
    human = _opponent_of(s, ai_id)
    if ai is None or human is None:
        return s

    # Remove cards from AI hand
    if face_up in ai.hand:
        ai.hand.remove(face_up)
    if face_down in ai.hand:
        ai.hand.remove(face_down)

    if choice == "face_up":
        human_card = Card(CardName(face_up))
        ai_card = Card(CardName(face_down))
    else:
        human_card = Card(CardName(face_down))
        ai_card = Card(CardName(face_up))

    human.recruited.append(human_card.name.value)
    ai.recruited.append(ai_card.name.value)

    s = resolve_movement(s, human.id, human_card)
    s = resolve_movement(s, ai.id, ai_card)
    s = draw_to_hand(s, human.id)
    s = draw_to_hand(s, ai.id)

    return s


# ---------------------------------------------------------------------------
# Veteran (1-turn minimax)
# ---------------------------------------------------------------------------

def _veteran_play(state: GameState, player: Player) -> tuple[str, str]:
    plays = _valid_plays(player.hand)
    best_play = plays[0]
    best_score = -INF

    for face_up, face_down in plays:
        # Worst case: human picks whichever card is best for them
        score_if_human_takes_face_up = _evaluate(
            _simulate_recruit(state, player.id, face_up, face_down, "face_up"),
            player.id,
        )
        score_if_human_takes_face_down = _evaluate(
            _simulate_recruit(state, player.id, face_up, face_down, "face_down"),
            player.id,
        )
        # Human will take the worse option for AI (minimax: opponent minimises)
        worst = min(score_if_human_takes_face_up, score_if_human_takes_face_down)
        if worst > best_score:
            best_score = worst
            best_play = (face_up, face_down)

    return best_play


def _choose_recruit_heuristic(state: GameState, ai: Player, face_up: str, face_down: str) -> str:
    """AI chooses which of the two cards to recruit for itself."""
    human = _opponent_of(state, ai.id)
    if human is None:
        return "face_up"

    s_up = state.model_copy(deep=True)
    s_down = state.model_copy(deep=True)

    # Simulate: AI takes face_up
    p_up = s_up.get_player(ai.id)
    if p_up:
        p_up.recruited.append(face_up)
        s_up = resolve_movement(s_up, ai.id, Card(CardName(face_up)))
    score_up = _evaluate(s_up, ai.id)

    # Simulate: AI takes face_down
    p_down = s_down.get_player(ai.id)
    if p_down:
        p_down.recruited.append(face_down)
        s_down = resolve_movement(s_down, ai.id, Card(CardName(face_down)))
    score_down = _evaluate(s_down, ai.id)

    return "face_up" if score_up >= score_down else "face_down"


# ---------------------------------------------------------------------------
# Maestro (2-3 turn minimax + deck probability)
# ---------------------------------------------------------------------------

MAESTRO_DEPTH = 2  # search depth (each level = 1 recruit step)


def _deck_probabilities(state: GameState, human_id: str) -> dict[str, float]:
    """
    Estimate probability of each card name being in human's hand,
    based on known deck composition minus played/discarded cards.
    Returns {card_name: probability}.
    """
    human = state.get_player(human_id)
    if human is None:
        return {}

    # Full deck composition
    full = {}
    for card in build_deck():
        full[card.name.value] = full.get(card.name.value, 0) + 1

    # Subtract what's been recruited (face-up / publicly visible) and in the deck
    visible: dict[str, int] = {}
    for p in state.players:
        for cn in p.recruited:
            visible[cn] = visible.get(cn, 0) + 1
    for cn in state.discard_pile:
        visible[cn] = visible.get(cn, 0) + 1
    for cn in state.deck:
        visible[cn] = visible.get(cn, 0) + 1

    unknown: dict[str, int] = {}
    for cn, count in full.items():
        remaining = count - visible.get(cn, 0)
        if remaining > 0:
            unknown[cn] = remaining

    total_unknown = sum(unknown.values())
    if total_unknown == 0:
        return {}

    human_hand_size = len(human.hand)
    probs = {cn: (cnt / total_unknown) * human_hand_size for cn, cnt in unknown.items()}
    return probs


def _minimax(
    state: GameState,
    ai_id: str,
    depth: int,
    is_ai_turn: bool,
    deck_probs: dict[str, float],
) -> float:
    if state.is_finished() or depth == 0:
        return _evaluate(state, ai_id)

    ai = state.get_player(ai_id)
    human = _opponent_of(state, ai_id)
    if ai is None or human is None:
        return 0.0

    if is_ai_turn:
        # AI maximises: try all plays, take worst-case human response
        plays = _valid_plays(ai.hand)
        best = -INF
        for face_up, face_down in plays:
            for choice in ("face_up", "face_down"):
                sim = _simulate_recruit(state, ai_id, face_up, face_down, choice)
                val = _minimax(sim, ai_id, depth - 1, False, deck_probs)
                best = max(best, val)
        return best
    else:
        # Human turn: use expected value over likely human hands
        if not deck_probs:
            return _evaluate(state, ai_id)

        # Sample top-probability cards as likely human plays
        top_cards = sorted(deck_probs.items(), key=lambda x: -x[1])[:4]
        if not top_cards:
            return _evaluate(state, ai_id)

        total_weight = sum(w for _, w in top_cards)
        expected = 0.0
        for card_name, weight in top_cards:
            # Simulate human recruiting this card
            sim = state.model_copy(deep=True)
            h = sim.get_player(human.id)
            if h:
                h.recruited.append(card_name)
                sim = resolve_movement(sim, human.id, Card(CardName(card_name)))
            val = _minimax(sim, ai_id, depth - 1, True, deck_probs)
            expected += (weight / total_weight) * val

        return expected


def _maestro_play(state: GameState, player: Player) -> tuple[str, str]:
    human = _opponent_of(state, player.id)
    if human is None:
        return _veteran_play(state, player)

    deck_probs = _deck_probabilities(state, human.id)
    plays = _valid_plays(player.hand)
    best_play = plays[0]
    best_score = -INF

    for face_up, face_down in plays:
        # AI plays these cards — evaluate from human's perspective (human picks best for them)
        score_face_up = _minimax(
            _simulate_recruit(state, player.id, face_up, face_down, "face_up"),
            player.id, MAESTRO_DEPTH, False, deck_probs,
        )
        score_face_down = _minimax(
            _simulate_recruit(state, player.id, face_up, face_down, "face_down"),
            player.id, MAESTRO_DEPTH, False, deck_probs,
        )
        # Human picks whichever hurts AI most → take minimum
        worst = min(score_face_up, score_face_down)
        if worst > best_score:
            best_score = worst
            best_play = (face_up, face_down)

    return best_play
