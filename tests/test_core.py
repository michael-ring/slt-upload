import asyncio
import time
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from sltupload.app import TEMPLATES
from sltupload.app import create_app
from sltupload.app import project_option_list
from sltupload.app import resolve_project_selection
from sltupload.auth import DiscordOAuth
from sltupload.config import Settings
from sltupload.filesystem import ImageUploader
from sltupload.filesystem import UploadError
from sltupload.filesystem import is_valid_jpeg
from sltupload.filesystem import sanitize_username
from sltupload.filesystem import upload_key
from sltupload.s3 import ProjectCatalog
from sltupload.s3 import sanitize_catalog
from sltupload.s3 import sanitize_catalog_name


def test_sanitize_username_removes_path_separators_and_unsafe_characters() -> None:
    assert sanitize_username(username="  Astro/Member name!  ") == "Astro-Member-name"


def test_sanitize_username_has_fallback_for_empty_safe_value() -> None:
    assert sanitize_username(username="///") == "discord-user"


def test_upload_key_preserves_telescope_and_project_spaces() -> None:
    assert upload_key(username="astro-member", telescope="My Telescope", project="Project 1") == (
        "astro-member/My Telescope/Project 1.jpg"
    )


def test_sanitize_catalog_name_rejects_frontend_and_path_control_values() -> None:
    assert sanitize_catalog_name(value="M 17") == "M 17"
    assert sanitize_catalog_name(value="<script>alert(1)</script>") is None
    assert sanitize_catalog_name(value="Project\nName") is None
    assert sanitize_catalog_name(value="../") is None


def test_sanitize_catalog_drops_unsafe_telescope_and_project_names() -> None:
    assert sanitize_catalog(
        catalog={
            "slt": ("M 17", "<script>", "Project\nName"),
            "<img>": ("M 31",),
        }
    ) == {"slt": ("M 17",)}


def test_project_options_filter_unsafe_catalog_values() -> None:
    options = project_option_list(catalog={"slt": ("M 17", "<script>"), "<img>": ("M 31",)})

    assert [option.label for option in options] == ["slt / M 17"]


def test_project_suggestions_are_html_escaped() -> None:
    options = project_option_list(catalog={"slt & scope": ("M 17 & 18",)})
    rendered = TEMPLATES.get_template(name="partials/project_options.html").render(project_options=options)

    assert 'data-value="slt &amp; scope / M 17 &amp; 18"' in rendered
    assert ">slt &amp; scope / M 17 &amp; 18</button>" in rendered


def test_upload_project_typeahead_uses_rendered_html_suggestions_without_requests() -> None:
    rendered = TEMPLATES.get_template(name="upload.html").render(
        user={"upload_username": "astro-member"},
        csrf_token="token",
        catalog_error=None,
        max_upload_size_mb=25,
        message=None,
        project_options=project_option_list(catalog={"slt": ("M 17",)}),
        selected_project_selection="",
        url_for=lambda endpoint, **kwargs: f"/{kwargs.get('path', endpoint)}",
    )

    assert 'id="project-input"' in rendered
    assert 'id="project-suggestions"' in rendered
    assert 'data-value="slt / M 17"' in rendered
    assert "<datalist" not in rendered
    assert "project_typeahead.js" in rendered


def test_anonymous_upload_is_rejected_before_multipart_parsing() -> None:
    application = create_app(settings=Settings(session_secret="test-session-secret"))

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            return await client.post(
                url="/upload",
                content=b"not a multipart body",
                headers={"Content-Type": "multipart/form-data; boundary=missing"},
            )

    response = asyncio.run(main=send_request())

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_upload_key_rejects_unsafe_source_folder_names() -> None:
    with pytest.raises(expected_exception=ValueError):
        upload_key(username="astro-member", telescope="slt/../", project="M 17")


def test_is_valid_jpeg_accepts_decodable_jpeg_and_rejects_other_bytes() -> None:
    image_file = BytesIO()
    with Image.new(mode="RGB", size=(1, 1), color="red") as image:
        image.save(fp=image_file, format="JPEG")

    assert is_valid_jpeg(fileobj=image_file)
    assert not is_valid_jpeg(fileobj=BytesIO(initial_bytes=b"not a jpeg"))


def test_settings_split_comma_separated_guild_ids() -> None:
    settings = Settings(discord_guild_ids="111, 222,333")

    assert settings.allowed_guild_ids == ("111", "222", "333")


def test_discord_authorization_url_requests_membership_scope() -> None:
    settings = Settings(
        discord_client_secret="secret",
        discord_guild_ids="111",
    )
    url = DiscordOAuth(settings=settings).authorization_url(state="test-state")

    assert "scope=identify+guilds.members.read" in url
    assert "state=test-state" in url


def test_project_options_flatten_catalog_into_display_labels() -> None:
    catalog = {"slt": ("M 17", "M 78"), "vst": ("M 31",)}

    options = project_option_list(catalog=catalog)

    assert [option.label for option in options] == ["slt / M 17", "slt / M 78", "vst / M 31"]
    assert resolve_project_selection(selection="slt / M 78", catalog=catalog) == ("slt", "M 78")
    assert resolve_project_selection(selection="unknown / project", catalog=catalog) is None
    assert resolve_project_selection(selection="slt / M 17<script>", catalog=catalog) is None
    assert resolve_project_selection(selection="slt / M 17\n", catalog=catalog) is None


def test_project_catalog_reads_nested_prefixes_and_caches_them() -> None:
    class FakePaginator:
        def paginate(self, **kwargs: str) -> list[dict[str, object]]:
            prefixes = {
                "": [{"Prefix": "Telescope/"}, {"Prefix": "Other/"}],
                "Telescope/": [
                    {"Prefix": "Telescope/Project Two/"},
                    {"Prefix": "Telescope/Project One/"},
                    {"Prefix": "Telescope/<script>/"},
                    {"Prefix": "Telescope/Project\nName/"},
                ],
                "Other/": [{"Prefix": "Other/Single Project/"}],
            }
            return [{"CommonPrefixes": prefixes[kwargs["Prefix"]]}]

    class FakeClient:
        def get_paginator(self, operation_name: str) -> FakePaginator:
            return FakePaginator()

    settings = Settings(source_s3_bucket="source", project_cache_ttl_seconds=900)
    client_calls = 0

    def client_factory() -> FakeClient:
        nonlocal client_calls
        client_calls += 1
        return FakeClient()

    catalog = ProjectCatalog(settings=settings, client_factory=client_factory)

    async def read_twice() -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
        first = await catalog.get_catalog()
        second = await catalog.get_catalog()
        return first, second

    first, second = asyncio.run(main=read_twice())

    assert first == {
        "Other": ("Single Project",),
        "Telescope": ("Project One", "Project Two"),
    }
    assert second == first
    assert client_calls == 1


def test_image_uploader_writes_file_to_configured_path_and_updates_timestamp(tmp_path: Path) -> None:
    settings = Settings(upload_path=tmp_path)
    uploader = ImageUploader(settings=settings)
    key = "user/Telescope/Project.jpg"
    before = time.time()

    asyncio.run(
        main=uploader.upload(
            fileobj=BytesIO(initial_bytes=b"image bytes"),
            key=key,
        )
    )

    destination = tmp_path / key
    assert destination.read_bytes() == b"image bytes"
    assert before <= destination.stat().st_mtime <= time.time()


def test_image_uploader_keeps_existing_file_when_copy_fails(tmp_path: Path) -> None:
    settings = Settings(upload_path=tmp_path)
    uploader = ImageUploader(settings=settings)
    key = "user/Telescope/Project.jpg"
    destination = tmp_path / key
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"original image")

    class FailingFile(BytesIO):
        read_count: int = 0

        def read(self, size: int | None = -1, /) -> bytes:
            self.read_count += 1
            if self.read_count > 1:
                raise OSError("read failed")
            return super().read(size)

    with pytest.raises(expected_exception=UploadError):
        asyncio.run(
            main=uploader.upload(
                fileobj=FailingFile(initial_bytes=b"partial image"),
                key=key,
            )
        )

    assert destination.read_bytes() == b"original image"
    assert not tuple(destination.parent.glob(pattern=f".{destination.name}.*.tmp"))
