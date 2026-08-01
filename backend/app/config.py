from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# корень репозитория (…/project-ai)
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://projectai:projectai@localhost:5432/projectai"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j"

    api_port: int = 8010
    jwt_secret: str = "dev-secret"
    jwt_ttl_hours: int = 24 * 14
    cors_origins: str = "http://localhost:3010"

    data_dir: str = "./data"

    claude_bin: str = "claude"
    ai_analysis_enabled: bool = True
    ai_max_files_per_run: int = 40
    ai_batch_size: int = 6
    ai_concurrency: int = 2
    claude_timeout_sec: int = 600
    # модель для фоновой индексации/анализа (чат настраивается отдельно, по умолчанию opus)
    ai_model: str = "sonnet"
    ai_reasoning: str = "low"
    chat_default_model: str = "opus"
    chat_default_reasoning: str = "high"

    whisper_model: str = "large-v3"
    whisper_device: str = "auto"

    # наблюдение за каталогом: пауза после последнего изменения до запуска индекса
    watch_debounce_sec: float = 20.0

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        if not p.is_absolute():
            p = REPO_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
