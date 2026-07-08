# TAG! — The Playground Chase

A digital implementation of a 2–4 player circular board chase game. Kids recruit friends, play ability cards, and try to tag their opponents before running out of tricks.

---

## Quick Start

```bash
./run.sh
```

This single command:
1. Updates `uv` to the latest version
2. Upgrades all Python dependencies in `uv.lock`
3. Builds and launches the Docker/Podman container
4. Waits for the server to be ready
5. Opens your browser at `http://localhost:8000`

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Backend | Python 3.12 + FastAPI 0.115 | Async ASGI, native WebSocket |
| Data models | Pydantic v2 + pydantic-settings | Auto-validation, typed .env |
| Database | SQLite + SQLAlchemy async + aiosqlite | Single-file DB, no extra service |
| Auth | bcrypt + PyJWT | Password hashing + JWT tokens |
| Server | Uvicorn (standard) | ASGI with WebSocket support |
| Package manager | uv | Fast, lock-file based, venv integrated |
| Frontend | HTML5 + CSS3 + JS (vanilla) | No npm/node — served as static files |
| Container | Docker / Podman + Compose | Single container, serves everything |

---

## Project Structure

```
pilla_pilla/
├── run.sh                        # One-command launcher
├── docker-compose.yml
├── .env                          # Local secrets (not committed)
├── .env.example                  # Template for .env
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml            # uv dependencies
│   ├── .python-version           # "3.12"
│   ├── uv.lock
│   └── app/
│       ├── main.py               # FastAPI app, lifespan, mounts
│       ├── game/
│       │   ├── cards.py          # Card definitions and deck builder
│       │   ├── models.py         # GameState, Player, Team (Pydantic)
│       │   ├── engine.py         # Game rules: play, recruit, movement, win/lose
│       │   └── ai.py             # AI: Beginner / Veteran / Maestro
│       ├── api/
│       │   ├── routes.py         # REST endpoints (solo + local modes)
│       │   ├── auth.py           # User auth: register, login, profile
│       │   └── websocket.py      # WebSocket handler (online mode + chat)
│       ├── core/
│       │   ├── config.py         # Settings from .env (pydantic-settings)
│       │   └── security.py       # WS rate limiting + session tokens
│       └── db/
│           ├── database.py       # SQLAlchemy async engine + session factory
│           ├── models.py         # ORM: User, UserStats, GameRecord, GameParticipant
│           └── crud.py           # DB operations: create_user, record_game_result, leaderboard
│
└── frontend/
    ├── index.html                # Single-page app (6 screens)
    ├── css/styles.css
    └── js/
        ├── app.js                # Main controller, screen routing, game logic
        ├── game.js               # Board renderer (SVG), card DOM, hand render
        ├── ws.js                 # GameSocket class for online mode
        └── ai_client.js          # REST client for solo mode
```

---

## Setup

### Option A: Docker / Podman (recommended)

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env: set SERVER_PASSWORD, JWT_SECRET, and other values

# 2. Launch (one command does everything)
./run.sh
```

### Option B: Local development (no Docker)

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

cd backend

# Install dependencies
uv sync

# Create .env at project root (pilla_pilla/.env)
cp ../.env.example ../.env

# Run the server
uv run uvicorn app.main:app --reload --port 8000
```

The server serves the frontend at `http://localhost:8000` and the API at `http://localhost:8000/api/`.

---

## Game Modes

### Solo vs AI

One human vs a computer opponent. The AI only ever sees public information (both players' recruited cards, board positions, deck size) — it never peeks at the human's hand.

| Difficulty | Strategy |
|---|---|
| Beginner | Random valid moves |
| Veteran | 1-turn minimax (worst-case best move) |
| Maestro | Minimax depth 2–3 + Bayesian hand probability from seen/discarded cards |

### Local Multiplayer (Hot-Seat)

All players share the same screen. When it's Player 2's turn, the app shows a "Pass the device" screen to prevent peeking.

| Sub-mode | Players | Notes |
|---|---|---|
| 1v1 | 2 | Standard duel |
| 2v2 | 4 | Teams of 2, shared meeple + recruited pile |
| 2v1 | 3 | Solo player gets 4 discards; each teammate gets 2 (official balance rule) |
| Free-for-All | 4 | Each turn: choose a target → play cards → only those 2 move |

### Online (WebSocket)

Multiple players connect over the internet. Full auth flow, room system, and real-time sync via WebSocket.

---

## Game Rules Summary

**Board**: 24-space circular track. Each player starts at their home space (0 and 12 for 1v1; 0, 6, 12, 18 for FFA).

**Turn structure**:
1. **Play** — Active player plays 2 cards face-up and face-down
2. **Recruit** — Opponent picks 1 card to keep; active player keeps the other
3. **Move** — Both players move their meeple according to their new card's value (1st, 2nd, or 3rd copy they hold)
4. **Draw** — Both players draw back to 4 cards

**Win conditions**:
- **Catch** — Your meeple reaches or passes the opponent's (cumulative steps, not position mod 24)
- **3 Masterminds recruited** — Instant win
- **Opponent gets 3 Show-offs** — They lose
- **Deck exhausted + opponent has < 2 cards** — Win by distance

---

## REST API Reference

Base path: `/api`

### Health

```
GET /api/health
→ {"status": "ok", "active_games": 3}
```

### User Auth

```
POST /api/auth/register
Body: {"username": "alice", "email": "alice@example.com", "password": "hunter42"}
→ {"access_token": "...", "token_type": "bearer", "username": "alice", "user_id": "..."}

POST /api/auth/login
Body: {"username": "alice", "password": "hunter42"}
→ {"access_token": "...", "token_type": "bearer", "username": "alice", "user_id": "..."}

GET /api/auth/me          (Authorization: Bearer <token>)
→ {"username": "alice", "games_played": 12, "wins": 7, "losses": 5, "win_rate": 58.3, ...}

GET /api/auth/leaderboard
→ {"leaderboard": [{"username": "alice", "wins": 7, "games_played": 12, "win_rate": 58.3}, ...]}
```

### Solo Mode

```
POST /api/solo/new
Body: {"player_name": "Alice", "difficulty": "veteran"}
→ {"game_id": "...", "state": {...}}

POST /api/game/play
Body: {"game_id": "...", "player_id": "...", "face_up": "Sprinter", "face_down": "Lookout"}
→ {"state": {...}, "ai_recruited": "face_up"}   # AI auto-recruits in solo mode

POST /api/game/recruit
Body: {"game_id": "...", "player_id": "...", "choice": "face_up"}
→ {"state": {...}, "ai_played": {"face_up": "Mastermind", "face_down": "Blitzer"}}
```

### Local Mode

```
POST /api/local/new
Body: {"mode": "local_1v1", "player_names": ["Alice", "Bob"]}
Body: {"mode": "local_2v2", "player_names": ["Alice", "Bob", "Carol", "Dave"]}
Body: {"mode": "local_2v1", "player_names": ["Alice", "Bob", "Solo"]}
Body: {"mode": "local_ffa", "player_names": ["Alice", "Bob", "Carol", "Dave"]}
→ {"game_id": "...", "state": {...}}

POST /api/game/discard
Body: {"game_id": "...", "player_id": "...", "card_name": "Show-off"}

GET /api/game/{game_id}
→ {"state": {...}}
```

---

## WebSocket Protocol (Online Mode)

Connect to `ws://localhost:8000/ws`

### 1. Authentication (required within 5 seconds)

```json
// Client → Server (must be first message)
{"type": "auth", "password": "your_server_password", "player_name": "Alice"}

// Server → Client (success)
{"type": "auth_ok", "token": "550e8400-e29b-41d4-a716-446655440000", "player_name": "Alice"}

// Server → Client (failure)
{"type": "error", "code": "auth_failed", "message": "Invalid password"}
```

All subsequent messages must include `"token": "<your_token>"`.

### 2. Room Management

```json
// Create a room
{"type": "create_room", "token": "...", "mode": "local_1v1"}
→ {"type": "room_created", "room_id": "AB12", "mode": "local_1v1", "max_players": 2}

// Join a room
{"type": "join_room", "token": "...", "room_id": "AB12"}
→ broadcast: {"type": "player_joined", "room_id": "AB12", "players": [...], "ready": true}

// List open rooms
{"type": "list_rooms", "token": "..."}
→ {"type": "room_list", "rooms": [{"room_id": "AB12", "mode": "local_1v1", "players": 1, "max_players": 2}]}

// Leave a room
{"type": "leave_room", "token": "..."}
```

### 3. Gameplay

```json
// Start game (any player once room is full)
{"type": "start_game", "token": "..."}
→ broadcast: {"type": "game_started", "state": {...}}

// Play cards
{"type": "play_cards", "token": "...", "face_up": "Sprinter", "face_down": "Lookout"}
// FFA: add "target_id": "<player_id>"

// Recruit
{"type": "recruit", "token": "...", "choice": "face_up"}

// Discard
{"type": "discard", "token": "...", "card_name": "Show-off"}

// All game actions broadcast:
→ {"type": "game_state", "state": {...}}
// On finish:
→ {"type": "game_over", "result": {"winner_id": "...", "loser_id": "...", "reason": "caught"}}
```

### 4. Chat

```json
// Global chat (everyone in the room)
{"type": "chat_all", "token": "...", "text": "Good game!"}
→ broadcast: {"type": "chat_all", "from": "Alice", "text": "Good game!", "ts": 1720000000.0}

// Team chat (only your teammates receive it — 2v2 / 2v1 modes)
{"type": "chat_team", "token": "...", "text": "Go left!"}
→ team broadcast: {"type": "chat_team", "team": "A", "from": "Alice", "text": "Go left!", "ts": ...}

// Quick reactions
{"type": "reaction", "token": "...", "reaction": "fire"}
→ broadcast: {"type": "reaction", "from": "Alice", "reaction": "fire", "emoji": "🔥", "ts": ...}
```

#### Available Reactions

| Key | Emoji | Label |
|---|---|---|
| `good_play` | 👍 | Good Play |
| `haha` | 😂 | Haha |
| `wow` | 😮 | Wow |
| `fire` | 🔥 | Fire |
| `cry` | 😢 | Oof |
| `angry` | 😡 | Angry |
| `celebrate` | 🎉 | Celebrate |
| `well_played` | 👏 | Well Played |

### 5. Keepalive

```json
{"type": "ping", "token": "..."}
→ {"type": "pong"}
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SERVER_PASSWORD` | `change_me` | Password to join online mode (share with players) |
| `PORT` | `8000` | Port the server listens on |
| `ALLOWED_ORIGINS` | `http://localhost:8000` | Comma-separated CORS origins |
| `MAX_ROOMS` | `50` | Max concurrent online rooms |
| `AUTH_RATE_LIMIT` | `5` | Max failed WS auth attempts per IP per minute |
| `SESSION_TIMEOUT_MINUTES` | `120` | WS session token lifetime |
| `JWT_SECRET` | `change_me` | Secret key for signing JWT tokens |
| `JWT_EXPIRE_HOURS` | `720` | JWT lifetime (default: 30 days) |
| `DATABASE_URL` | `sqlite+aiosqlite:///./tag_game.db` | SQLAlchemy async DB URL |

---

## Security

### Online Mode (WebSocket)

- Password is validated using `hmac.compare_digest()` (timing-attack safe)
- 5 failed auth attempts per IP per minute → rate-limited with `4029` close code
- Session tokens are UUID4 (not derived from password)
- Rooms idle for 30 minutes are garbage-collected
- `SERVER_PASSWORD` is never echoed back to the client

### User Accounts (JWT)

- Passwords hashed with bcrypt (cost factor 12)
- JWT signed with HS256 using `JWT_SECRET`
- Tokens expire after `JWT_EXPIRE_HOURS` hours
- Email and username uniqueness enforced at DB level
- Username validation: 3–32 chars, alphanumeric + `_` `-` only

---

## Database Schema

```
users
  id            UUID (PK)
  username      TEXT UNIQUE
  email         TEXT UNIQUE
  password_hash TEXT
  created_at    DATETIME

user_stats
  user_id       FK → users.id (PK)
  games_played  INT
  wins          INT
  losses        INT

game_records
  id              UUID (PK)
  mode            TEXT        (solo, local_1v1, local_2v2, ...)
  end_reason      TEXT        (caught, three_masterminds, ...)
  winner_username TEXT
  started_at      DATETIME
  finished_at     DATETIME
  turn_count      INT

game_participants
  id       UUID (PK)
  game_id  FK → game_records.id
  user_id  FK → users.id
  won      BOOL
```

---

## Development

### Running tests

```bash
cd backend
uv run pytest
```

### Adding a new card

1. Add the name to `CardName` enum in [game/cards.py](backend/app/game/cards.py)
2. Add its values to `CARD_VALUES` (list of 3: 1st-copy, 2nd-copy, 3rd-copy effect)
3. Add its count to `CARD_COUNTS`
4. If it has a special effect, handle it in `engine.py:resolve_movement()`

### Watching container logs

```bash
docker compose logs -f
# or
podman-compose logs -f
```

### Rebuilding after code changes

```bash
./run.sh
# or manually:
docker compose up --build -d
```

---

## Cards Reference

### Kid Cards (38-card deck)

| Card | Copies | 1st copy | 2nd copy | 3rd copy |
|---|---|---|---|---|
| Sprinter | 6 | +1 | +2 | +3 |
| Prankster | 6 | −1 | +6 | −1 |
| Mastermind | 6 | 0 | 0 | **WIN** |
| Blitzer | 6 | −1 | −1 | −2 |
| Show-off | 6 | +2 | +3 | **LOSE** |
| Lookout | 6 | 0 | +2 | +6 |
| Best Buddy | 1 | +4 | +4 | +4 |
| Snitch | 1 | −3 | −3 | −3 |

Movement is on the circular 24-space track. Positive = clockwise (chaser advances); Negative = counter-clockwise (runner retreats or chaser overshoots).

---

## License

MIT — do whatever you want with it.
