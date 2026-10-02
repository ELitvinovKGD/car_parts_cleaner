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
    comfyui_timeout_seconds: float = Field(default=300.0, gt=0.0, le=3600.0)
    comfyui_poll_interval_seconds: float = Field(default=1.0, gt=0.0, le=30.0)
    mask_threshold: int = Field(default=127, ge=0, le=255)
    mask_feather_radius: float = Field(default=8.0, ge=0.0, le=128.0)
    crop_padding_ratio: float = Field(default=0.5, ge=0.0, le=3.0)
    max_model_edge: int = Field(default=1024, ge=256, le=4096)


def get_settings() -> Settings:
    return Settings()
