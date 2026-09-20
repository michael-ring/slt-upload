# SLT Upload

A tool for members of the [SLT Observatory](https://slt-observatory.space/) to upload
their finished edits to be shown on our project website. Discord is used for communication
and to authenticate against the service to allow uploading images.

## Setup

Install dependencies with uv, create a local environment file, and edit it:

```sh
uv sync
cp .env.example .env
```

## Run

```sh
uv run sltupload
```

Alternatively run this service via Docker:

```sh
docker compose up --build
```

Set `UPLOAD_PATH` to the filesystem directory where uploaded images should be stored.
Uploads create or replace a file below that directory at the following relative path:

```text
{sanitized_username}/{telescope}/{project}.jpg
```

## Development

We use `ruff`, `ty`, and `pytest` to format, lint, typecheck, and test the code.

```sh
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```
