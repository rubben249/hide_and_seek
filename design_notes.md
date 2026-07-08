# TAG! — Design Notes & Agent Avenue Analysis

## Agent Avenue Analysis

### Core Mechanic
Agent Avenue is a 2-player (or team) card-driven race game. Both players move a single meeple around a circular track, trying to catch the opponent's meeple. The key tension is in the **Recruit step**: you play 2 cards (1 face-up, 1 face-down) and your **opponent chooses which one to take** — but you always get the other. This creates a push-pull of information and bluffing.

### The 8 Agent Card Types

| Card | Values (1st/2nd/3rd+) | Role |
|------|----------------------|------|
| Double Agent | −1 / +6 / −1 | High-risk/high-reward; sweet spot is exactly 2 |
| Enforcer | +1 / +2 / +3 | Safe, steady forward movement |
| Codebreaker | 0 / 0 / WIN | Alternate win condition (collect 3) |
| Saboteur | −1 / −1 / −2 | Always negative — a trap card |
| Daredevil | +2 / +3 / LOSE | Fast but dangerous (3 = instant loss) |
| Sentinel | 0 / +2 / +6 | Slow buildup, massive payoff |
| Sidekick | +4 | Unique, always strong |
| Mole | −3 | Unique, always hurts |

### Win/Lose Conditions (Simple Mode)
- **A:** Catch opponent's meeple → WIN
- **B:** 3 Codebreakers in play → WIN  
- **C:** 3 Daredevils in play → LOSE

### The Board
Double-sided circular track (~24 spaces). Players start on opposite sides (home spaces). Advanced mode adds 4 Black Market Spots in the corners of the loop.

### Black Market Cards (15 total — Advanced Mode)
Gained by landing **exactly** on designated board spaces. Two types:
- **⚡ Instant:** One-time effect, then discarded
- **∞ Ongoing:** Placed in front of player, permanently active

Known card effects:
- Security System (∞): Win if opponent is on your home space
- Getaway Car (∞): +3 when landing on any home space
- Masterplan (∞): Win with 7 different agent types in play
- Outpost (∞): Hand size reduced to 3
- Mind Control (⚡): Remove opponent's agent from play (no movement)
- Secret Recruit (⚡): Recruit from hand freely; move pawn
- Spycation (⚡): Return own agent to hand; may re-recruit

### Team Variant
3–4 players in 2 teams. Teammates share 1 meeple and 1 pool of recruited cards. Each has own hand, cannot show cards to teammate. On team's turn, each teammate plays 1 card (one face-up, one face-down). Opposing team agrees on which to recruit.

---

## TAG! Design Decisions

### Theme Mapping
The spy/espionage theme maps naturally to a schoolyard tag game:
- Secret agents → Playground kids
- Recruiting neighbors → Recruiting classmates
- Meeples chasing → Kids playing tag
- Black market → Playground perks (hidden advantages found on the field)
- Neighborhood board → Schoolyard loop

### Card Name Mapping
| Agent Avenue | TAG! | Reasoning |
|---|---|---|
| Double Agent | Prankster | Unpredictable, chaotic, fakes you out |
| Enforcer | Sprinter | Reliable runner |
| Codebreaker | Mastermind | Strategic planner, alternate win |
| Saboteur | Blitzer | Disrupts everyone, always negative |
| Daredevil | Show-off | Fast but risky, flashy |
| Sentinel | Lookout | Patient, watchful, explosive payoff |
| Sidekick | Best Buddy | Loyal friend, always +4 |
| Mole | Snitch | Tattletale, always hurtful |

### Playground Perk Mapping
| Agent Avenue | TAG! |
|---|---|
| Security System | Yard Monitor |
| Getaway Car | Skateboard |
| Watchtower HQ | Treehouse |
| Sinister Twin | Copycat |
| Supercomputer | Smartwatch |
| Leader of the Pack | Pack Leader |
| Masterplan | Grand Strategy |
| Outpost | Jungle Gym |
| Distraction Device | Distraction |
| Smoke Screen | Smoke Bomb |
| Brainstorming Device | Bright Idea |
| Double Trouble | Double Trouble |
| Mind Control | Mind Games |
| Secret Recruit | New Kid |
| Spycation | Time Out |

### Rules Preserved 100%
All game mechanics are identical to Agent Avenue:
- 2 cards played (1 face-up, 1 face-down, different names)
- Opponent chooses 1; you take the other
- Movement based on count (1st/2nd/3rd+) of same-name cards
- Win by catching pawn, or 3 Masterminds
- Lose by 3 Show-offs
- Optional discard (4 times total)
- Running-out-of-cards tiebreaker
- Active player wins all ties
- Playground Spot landing (exact) → take perk
- Crossing a spot doesn't count
- Team variant: 1 card per teammate, opposing team picks together

---

## Files in This Project

```
pilla_pilla/
├── rulebook.md              ← Complete rulebook (EN)
├── design_notes.md          ← This file
└── cards/
    ├── kid_cards.md         ← All 38 kid card definitions
    └── playground_cards.md  ← All 15 playground perk definitions
```

## Next Steps (Suggestions)

1. **Board layout:** Design a schoolyard loop (~24 spaces) with:
   - Home spaces at opposite ends (labeled with colors)
   - Simple side: plain loop
   - Advanced side: 4 Playground Spot (⬡) spaces at corners
   
2. **Card art brief:** 
   - Kid cards: each type has a distinct kid character (Sprinter = athlete, Prankster = class clown, Mastermind = glasses/book kid, Blitzer = big kid, Show-off = dramatic performer, Lookout = quiet observer)
   - Playground perks: schoolyard items/situations

3. **Playtesting:** The card values are identical to Agent Avenue's tested balance. Only the theme and card names differ.

4. **Print & Play:** A print-ready version would need card templates sized for standard card sleeves (63×88mm poker size).
