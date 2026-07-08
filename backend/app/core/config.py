from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Server / security ----
    server_password: str = "change_me"
    port: int = 8000
    allowed_origins: str = "http://localhost:8000"
    max_rooms: int = 50
    auth_rate_limit: int = 5          # max failed WS auth attempts per IP per minute
    session_timeout_minutes: int = 120
    ws_auth_timeout: int = 5          # seconds to authenticate before WS closes
    room_idle_timeout: int = 1800     # seconds of inactivity before room auto-closes

    # ---- User accounts ----
    jwt_secret: str = "change_jwt_secret_before_deploying"
    jwt_expire_hours: int = 720       # 30 days
    database_url: str = "sqlite+aiosqlite:///./tag_game.db"

    # ---- Game board constants ----
    board_size: int = 24              # total spaces on the circular track
    hand_size_limit: int = 4          # max cards in hand
    default_max_discards: int = 4     # discards allowed per player (2v1 solo player overrides this)
    team_2v1_discard_per_member: int = 2   # each teammate in 2v1 gets this many discards
    team_2v1_discard_solo: int = 4    # the solo player in 2v1 gets this many discards

    # ---- Game timers (all in seconds) ----
    game_time_limit: int = 1800       # 30 minutes: max total game duration
    player_time_limit: int = 900      # 15 minutes: max total time per player across all turns
    turn_time_limit: int = 120        # 2 minutes: max time per individual turn
    turn_countdown_threshold: int = 30  # show visual countdown when ≤ this many seconds remain
    animation_grace_seconds: int = 6  # seconds to wait for turn_ready before auto-starting clock
    player_warning_fractions: str = "0.25,0.5,0.75"  # warn when this fraction of player_time_limit is used

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    @property
    def player_warning_fractions_list(self) -> list[float]:
        return [float(f.strip()) for f in self.player_warning_fractions.split(",") if f.strip()]


settings = Settings()
