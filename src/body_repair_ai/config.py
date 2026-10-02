from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_host: str = "127.0.0.1"
    app_port: int = 8000
    data_dir: Path = Path("data")
    inference_backend: str = "mock"
    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_workflow: Path = Path("workflows/remove_dent.json")
    mask_threshold: int = Field(default=127, ge=0, le=255)
    mask_feather_radius: float = Field(default=8.0, ge=0.0, le=128.0)


def get_settings() -> Settings:
    return Settings()
