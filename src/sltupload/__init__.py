from pathlib import Path

from sltupload.config import get_settings


def main() -> None:
    """Run the application with Uvicorn."""
    import uvicorn

    settings = get_settings()
    ssl_key = settings.site_ssl_key
    ssl_cert = settings.site_ssl_cert
    if ssl_key is not None and ssl_cert is not None and Path(ssl_key).exists() and Path(ssl_cert).exists():
        uvicorn.run(
            app="sltupload.app:app",
            host=settings.host,
            port=settings.port,
            ssl_keyfile=ssl_key,
            ssl_certfile=ssl_cert,
        )
        return

    uvicorn.run(app="sltupload.app:app", host=settings.host, port=settings.port)
