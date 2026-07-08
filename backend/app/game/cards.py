from enum import Enum
from dataclasses import dataclass


class CardName(str, Enum):
    SPRINTER = "Sprinter"
    PRANKSTER = "Prankster"
    MASTERMIND = "Mastermind"
    BLITZER = "Blitzer"
    SHOW_OFF = "Show-off"
    LOOKOUT = "Lookout"
    BEST_BUDDY = "Best Buddy"
    SNITCH = "Snitch"


# Special icon values (non-numeric outcomes)
WIN = "WIN"
LOSE = "LOSE"

# Movement values per card type: [1st_copy, 2nd_copy, 3rd+_copy]
# None means "no movement (0)", WIN/LOSE are string sentinels
CARD_VALUES: dict[CardName, list] = {
    CardName.SPRINTER:    [1,    2,    3],
    CardName.PRANKSTER:   [-1,   6,    -1],
    CardName.MASTERMIND:  [0,    0,    WIN],
    CardName.BLITZER:     [-1,   -1,   -2],
    CardName.SHOW_OFF:    [2,    3,    LOSE],
    CardName.LOOKOUT:     [0,    2,    6],
    CardName.BEST_BUDDY:  [4,    4,    4],   # unique, always +4
    CardName.SNITCH:      [-3,   -3,   -3],  # unique, always -3
}

# How many copies of each card exist in the deck
CARD_COUNTS: dict[CardName, int] = {
    CardName.SPRINTER:   6,
    CardName.PRANKSTER:  6,
    CardName.MASTERMIND: 6,
    CardName.BLITZER:    6,
    CardName.SHOW_OFF:   6,
    CardName.LOOKOUT:    6,
    CardName.BEST_BUDDY: 1,
    CardName.SNITCH:     1,
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
