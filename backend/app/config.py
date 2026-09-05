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

    # векторный поиск (Qdrant + локальные эмбеддинги fastembed)
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "projectai_knowledge"
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embed_fake: bool = False  # тесты: детерминированный эмбеддер без скачивания модели

    api_port: int = 8010
    jwt_secret: str = "dev-secret"
    jwt_ttl_hours: int = 24 * 14
    cors_origins: str = "http://localhost:3010"

    data_dir: str = "./data"

    claude_bin: str = "claude"
    ai_analysis_enabled: bool = True
    ai_max_files_per_run: int = 40
    ai_batch_size: int = 12
    ai_concurrency: int = 15
    claude_timeout_sec: int = 600
    #: потолок ходов для служебных JSON-вызовов (план RLM, синтез, извлечение задач).
    #: Инструменты им не даются, зацикливаться не на чем — запас нужен на случай,
    #: когда модель тратит первый ход на размышление и не успевает выдать ответ.
    claude_max_turns: int = 12
    #: сколько фоновых задач (индексация, проработка, планировщик) идёт одновременно
    job_concurrency: int = 5
    #: доисследование по невыясненным вопросам — второй заход RLM плюс пересборка
    #: описания. По замерам на фикстурах прироста качества не дало, а время удваивало,
    #: поэтому выключено; включается, когда точность важнее скорости.
    enrich_followup: bool = False

    # --- глубина RLM ---
    #: 1 — корень и один слой под-агентов (без углубления, дешевле всего);
    #: 2 и больше — под-агент может задать свои вопросы и породить собственный слой;
    #: 0 — без ограничения глубины (держат только жёсткий потолок и бюджет узлов ниже).
    rlm_max_depth: int = 2
    #: сколько уточняющих вопросов берётся с ОДНОЙ ветки на каждом уровне
    rlm_branching: int = 2
    #: предохранитель: сколько всего вложенных исследований допустимо за один прогон
    rlm_max_nodes: int = 8
    # модель для фоновой индексации/анализа (чат настраивается отдельно, по умолчанию opus)
    ai_model: str = "sonnet"
    ai_reasoning: str = "low"
    chat_default_model: str = "opus"
    chat_default_reasoning: str = "high"
    #: язык ИИ-контента (обзоры, досье, задачи из материалов) и сообщений фоновых
    #: работ: ru | en. Язык интерфейса выбирается в браузере отдельно.
    ai_language: str = "en"

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
