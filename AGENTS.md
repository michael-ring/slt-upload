# AGENTS.md

## Project overview

This repository contains `sltupload`, a FastAPI service for members of the SLT Observatory to upload finished image edits to a configured S3 bucket. The app authenticates with Discord OAuth, restricts access to specific allowed guilds, caches a project catalog from a source S3 bucket, and uploads approved images to a destination bucket using a member-specific key.

## Important architecture notes

- Runtime entry point: `src/sltupload/__init__.py` defines the `main()` function, which starts Uvicorn with `sltupload.app:app`.
- Web app: `src/sltupload/app.py` is the main FastAPI application. It handles login, Discord callback, session auth, upload page rendering, project lookups, and upload submission.
- Auth: `src/sltupload/auth.py` performs Discord OAuth exchange, reads the current user, and verifies membership in configured guilds.
- Config: `src/sltupload/config.py` loads environment settings from `.env` via `pydantic-settings`; all S3 and Discord config is centralized there.
- S3 logic: `src/sltupload/s3.py` handles sanitization, project catalog discovery from a source bucket, caching, and uploads to the destination bucket.
- Static assets: `src/sltupload/templates/` and `src/sltupload/static/` define the HTML UI and CSS.

## Operational model

1. User opens the app and is redirected to Discord login.
2. The app stores a random OAuth state in the signed session cookie.
3. After OAuth completion, it checks the Discord user and verifies guild membership against `DISCORD_GUILD_IDS`.
4. A valid session stores the Discord ID and a sanitized upload username.
5. The upload page loads project choices from the source S3 bucket and exposes them as a filtered type-ahead.
6. The selected telescope/project is resolved back to exact S3-safe names and the image is uploaded to `memberpics/{sanitized_username}/{telescope}/{project}.jpg` in the upload bucket.

## Security-sensitive behaviors

- All catalog names and usernames are sanitized before they are displayed or used as S3 paths (`sanitize_catalog_name`, `sanitize_catalog`, `sanitize_username`).
- The app enforces a CSRF token on logout and upload forms.
- Discord authentication is gated on configured guild membership, not just valid login.
- The source and destination S3 credentials are independently configured so the app can read project names from one bucket and write images to another.

## Configuration

- Use `uv sync` to install dependencies.
- Copy `.env.example` to `.env` and fill in the required values.
- Required config includes:
  - Discord OAuth client credentials and allowed guild IDs.
  - `SESSION_SECRET` and optional cookie security settings.
  - Source S3 bucket info for reading project names.
  - Upload S3 bucket info for writing member images.

## Commands

- Install deps: `uv sync`
- Run app: `uv run sltupload`
- Docker run: `docker compose up --build`
- Lint: `uv run ruff check .`
- Format check: `uv run ruff format --check .`
- Type check: `uv run ty check`
- Tests: `uv run pytest`

## Testing notes

The repository has focused coverage in `tests/test_core.py` for:

- username and catalog sanitization
- project selection resolution
- Discord auth URL generation
- project catalog loading and caching
- S3 upload behavior

## Contributing guidance for agents

- Keep comments short and only add them where the code intent is not obvious.
- Prefer small, targeted changes that match the existing FastAPI and S3 abstractions.
- Validate with the smallest relevant toolchain: `ruff`, `ty`, and/or `pytest` as applicable to the change.
- Respect the app's security conventions: sanitize user-controlled values before rendering or path use.
- After a successful upload, the project search field should be cleared in the rendered upload page so the UI returns to a clean state.
- The upload form places the image input before the project search field, and that ordering should be preserved unless a UI requirement changes it intentionally.
- Status messages are shown below the upload button in the upload form.
- The upload page currently renders `selected_project_selection` back into the input value; keep that behavior in mind when changing success or error states.
