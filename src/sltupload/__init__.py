from sltupload.config import get_settings
from pathlib import Path


def main() -> None:
    """Run the application with Uvicorn."""
    import uvicorn

    settings = get_settings()
    if settings.site_ssl_cert is not None and settings.site_ssl_key is not None and Path(settings.site_ssl_key).exists() and Path(settings.site_ssl_cert).exists():
        uvicorn.run(
            app="sltupload.app:app",
            host=settings.host,
            port=settings.port,
            ssl_keyfile=settings.site_ssl_key,
            ssl_certfile=settings.site_ssl_cert,
        )
    else:
      uvicorn.run(app="sltupload.app:app", host=settings.host, port=settings.port)
