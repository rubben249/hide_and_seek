from __future__ import annotations

import random
import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.game.cards import Card, CardName, build_deck


class GameMode(str, Enum):
    SOLO = "solo"           # 1 human vs AI
    LOCAL_1V1 = "local_1v1"
    LOCAL_2V2 = "local_2v2"
    LOCAL_2V1 = "local_2v1"
    LOCAL_FFA = "local_ffa"  # free-for-all, 4 players
    ONLINE = "online"


class AIDifficulty(str, Enum):
    BEGINNER = "beginner"
    VETERAN = "veteran"
    MAESTRO = "maestro"


class TeamId(str, Enum):
    TEAM_A = "A"
    TEAM_B = "B"


class PlayerType(str, Enum):
    HUMAN = "human"
    AI = "ai"


class PendingPlay(BaseModel):
    face_up: str       # CardName value
    face_down: str     # CardName value
    actor_id: str      # who played
    target_id: str | None = None  # for FFA: who is the target


class Player(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: PlayerType = PlayerType.HUMAN
    team: TeamId | None = None
    ai_difficulty: AIDifficulty | None = None

    hand: list[str] = Field(default_factory=list)          # CardName values
    recruited: list[str] = Field(default_factory=list)     # CardName values in play
    position: int = 0                                       # board position for display (0-indexed, mod board_size)
    home_position: int = 0
    total_steps: int = 0                                    # cumulative signed steps from home (not mod) — used for catching
    discards_used: int = 0
    max_discards: int = 4
    eliminated: bool = False

    def hand_cards(self) -> list[Card]:
        return [Card(CardName(n)) for n in self.hand]

    def recruited_cards(self) -> list[Card]:
        return [Card(CardName(n)) for n in self.recruited]

    def count_in_play(self, name: CardName) -> int:
        return self.recruited.count(name.value)

    def add_to_hand(self, card: Card) -> None:
        self.hand.append(card.name.value)

    def remove_from_hand(self, card: Card) -> bool:
        try:
            self.hand.remove(card.name.value)
            return True
        except ValueError:
            return False

    def recruit_card(self, card: Card) -> None:
        self.recruited.append(card.name.value)

    def hand_size_limit(self) -> int:
        return settings.hand_size_limit


class Team(BaseModel):
    id: TeamId
    player_ids: list[str] = Field(default_factory=list)
    meeple_position: int = 0
    home_position: int = 0
    recruited: list[str] = Field(default_factory=list)
    active_player_index: int = 0  # which teammate plays next within team turn
    total_steps: int = 0          # cumulative signed steps for catching detection

    def count_in_play(self, name: CardName) -> int:
        return self.recruited.count(name.value)


class GamePhase(str, Enum):
    WAITING = "waiting"
    PLAY = "play"           # current player must play 2 cards
    RECRUIT = "recruit"     # opponent must choose which card to recruit
    END_CHECK = "end_check" # checking win/lose conditions
    FFA_TARGET = "ffa_target"  # FFA: active player must choose a target
    PASS_SCREEN = "pass_screen"  # local hot-seat: show "pass device" screen
    FINISHED = "finished"


class EndReason(str, Enum):
    CAUGHT = "caught"
    THREE_MASTERMINDS = "three_masterminds"
    THREE_SHOW_OFFS = "three_show_offs"
    OUT_OF_CARDS = "out_of_cards"


class GameResult(BaseModel):
    winner_id: str | None = None   # None = draw (shouldn't happen with active-player rule)
    loser_id: str | None = None
    reason: EndReason


BOARD_SIZE: int = settings.board_size  # kept for backward compat; prefer settings.board_size


class TimerState(BaseModel):
    """Server-side authoritative timer state. Serialized in every game broadcast."""
    game_start: float | None = None          # time.time() when game started
    turn_start: float | None = None          # time.time() when turn clock started
    turn_active: bool = False                # True = clock is running
    player_time_used: dict[str, float] = Field(default_factory=dict)   # player_id → cumulative seconds
    player_warnings_sent: dict[str, list[float]] = Field(default_factory=dict)  # player_id → fractions warned


class GameState(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mode: GameMode
    phase: GamePhase = GamePhase.WAITING
    players: list[Player] = Field(default_factory=list)
    teams: list[Team] | None = None   # only for 2v2 and 2v1 modes
    deck: list[str] = Field(default_factory=list)     # CardName values (face-down draw pile)
    discard_pile: list[str] = Field(default_factory=list)
    active_player_index: int = 0     # index into self.players
    pending_play: PendingPlay | None = None
    result: GameResult | None = None
    turn_number: int = 0
    board_size: int = BOARD_SIZE
    ai_difficulty: AIDifficulty | None = None

    # For team modes: whose sub-turn within the team is it
    team_play_state: dict[str, Any] = Field(default_factory=dict)

    # Timer state (authoritative in online mode; informational in local/solo)
    timer: TimerState = Field(default_factory=TimerState)
    timer_config: dict[str, Any] = Field(default_factory=dict)

    def active_player(self) -> Player:
        return self.players[self.active_player_index]

    def get_player(self, player_id: str) -> Player | None:
        return next((p for p in self.players if p.id == player_id), None)

    def deck_cards(self) -> list[Card]:
        return [Card(CardName(n)) for n in self.deck]

    def draw_card(self) -> Card | None:
        if not self.deck:
            return None
        name = self.deck.pop(0)
        return Card(CardName(name))

    def is_finished(self) -> bool:
        return self.phase == GamePhase.FINISHED

    def board_distance(self, from_pos: int, to_pos: int) -> int:
        """Clockwise distance from from_pos to to_pos."""
        return (to_pos - from_pos) % self.board_size


def init_game(
    mode: GameMode,
    player_names: list[str],
    ai_difficulty: AIDifficulty | None = None,
    first_player_index: int = 0,
) -> GameState:
    """Create and return a fresh GameState ready to play."""
    deck = build_deck()
    random.shuffle(deck)

    players: list[Player] = []
    teams: list[Team] | None = None

    bs = settings.board_size

    if mode == GameMode.LOCAL_FFA:
        assert len(player_names) == 4
        spacing = bs // 4
        for i, name in enumerate(player_names):
            home = (i * spacing) % bs
            p = Player(
                name=name,
                home_position=home,
                position=home,
                max_discards=settings.default_max_discards,
            )
            players.append(p)

    elif mode in (GameMode.LOCAL_2V2, GameMode.LOCAL_2V1):
        assert len(player_names) in (3, 4)
        team_a = Team(id=TeamId.TEAM_A, home_position=0, meeple_position=0)
        team_b = Team(id=TeamId.TEAM_B, home_position=bs // 2, meeple_position=bs // 2)

        for i, name in enumerate(player_names):
            team_id = TeamId.TEAM_A if i < len(player_names) // 2 else TeamId.TEAM_B
            if mode == GameMode.LOCAL_2V1 and len(player_names) == 3 and i == 2:
                max_d = settings.team_2v1_discard_solo      # solo player
            elif mode == GameMode.LOCAL_2V1:
                max_d = settings.team_2v1_discard_per_member
            else:
                max_d = settings.default_max_discards
            home = 0 if team_id == TeamId.TEAM_A else bs // 2
            p = Player(name=name, team=team_id, home_position=home, max_discards=max_d)
            if team_id == TeamId.TEAM_A:
                team_a.player_ids.append(p.id)
            else:
                team_b.player_ids.append(p.id)
            players.append(p)

        teams = [team_a, team_b]

    else:
        # 1v1 or solo
        assert len(player_names) == 2
        for i, name in enumerate(player_names):
            home = 0 if i == 0 else bs // 2
            is_ai = (mode == GameMode.SOLO and name == "__AI__")
            p = Player(
                name=name,
                type=PlayerType.AI if is_ai else PlayerType.HUMAN,
                home_position=home,
                position=home,
                ai_difficulty=ai_difficulty if is_ai else None,
                max_discards=settings.default_max_discards,
            )
            players.append(p)

    # Deal initial hand to each player
    for player in players:
        for _ in range(settings.hand_size_limit):
            if deck:
                player.hand.append(deck.pop(0).name.value)

    # Timer config snapshot sent to clients
    timer_config = {
        "game_time_limit": settings.game_time_limit,
        "player_time_limit": settings.player_time_limit,
        "turn_time_limit": settings.turn_time_limit,
        "turn_countdown_threshold": settings.turn_countdown_threshold,
        "player_warning_fractions": settings.player_warning_fractions_list,
    }

    state = GameState(
        mode=mode,
        phase=GamePhase.PLAY,
        players=players,
        teams=teams,
        deck=[c.name.value for c in deck],
        active_player_index=first_player_index,
        ai_difficulty=ai_difficulty,
        board_size=bs,
        timer=TimerState(
            game_start=time.time(),
            player_time_used={p.id: 0.0 for p in players},
            player_warnings_sent={p.id: [] for p in players},
        ),
        timer_config=timer_config,
    )
    return state
