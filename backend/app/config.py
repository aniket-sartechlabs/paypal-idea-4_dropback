from functools import lru_cache
import os

from pydantic import field_validator, model_validator

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    database_url: str = "sqlite:///./dropback.db"
    paypal_env: str = "sandbox"
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    paypal_sandbox_buyer_email: str = ""
    paypal_sandbox_buyer_password: str = ""
    paypal_webhook_id: str = ""
    channel3_api_key: str = ""
    channel3_webhook_secret: str = ""
    app_base_url: str = "http://localhost:5173"
    llm_provider: str = "auto"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    gemini_api_key: str = ""
    secret_key: str = ""
    merchant_email: str = ""
    merchant_password: str = ""
    session_cookie_secure: bool = False
    # Bearer token required by the DropBack MCP endpoint (/mcp). Leave empty to disable it.
    mcp_api_token: str = ""
    # Production sign-up needs this invite code; without it, production sign-up stays closed.
    signup_code: str = ""
    # Seed the demo catalog (Sony / AirPods / Kindle) when the catalog is empty. Always on in development.
    demo_catalog: bool = False
    # Built React app served by FastAPI in the single-service deployment (Render / Docker).
    static_dir: str = ""

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, value: str) -> str:
        """Render and Heroku-style URLs (postgres://, postgresql://) -> SQLAlchemy's psycopg 3 driver."""
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value

    @model_validator(mode="after")
    def _platform_url(self):
        """On Render, use the service's public URL for links, webhooks, and allowed origins."""
        external = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
        if external and "localhost" in self.app_base_url:
            self.app_base_url = external
        base = self.app_base_url.rstrip("/")
        if base and base not in self.cors_origins:
            self.cors_origins = [*self.cors_origins, base]
        return self

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def paypal_ready(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
