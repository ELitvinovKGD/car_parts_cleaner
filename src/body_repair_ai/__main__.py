import uvicorn

from body_repair_ai.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "body_repair_ai.web:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
