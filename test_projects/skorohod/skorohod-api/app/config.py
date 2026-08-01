"""Конфигурация сервиса.

Всё читается из переменных окружения (в dev — из `.env`, см. `.env.example`).
Имена полей совпадают с именами переменных без учёта регистра:
`DATABASE_URL` -> `database_url`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения.

    Денежные величины — в копейках (int), как и везде в проекте.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- инфраструктура ---
    database_url: str = "postgresql+psycopg://skorohod:skorohod@localhost:5432/skorohod"
    db_echo: bool = False
    db_pool_size: int = 10

    # --- авторизация ---
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_ttl_seconds: int = 60 * 60 * 24 * 14

    # --- платёжный провайдер ---
    payments_api_key: str = "test_change-me"
    payments_webhook_secret: str = "change-me"
    payments_base_url: str = "https://api.pay-provider.ru/v3"
    payments_timeout_s: float = 8.0
    payments_retries: int = 3

    # --- уведомления ---
    sms_token: str = "change-me"
    sms_sender: str = "Skorohod"

    # --- ценообразование доставки ---
    surge_enabled: bool = True
    #: базовая стоимость доставки, 149 ₽
    base_delivery_kop: int = 14900
    #: с этой суммы корзины доставка бесплатная, 2500 ₽
    free_delivery_from_kop: int = 250000
    #: дальше этого радиуса от ресторана не возим
    max_delivery_radius_m: int = 12000
    #: первые N метров входят в базовую стоимость
    free_distance_m: int = 3000
    #: цена за каждый начатый километр сверх free_distance_m
    price_per_km_kop: int = 1900
    #: ночная наценка (доля от базы + расстояния)
    night_rate: float = 0.15
    #: потолок surge-коэффициента
    surge_max: float = 2.0

    # --- прочее ---
    tz: str = "Europe/Moscow"
    cors_origin: str = "http://localhost:3020"
    assign_loop_interval_s: float = 5.0
    stale_order_minutes: int = 30


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Синглтон настроек. Отдельная функция — чтобы подменять в тестах."""
    return Settings()


settings = get_settings()
