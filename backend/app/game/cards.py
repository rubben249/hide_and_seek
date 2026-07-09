from enum import Enum
from dataclasses import dataclass


class CardName(str, Enum):
    ENFORCER    = "Enforcer"
    DOUBLE_AGENT = "Double Agent"
    CODEBREAKER = "Codebreaker"
    SABOTEUR    = "Saboteur"
    DAREDEVIL   = "Daredevil"
    SENTINEL    = "Sentinel"
    SIDEKICK    = "Sidekick"
    MOLE        = "Mole"


# Special icon values (non-numeric outcomes)
WIN = "WIN"
LOSE = "LOSE"

# Movement values per card type: [1st_copy, 2nd_copy, 3rd+_copy]
CARD_VALUES: dict[CardName, list] = {
    CardName.ENFORCER:     [1,    2,    3],
    CardName.DOUBLE_AGENT: [-1,   6,    -1],
    CardName.CODEBREAKER:  [0,    0,    WIN],
    CardName.SABOTEUR:     [-1,   -1,   -2],
    CardName.DAREDEVIL:    [2,    3,    LOSE],
    CardName.SENTINEL:     [0,    2,    6],
    CardName.SIDEKICK:     [4,    4,    4],
    CardName.MOLE:         [-3,   -3,   -3],
}

# How many copies of each card exist in the deck
CARD_COUNTS: dict[CardName, int] = {
    CardName.ENFORCER:     6,
    CardName.DOUBLE_AGENT: 6,
    CardName.CODEBREAKER:  6,
    CardName.SABOTEUR:     6,
    CardName.DAREDEVIL:    6,
    CardName.SENTINEL:     6,
    CardName.SIDEKICK:     1,
    CardName.MOLE:         1,
}

TOTAL_CARDS = sum(CARD_COUNTS.values())  # 38


@dataclass(frozen=True)
class Card:
    name: CardName

    def get_movement_value(self, copies_in_play: int) -> int | str:
        """Return movement for this card given how many copies player has in play (including this one)."""
        values = CARD_VALUES[self.name]
        idx = min(copies_in_play - 1, 2)  # cap at index 2 (3rd+)
        return values[idx]

    def __str__(self) -> str:
        return self.name.value

    def __repr__(self) -> str:
        return f"Card({self.name.value})"


def build_deck() -> list[Card]:
    """Build a full shuffled-ready deck of 38 cards."""
    deck: list[Card] = []
    for name, count in CARD_COUNTS.items():
        deck.extend([Card(name)] * count)
    return deck
