"""Client for the public Infrahub Marketplace API.

A thin async ``httpx`` client over the marketplace's public ``/api/v1`` endpoints,
mirroring the URL scheme and schema-vs-collection auto-detect of
``infrahub_sdk.ctl.marketplace`` (the reference implementation) and the
``list``/``search``/``show`` endpoint contract from infrahub-sdk-python PR #1128.

This client is deliberately Infrahub-credential-free: reaching an external service
must not leak internal secrets (FR-009). It inherits only the SDK's proxy/TLS
configuration. Errors are surfaced as :class:`MarketplaceError` with a category so
callers can distinguish a bad reference from an unreachable service (FR-010).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, NamedTuple

import httpx
from pydantic import BaseModel

if TYPE_CHECKING:
    from infrahub_sdk.config import ConfigBase

MarketplaceItemType = str  # "schemas" | "collections" (the API path segment)

_IDENTIFIER_PARTS = 2  # a valid ref is exactly "namespace/name"


class MarketplaceErrorCategory(StrEnum):
    """Categories that let callers tell a bad ref from an unreachable service (FR-010)."""

    INVALID_REF = "invalid-ref"
    NOT_FOUND = "not-found"
    NO_SUCH_VERSION = "no-such-version"
    UNREACHABLE = "unreachable"
    TOO_LARGE = "too-large"


class MarketplaceError(Exception):
    """A marketplace interaction failed, tagged with a :class:`MarketplaceErrorCategory`."""

    def __init__(self, category: MarketplaceErrorCategory, message: str, remediation: str | None = None) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.remediation = remediation


class MarketplaceIdentifier(NamedTuple):
    """A parsed ``namespace/name`` reference to a catalog item."""

    namespace: str
    name: str

    def __str__(self) -> str:
        return f"{self.namespace}/{self.name}"


class CatalogEntry(BaseModel, frozen=True):
    """One ranked result from a marketplace search."""

    namespace: str
    name: str
    item_type: str
    title: str | None = None
    description: str | None = None
    author: str | None = None
    latest_version: str | None = None
    tags: list[str] = []
    downloads: int | None = None
    schema_count: int | None = None


class SchemaPayload(BaseModel, frozen=True):
    """A schema's catalog metadata plus its downloaded YAML (FR-002)."""

    namespace: str
    name: str
    resolved_version: str
    yaml: str
    metadata: dict[str, Any] | None = None


class CollectionPayload(BaseModel, frozen=True):
    """A collection's metadata plus its assembled multi-document YAML stream (FR-003)."""

    namespace: str
    name: str
    members: list[str]
    yaml: str
    metadata: dict[str, Any] | None = None


def parse_identifier(ref: str) -> MarketplaceIdentifier:
    """Parse ``namespace/name``; raise ``invalid-ref`` on anything else."""
    parts = ref.split("/")
    if len(parts) != _IDENTIFIER_PARTS or not all(part.strip() for part in parts):
        raise MarketplaceError(
            MarketplaceErrorCategory.INVALID_REF,
            f"Invalid marketplace identifier {ref!r}. Expected 'namespace/name'.",
            remediation="Use the form 'namespace/name', e.g. 'opsmill/dcim'.",
        )
    return MarketplaceIdentifier(namespace=parts[0], name=parts[1])


def _list_url(base_url: str, item_type: MarketplaceItemType) -> str:
    return f"{base_url}/api/v1/{item_type}"


def _detail_url(base_url: str, item_type: MarketplaceItemType, namespace: str, name: str) -> str:
    return f"{base_url}/api/v1/{item_type}/{namespace}/{name}"


def _schema_download_url(base_url: str, namespace: str, name: str, version: str | None = None) -> str:
    if version:
        return f"{base_url}/api/v1/schemas/{namespace}/{name}/versions/{version}/download"
    return f"{base_url}/api/v1/schemas/{namespace}/{name}/download"


def make_marketplace_http_client(sdk_config: ConfigBase | None) -> httpx.AsyncClient:
    """Build an httpx client that inherits the SDK's proxy/TLS but carries no Infrahub auth.

    Mirrors ``infrahub_sdk.ctl.marketplace._make_http_client``. When ``sdk_config`` is
    None (e.g. passthrough mode with no shared client), falls back to a plain client.
    """
    kwargs: dict[str, Any] = {"follow_redirects": True}
    if sdk_config is not None:
        kwargs["verify"] = sdk_config.tls_context
        if sdk_config.proxy:
            kwargs["proxy"] = sdk_config.proxy
        elif sdk_config.proxy_mounts.is_set:
            kwargs["mounts"] = {
                key: httpx.AsyncHTTPTransport(proxy=val)
                for key, val in sdk_config.proxy_mounts.model_dump(by_alias=True).items()
                if val
            }
    return httpx.AsyncClient(**kwargs)


def _assemble_multidoc(docs: list[str]) -> str:
    """Join YAML documents into a single valid multi-document stream (``---`` separated)."""
    parts: list[str] = []
    for index, text in enumerate(docs):
        chunk = text if text.endswith("\n") else text + "\n"
        if index > 0 and not chunk.lstrip().startswith("---"):
            parts.append("---\n")
        parts.append(chunk)
    return "".join(parts)


def _tag_names(raw: Any) -> list[str]:
    """Normalise the ``tags`` field, which the API returns as ``[{id, name}]`` dicts."""
    names: list[str] = []
    for tag in raw or []:
        if isinstance(tag, dict) and tag.get("name"):
            names.append(str(tag["name"]))
        elif isinstance(tag, str):
            names.append(tag)
    return names


def _catalog_entry(item: dict[str, Any], item_type: MarketplaceItemType) -> CatalogEntry:
    """Map a raw listing item to a :class:`CatalogEntry`, tolerating field-name variants."""
    latest = item.get("latest_version")
    latest_semver = latest.get("semver") if isinstance(latest, dict) else None
    author = item.get("author")
    if isinstance(author, dict):
        author = author.get("username") or author.get("name")
    return CatalogEntry(
        namespace=str(item.get("namespace", "")),
        name=str(item.get("name", "")),
        item_type="collection" if item_type == "collections" else "schema",
        title=item.get("display_name") or item.get("display") or item.get("title"),
        description=item.get("description"),
        author=author,
        latest_version=item.get("semver") or latest_semver,
        tags=_tag_names(item.get("tags")),
        downloads=item.get("download_count") or item.get("downloads"),
        schema_count=item.get("schema_count"),
    )


class MarketplaceClient:
    """Async client over the marketplace's public ``/api/v1`` API.

    Constructed with a base URL and an ``httpx.AsyncClient`` (built by
    :func:`make_marketplace_http_client`). Pure of any MCP/Infrahub coupling so it can
    be unit-tested against a mock transport.
    """

    def __init__(self, base_url: str, http_client: httpx.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http_client

    async def _get(self, url: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        """GET a URL, mapping transport failures and 5xx to ``unreachable``."""
        try:
            resp = await self._http.get(url, params=params)
        except httpx.HTTPError as exc:
            raise MarketplaceError(
                MarketplaceErrorCategory.UNREACHABLE,
                f"Could not reach the marketplace at {self._base_url}.",
                remediation="Check network connectivity and the configured marketplace URL.",
            ) from exc
        if resp.status_code >= 500:  # noqa: PLR2004
            raise MarketplaceError(
                MarketplaceErrorCategory.UNREACHABLE,
                f"The marketplace at {self._base_url} returned a server error ({resp.status_code}).",
                remediation="The marketplace may be temporarily unavailable — retry later.",
            )
        return resp

    @staticmethod
    def _json(resp: httpx.Response, url: str) -> Any:
        try:
            return resp.json()
        except ValueError as exc:
            raise MarketplaceError(
                MarketplaceErrorCategory.UNREACHABLE,
                f"The marketplace response from {url} was not valid JSON.",
                remediation="The marketplace may be misbehaving — retry later.",
            ) from exc

    async def _fetch_listing(
        self, item_type: MarketplaceItemType, *, search: str | None, limit: int | None
    ) -> list[dict[str, Any]]:
        """Fetch listing items, following cursor pagination (SDK PR #1128 contract).

        With ``limit`` set, a single page is requested. Otherwise every page is fetched
        until ``has_next_page`` is false or no cursor is returned.
        """
        url = _list_url(self._base_url, item_type)
        params: dict[str, Any] = {}
        if search:
            params["search"] = search
        if limit is not None:
            params["limit"] = limit
        items: list[dict[str, Any]] = []
        while True:
            resp = await self._get(url, params=params)
            payload = self._json(resp, url)
            if isinstance(payload, dict):
                items.extend(entry for entry in payload.get("items", []) if isinstance(entry, dict))
                page_info = payload.get("page_info") or {}
            else:
                page_info = {}
            cursor = page_info.get("end_cursor")
            if limit is not None or not page_info.get("has_next_page") or not cursor:
                break
            params = {**params, "cursor": cursor}
        return items

    async def search(
        self,
        query: str,
        *,
        tag: str | None = None,
        namespace: str | None = None,
        limit: int | None = None,
        collections: bool = False,
    ) -> list[CatalogEntry]:
        """Search the catalog (FR-001). Empty list on no match (not an error).

        ``tag``/``namespace`` are filtered client-side on the returned fields — the
        marketplace API confirms only a ``search=`` param (research.md Decision 3).
        """
        item_type: MarketplaceItemType = "collections" if collections else "schemas"
        raw = await self._fetch_listing(item_type, search=query or None, limit=limit)
        entries = [_catalog_entry(item, item_type) for item in raw]
        if namespace:
            entries = [entry for entry in entries if entry.namespace == namespace]
        if tag:
            entries = [entry for entry in entries if tag in entry.tags]
        return entries

    async def _download_schema_yaml(
        self, ident: MarketplaceIdentifier, version: str | None, *, schema_exists: bool
    ) -> tuple[str, str]:
        """Download a schema's YAML; return ``(yaml_text, resolved_version)``."""
        resp = await self._get(_schema_download_url(self._base_url, ident.namespace, ident.name, version))
        if resp.status_code == httpx.codes.NOT_FOUND:
            if version and schema_exists:
                raise MarketplaceError(
                    MarketplaceErrorCategory.NO_SUCH_VERSION,
                    f"Schema {ident} has no published version {version!r}.",
                    remediation="Omit the version for the latest, or check available versions.",
                )
            raise MarketplaceError(
                MarketplaceErrorCategory.NOT_FOUND,
                f"No schema named {str(ident)!r} found on the marketplace.",
                remediation="Check the namespace/name, or search the catalog first.",
            )
        resp.raise_for_status()
        resolved = version or resp.headers.get("x-schema-version", "latest")
        return resp.text, resolved

    async def get_schema(self, ref: str, version: str | None = None) -> SchemaPayload:
        """Fetch a schema's catalog metadata (best effort) and its YAML payload (FR-002)."""
        ident = parse_identifier(ref)
        detail_resp = await self._get(_detail_url(self._base_url, "schemas", ident.namespace, ident.name))
        if detail_resp.status_code == httpx.codes.NOT_FOUND:
            raise MarketplaceError(
                MarketplaceErrorCategory.NOT_FOUND,
                f"No schema named {str(ident)!r} found on the marketplace.",
                remediation="Check the namespace/name, or search the catalog first.",
            )
        metadata: dict[str, Any] | None = None
        if detail_resp.is_success:
            parsed = self._json(detail_resp, _detail_url(self._base_url, "schemas", ident.namespace, ident.name))
            metadata = parsed if isinstance(parsed, dict) else None
        yaml_text, resolved = await self._download_schema_yaml(ident, version, schema_exists=True)
        return SchemaPayload(
            namespace=ident.namespace,
            name=ident.name,
            resolved_version=resolved,
            yaml=yaml_text,
            metadata=metadata,
        )

    async def get_collection(self, ref: str) -> CollectionPayload:
        """Fetch a collection's metadata and assemble its member schemas into multi-doc YAML (FR-003)."""
        ident = parse_identifier(ref)
        url = _detail_url(self._base_url, "collections", ident.namespace, ident.name)
        resp = await self._get(url)
        if resp.status_code == httpx.codes.NOT_FOUND:
            raise MarketplaceError(
                MarketplaceErrorCategory.NOT_FOUND,
                f"No collection named {str(ident)!r} found on the marketplace.",
                remediation="Check the namespace/name, or search collections first.",
            )
        if resp.status_code == httpx.codes.REQUEST_ENTITY_TOO_LARGE:
            raise MarketplaceError(
                MarketplaceErrorCategory.TOO_LARGE,
                f"Collection {ident} is too large to assemble in one response.",
                remediation="Fetch its member schemas individually with marketplace_get_schema.",
            )
        resp.raise_for_status()
        payload = self._json(resp, url)
        items = payload.get("items", []) if isinstance(payload, dict) else []

        members: list[MarketplaceIdentifier] = []
        versions: list[str | None] = []
        for item in items:
            schema = item.get("schema") if isinstance(item, dict) else None
            if not isinstance(schema, dict):
                continue
            member_ns, member_name = schema.get("namespace"), schema.get("name")
            if not member_ns or not member_name:
                continue
            members.append(MarketplaceIdentifier(namespace=member_ns, name=member_name))
            latest = schema.get("latest_version")
            versions.append(latest.get("semver") if isinstance(latest, dict) else None)

        docs: list[str] = []
        for member, member_version in zip(members, versions, strict=True):
            text, _ = await self._download_schema_yaml(member, member_version, schema_exists=True)
            docs.append(text)

        return CollectionPayload(
            namespace=ident.namespace,
            name=ident.name,
            members=[str(member) for member in members],
            yaml=_assemble_multidoc(docs),
            metadata=payload if isinstance(payload, dict) else None,
        )
