from sltupload.config import get_settings
from pathlib import Path


def main() -> None:
    """Run the application with Uvicorn."""
    import uvicorn

    settings = get_settings()
    if settings.ssl_certfile is not None and settings.ssl_keyfile is not None and Path(settings.ssl_keyfile).exists() and Path(settings.ssl_certfile).exists():
        uvicorn.run(
            app="sltupload.app:app",
            host=settings.host,
            port=settings.port,
            ssl_keyfile=settings.ssl_keyfile,
            ssl_certfile=settings.ssl_certfile,
        )
    else:
      uvicorn.run(app="sltupload.app:app", host=settings.host, port=settings.port)
