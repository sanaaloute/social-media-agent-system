"""Central configuration. All values overridable via environment / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Core infrastructure
    database_url: str = "sqlite:///./dev.db"
    redis_url: str = ""  # empty -> in-memory fallback
    queue_mode: str = "eager"  # eager | celery
    dry_run: bool = True  # publishers simulate success instead of live calls

    # Generation providers
    llm_provider: str = "ollama"  # ollama | openrouter | claude | openai
    llm_fallback_provider: str = ""  # backup LLM when the primary fails; "" = none
    image_provider: str = "local"  # local | kie | dalle | stable_diffusion
    video_provider: str = "local"  # local | kie | falai | kling

    # Provider credentials
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    kie_api_key: str = ""
    kie_image_model: str = "gpt-image-1.5"
    kie_video_model: str = "veo3.1"
    stability_api_key: str = ""
    fal_key: str = ""
    kling_api_key: str = ""
    # Local diffusion (optional: pip install -r requirements-local.txt)
    local_image_model: str = "stabilityai/sdxl-turbo"
    local_video_model: str = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
    local_video_seconds: int = 2  # target clip length; >5s uses segment chaining

    # Autopilot (fully autonomous mode; off by default — HITL is the default)
    autopilot_enabled: bool = False
    autopilot_interval_hours: int = 6  # min gap between auto-generated tasks/brand

    # Credential encryption (base64url-encoded 32-byte AES key)
    encryption_key: str = ""

    # Platform app credentials
    meta_app_id: str = ""
    meta_app_secret: str = ""
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    twitter_client_id: str = ""
    twitter_client_secret: str = ""
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""

    # Publishing safety
    max_posts_per_account_per_day: int = 10

    # Local storage paths
    media_cache_dir: str = "./media_cache"
    browser_profiles_dir: str = "./browser_profiles"
    checkpoint_db: str = "checkpoints.db"

    # Outbound proxy for web research / model downloads (e.g. networks where
    # Google News or HuggingFace are unreachable directly). NO_PROXY applies
    # too so local services (Ollama) stay direct.
    http_proxy: str = ""
    no_proxy: str = "localhost,127.0.0.1"


def apply_proxy_settings(settings: "Settings") -> None:
    """Export proxy env vars so httpx (trust_env) picks them up."""
    import os

    if settings.http_proxy:
        os.environ.setdefault("HTTP_PROXY", settings.http_proxy)
        os.environ.setdefault("HTTPS_PROXY", settings.http_proxy)
        os.environ.setdefault("NO_PROXY", settings.no_proxy)


@lru_cache
def get_settings() -> Settings:
    return Settings()
