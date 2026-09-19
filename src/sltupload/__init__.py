from sltupload.config import get_settings


def main() -> None:
    """Run the application with Uvicorn."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(app="sltupload.app:app", host=settings.host, port=settings.port)
