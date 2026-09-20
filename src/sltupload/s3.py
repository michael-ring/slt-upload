import asyncio
import unicodedata
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from typing import Protocol

import boto3
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError

from sltupload.config import Settings


class ProjectCatalogError(Exception):
    """Raised when project folders cannot be loaded from S3."""


class S3Paginator(Protocol):
    """The paginator surface used by the project catalog."""

    def paginate(self, **kwargs: str) -> Iterable[Mapping[str, object]]:
        """Yield S3 list response pages."""


class S3CatalogClient(Protocol):
    """The S3 client surface used to read project prefixes."""

    def get_paginator(self, operation_name: str) -> S3Paginator:
        """Return a paginator for an S3 operation."""


CatalogClientFactory = Callable[[], S3CatalogClient]
MAX_CATALOG_COMPONENT_LENGTH = 255


def sanitize_catalog_name(value: object) -> str | None:
    """Return a source folder name only when it is safe to display and reuse."""
    if not isinstance(value, str) or not value or len(value) > MAX_CATALOG_COMPONENT_LENGTH:
        return None

    normalized = unicodedata.normalize("NFKC", value)
    if (
        normalized != normalized.strip()
        or normalized in {".", ".."}
        or any(character in normalized for character in "/\\<>")
        or not all(character.isprintable() for character in normalized)
        or any(unicodedata.category(character).startswith("C") for character in normalized)
    ):
        return None
    return value


def sanitize_catalog(catalog: Mapping[str, object]) -> dict[str, tuple[str, ...]]:
    """Filter untrusted source folder names before exposing them to the app."""
    sanitized: dict[str, tuple[str, ...]] = {}
    for raw_telescope, raw_projects in catalog.items():
        telescope = sanitize_catalog_name(value=raw_telescope)
        if telescope is None or isinstance(raw_projects, str) or not isinstance(raw_projects, Iterable):
            continue

        projects: list[str] = []
        for raw_project in raw_projects:
            project = sanitize_catalog_name(value=raw_project)
            if project is not None and project not in projects:
                projects.append(project)
        if projects:
            existing = list(sanitized.get(telescope, ()))
            existing.extend(project for project in projects if project not in existing)
            sanitized[telescope] = tuple(existing)
    return sanitized


def _s3_client_kwargs(
    endpoint_url: str | None,
    region_name: str | None,
    access_key_id: str | None,
    secret_access_key: str | None,
) -> dict[str, str]:
    kwargs: dict[str, str] = {}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    if region_name:
        kwargs["region_name"] = region_name
    if access_key_id:
        kwargs["aws_access_key_id"] = access_key_id
    if secret_access_key:
        kwargs["aws_secret_access_key"] = secret_access_key
    return kwargs


class ProjectCatalog:
    """Load telescope/project folder names and cache them in process memory."""

    def __init__(self, settings: Settings, client_factory: CatalogClientFactory | None = None) -> None:
        self.settings = settings
        self._client_factory = client_factory or self._create_client
        self._catalog: dict[str, tuple[str, ...]] = {}
        self._loaded_at: float | None = None
        self._lock = asyncio.Lock()

    async def get_catalog(self, force_refresh: bool = False) -> dict[str, tuple[str, ...]]:
        """Return the cached catalog, refreshing it after the configured TTL."""
        now = asyncio.get_running_loop().time()
        if not force_refresh and self._is_fresh(now=now):
            return self._copy_catalog()

        async with self._lock:
            now = asyncio.get_running_loop().time()
            if not force_refresh and self._is_fresh(now=now):
                return self._copy_catalog()
            try:
                catalog = self._load_catalog()
            except (BotoCoreError, ClientError) as exc:
                raise ProjectCatalogError("Could not load project folders from the source bucket.") from exc
            self._catalog = catalog
            self._loaded_at = asyncio.get_running_loop().time()
            return self._copy_catalog()

    def _is_fresh(self, now: float) -> bool:
        return self._loaded_at is not None and now - self._loaded_at < self.settings.project_cache_ttl_seconds

    async def project_names(self, telescope: str) -> tuple[str, ...]:
        """Return project names for a telescope."""
        catalog = await self.get_catalog()
        return catalog.get(telescope, ())

    async def contains(self, telescope: str, project: str) -> bool:
        """Check that a telescope/project pair came from the source bucket."""
        return project in await self.project_names(telescope)

    def _create_client(self) -> S3CatalogClient:
        kwargs = _s3_client_kwargs(
            endpoint_url=self.settings.source_s3_endpoint_url,
            region_name=self.settings.source_s3_region,
            access_key_id=self.settings.source_s3_access_key_id,
            secret_access_key=self.settings.source_s3_secret_access_key,
        )
        return boto3.client(service_name="s3", **kwargs)

    def _load_catalog(self) -> dict[str, tuple[str, ...]]:
        missing = self.settings.missing_source_s3_settings()
        if missing:
            raise ProjectCatalogError("Source S3 is not configured.")

        client = self._client_factory()
        telescope_prefixes = self._list_common_prefixes(client=client, prefix="")
        catalog: dict[str, tuple[str, ...]] = {}
        for telescope_prefix in telescope_prefixes:
            telescope = sanitize_catalog_name(value=telescope_prefix.removesuffix("/"))
            if telescope is None:
                continue
            project_prefixes = self._list_common_prefixes(client=client, prefix=telescope_prefix)
            projects = tuple(
                sorted(
                    {
                        project
                        for project_prefix in project_prefixes
                        if project_prefix.startswith(telescope_prefix)
                        for project in (
                            sanitize_catalog_name(
                                value=project_prefix.removeprefix(telescope_prefix).removesuffix("/")
                            ),
                        )
                        if project is not None
                    },
                    key=str.casefold,
                )
            )
            if projects:
                catalog[telescope] = projects
        return dict(sorted(catalog.items(), key=lambda item: item[0].casefold()))

    def _list_common_prefixes(self, client: S3CatalogClient, prefix: str) -> tuple[str, ...]:
        paginator = client.get_paginator(operation_name="list_objects_v2")
        prefixes: set[str] = set()
        pages = paginator.paginate(
            Bucket=self.settings.source_s3_bucket,
            Prefix=prefix,
            Delimiter="/",
        )
        for page in pages:
            common_prefixes = page.get("CommonPrefixes", ())
            if not isinstance(common_prefixes, list):
                continue
            for common_prefix in common_prefixes:
                if not isinstance(common_prefix, Mapping):
                    continue
                value = common_prefix.get("Prefix")
                if isinstance(value, str) and value:
                    prefixes.add(value)
        return tuple(sorted(prefixes, key=str.casefold))

    def _copy_catalog(self) -> dict[str, tuple[str, ...]]:
        return sanitize_catalog(catalog=self._catalog)
