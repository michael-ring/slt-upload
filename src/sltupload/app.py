import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from typing import cast

from fastapi import FastAPI
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import UploadFile
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from sltupload.auth import DiscordAuthError
from sltupload.auth import DiscordOAuth
from sltupload.config import Settings
from sltupload.config import get_settings
from sltupload.filesystem import ImageUploader
from sltupload.filesystem import UploadError
from sltupload.filesystem import sanitize_username
from sltupload.filesystem import upload_key
from sltupload.s3 import MAX_CATALOG_COMPONENT_LENGTH
from sltupload.s3 import ProjectCatalog
from sltupload.s3 import ProjectCatalogError
from sltupload.s3 import sanitize_catalog

BASE_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
STYLESHEET_PATH = BASE_DIR / "static" / "styles.css"
PROJECT_TYPEAHEAD_SCRIPT_PATH = BASE_DIR / "static" / "project_typeahead.js"
STATIC_VERSION = hashlib.sha256(data=STYLESHEET_PATH.read_bytes()).hexdigest()[:16]
PROJECT_TYPEAHEAD_VERSION = hashlib.sha256(data=PROJECT_TYPEAHEAD_SCRIPT_PATH.read_bytes()).hexdigest()[:16]
TEMPLATE_GLOBALS = cast(dict[str, object], TEMPLATES.env.globals)
TEMPLATE_GLOBALS["static_version"] = STATIC_VERSION
TEMPLATE_GLOBALS["project_typeahead_version"] = PROJECT_TYPEAHEAD_VERSION
ERROR_MESSAGES = {
    "configuration": "The site is not configured yet. Please contact the administrator.",
    "discord_denied": "Discord login was cancelled or denied.",
    "invalid_state": "The Discord login expired. Please try again.",
    "oauth_failed": "Discord login could not be completed. Please try again.",
}


@dataclass(frozen=True, slots=True)
class ProjectOption:
    """A project choice displayed as one telescope/project label."""

    telescope: str
    project: str

    @property
    def label(self) -> str:
        """Return the value shown in the project type-ahead."""
        return f"{self.telescope} / {self.project}"


def project_option_list(
    catalog: dict[str, tuple[str, ...]],
    query: str = "",
) -> tuple[ProjectOption, ...]:
    """Flatten and filter the cached catalog for the combined type-ahead."""
    catalog = sanitize_catalog(catalog=catalog)
    normalized_query = query.casefold().strip()
    return tuple(
        ProjectOption(telescope=telescope, project=project)
        for telescope, projects in catalog.items()
        for project in projects
        if not normalized_query or normalized_query in f"{telescope} / {project}".casefold()
    )


def resolve_project_selection(
    selection: str,
    catalog: dict[str, tuple[str, ...]],
) -> tuple[str, str] | None:
    """Resolve a displayed type-ahead value back to exact S3 folder names."""
    max_selection_length = 2 * MAX_CATALOG_COMPONENT_LENGTH + 3
    if not isinstance(selection, str) or not selection.isprintable() or len(selection) > max_selection_length:
        return None
    for option in project_option_list(catalog=catalog):
        if option.label == selection:
            return option.telescope, option.project
    return None


def create_app(
    settings: Settings | None = None,
    catalog: ProjectCatalog | None = None,
    uploader: ImageUploader | None = None,
    discord: DiscordOAuth | None = None,
) -> FastAPI:
    """Create the FastAPI application."""
    resolved_settings = settings or get_settings()
    application = FastAPI(title="SLT Upload")
    application.add_middleware(
        middleware_class=SessionMiddleware,
        secret_key=resolved_settings.session_secret or secrets.token_urlsafe(nbytes=32),
        max_age=resolved_settings.session_max_age_seconds,
        same_site="lax",
        https_only=resolved_settings.cookie_secure,
    )
    application.mount(
        path="/static",
        app=StaticFiles(directory=str(BASE_DIR / "static")),
        name="static",
    )
    application.state.settings = resolved_settings
    application.state.catalog = catalog or ProjectCatalog(settings=resolved_settings)
    application.state.uploader = uploader or ImageUploader(settings=resolved_settings)
    application.state.discord = discord or DiscordOAuth(settings=resolved_settings)
    return _register_routes(application=application)


def _register_routes(application: FastAPI) -> FastAPI:
    @application.get(path="/", response_class=HTMLResponse, response_model=None)
    async def home(request: Request) -> HTMLResponse | RedirectResponse:
        if current_user(request=request):
            return RedirectResponse(url="/upload", status_code=303)
        return _render_login(request=request)

    @application.get(path="/login", response_class=HTMLResponse, response_model=None)
    async def login(
        request: Request,
        error: Annotated[str | None, Query()] = None,
    ) -> HTMLResponse | RedirectResponse:
        if current_user(request=request):
            return RedirectResponse(url="/upload", status_code=303)
        return _render_login(request=request, error=ERROR_MESSAGES.get(error or ""))

    @application.get(path="/auth/discord/login", response_model=None)
    async def discord_login(request: Request) -> RedirectResponse | HTMLResponse:
        settings: Settings = request.app.state.settings
        if settings.missing_discord_settings():
            return _render_login(request=request, error=ERROR_MESSAGES["configuration"], status_code=503)

        state = secrets.token_urlsafe(nbytes=32)
        request.session.clear()
        request.session["oauth_state"] = state
        discord: DiscordOAuth = request.app.state.discord
        return RedirectResponse(url=discord.authorization_url(state=state), status_code=303)

    @application.get(path="/auth/discord/callback")
    async def discord_callback(
        request: Request,
        code: Annotated[str | None, Query()] = None,
        state: Annotated[str | None, Query()] = None,
        error: Annotated[str | None, Query()] = None,
    ) -> RedirectResponse:
        expected_state = request.session.pop("oauth_state", None)
        if error:
            request.session.clear()
            return RedirectResponse(url="/login?error=discord_denied", status_code=303)
        if (
            not code
            or not state
            or not isinstance(expected_state, str)
            or not secrets.compare_digest(expected_state, state)
        ):
            request.session.clear()
            return RedirectResponse(url="/login?error=invalid_state", status_code=303)

        discord: DiscordOAuth = request.app.state.discord
        try:
            user = await discord.authenticate(code=code)
        except DiscordAuthError:
            request.session.clear()
            return RedirectResponse(url="/login?error=oauth_failed", status_code=303)

        request.session.clear()
        request.session["user"] = {
            "discord_id": user.discord_id,
            "discord_username": user.username,
            "upload_username": sanitize_username(username=user.username),
        }
        request.session["csrf_token"] = secrets.token_urlsafe(nbytes=32)
        return RedirectResponse(url="/upload", status_code=303)

    @application.post(path="/auth/logout")
    async def logout(request: Request, csrf_token: Annotated[str, Form()]) -> RedirectResponse:
        if not valid_csrf_token(request=request, supplied_token=csrf_token):
            raise HTTPException(status_code=403, detail="Invalid form token.")
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    @application.get(path="/upload", response_class=HTMLResponse, response_model=None)
    async def upload_page(request: Request) -> HTMLResponse | RedirectResponse:
        user = current_user(request=request)
        if user is None:
            return RedirectResponse(url="/login", status_code=303)
        return await render_upload_page(request=request, user=user)

    @application.get(path="/api/projects")
    async def projects_api(request: Request) -> dict[str, list[dict[str, object]]]:
        require_user(request=request)
        try:
            catalog = sanitize_catalog(catalog=await get_catalog(request=request))
        except ProjectCatalogError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "telescopes": [{"name": telescope, "projects": list(projects)} for telescope, projects in catalog.items()]
        }

    @application.post(path="/upload", response_class=HTMLResponse, response_model=None)
    async def upload(
        request: Request,
        project_selection: Annotated[str, Form()],
        image: Annotated[UploadFile, File()],
        csrf_token: Annotated[str, Form()],
    ) -> HTMLResponse | RedirectResponse:
        user = current_user(request=request)
        if user is None:
            return RedirectResponse(url="/login", status_code=303)
        if not valid_csrf_token(request=request, supplied_token=csrf_token):
            raise HTTPException(status_code=403, detail="Invalid form token.")

        message: dict[str, str] | None = None
        if not image.filename:
            message = {"kind": "error", "text": "Choose an image file to upload."}
        elif not image.filename.lower().endswith(".jpg"):
            message = {"kind": "error", "text": "The selected file must be a .jpg image."}
        elif image.content_type != "image/jpeg":
            message = {"kind": "error", "text": "The selected file must be a .jpg image."}
        elif image.size is not None and image.size > request.app.state.settings.max_upload_size_bytes:
            message = {"kind": "error", "text": "The selected image is too large."}
        else:
            try:
                catalog: ProjectCatalog = request.app.state.catalog
                catalog_data = sanitize_catalog(catalog=await catalog.get_catalog(force_refresh=True))
                selection = resolve_project_selection(selection=project_selection, catalog=catalog_data)
                if selection is None:
                    message = {"kind": "error", "text": "Choose a project from the available list."}
                else:
                    telescope, project = selection
                    key = upload_key(username=user["upload_username"], telescope=telescope, project=project)
                    uploader: ImageUploader = request.app.state.uploader
                    await uploader.upload(
                        fileobj=image.file,
                        key=key,
                    )
                    message = {"kind": "success", "text": f"Uploaded to {key}"}
                    project_selection = ""
            except ProjectCatalogError as exc:
                message = {"kind": "error", "text": str(exc)}
            except UploadError as exc:
                message = {"kind": "error", "text": str(exc)}

        return await render_upload_page(
            request=request,
            user=user,
            message=message,
            selected_project_selection=project_selection,
        )

    return application


def current_user(request: Request) -> dict[str, str] | None:
    """Return the authenticated session user, if present."""
    value = request.session.get("user")
    if not isinstance(value, dict):
        return None
    if not all(isinstance(value.get(key), str) for key in ("discord_id", "upload_username")):
        return None
    return value


def require_user(request: Request) -> dict[str, str]:
    """Raise a JSON-friendly authorization error when the session is absent."""
    user = current_user(request=request)
    if user is None:
        raise HTTPException(status_code=401, detail="Login required.")
    return user


def valid_csrf_token(request: Request, supplied_token: str) -> bool:
    """Validate a form token stored in the signed session cookie."""
    expected_token = request.session.get("csrf_token")
    return isinstance(expected_token, str) and secrets.compare_digest(expected_token, supplied_token)


def _render_login(
    request: Request,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error},
        status_code=status_code,
    )


async def get_catalog(request: Request) -> dict[str, tuple[str, ...]]:
    """Load the application catalog through its shared cache."""
    catalog: ProjectCatalog = request.app.state.catalog
    return await catalog.get_catalog()


async def render_upload_page(
    request: Request,
    user: dict[str, str],
    message: dict[str, str] | None = None,
    selected_project_selection: str = "",
) -> HTMLResponse:
    """Render the upload form and its cached combined project choices."""
    catalog_error: str | None = None
    try:
        catalog = await get_catalog(request=request)
    except ProjectCatalogError as exc:
        catalog = {}
        catalog_error = str(exc)

    csrf_token = request.session.get("csrf_token")
    if not isinstance(csrf_token, str):
        csrf_token = secrets.token_urlsafe(nbytes=32)
        request.session["csrf_token"] = csrf_token

    return TEMPLATES.TemplateResponse(
        request=request,
        name="upload.html",
        context={
            "user": user,
            "csrf_token": csrf_token,
            "message": message,
            "catalog_error": catalog_error,
            "max_upload_size_mb": request.app.state.settings.max_upload_size_bytes // (1024 * 1024),
            "project_options": project_option_list(catalog=catalog),
            "selected_project_selection": selected_project_selection,
        },
    )


app = create_app()
