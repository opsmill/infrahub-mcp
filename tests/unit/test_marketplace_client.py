"""Unit tests for MarketplaceClient against a mock httpx transport (no network, no Infrahub)."""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from infrahub_mcp.marketplace import (
    MarketplaceClient,
    MarketplaceError,
    MarketplaceErrorCategory,
    parse_identifier,
)

BASE_URL = "https://marketplace.test"

Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler) -> MarketplaceClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    return MarketplaceClient(base_url=BASE_URL, http_client=http)


def _listing(items: list[dict], *, cursor: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={"items": items, "page_info": {"has_next_page": cursor is not None, "end_cursor": cursor}},
    )


# --- parse_identifier -------------------------------------------------------


def test_parse_identifier_valid() -> None:
    ident = parse_identifier("opsmill/dcim")
    assert (ident.namespace, ident.name) == ("opsmill", "dcim")
    assert str(ident) == "opsmill/dcim"


@pytest.mark.parametrize("ref", ["dcim", "opsmill/dcim/extra", "opsmill/", "/dcim", "  /  "])
def test_parse_identifier_invalid(ref: str) -> None:
    with pytest.raises(MarketplaceError) as exc:
        parse_identifier(ref)
    assert exc.value.category is MarketplaceErrorCategory.INVALID_REF


# --- search -----------------------------------------------------------------


async def test_search_returns_entries() -> None:
    # Field shapes mirror the live API (confirmed against marketplace.infrahub.app):
    # nested author, tags as {id,name} dicts, download_count, latest_version.semver.
    real_item = {
        "namespace": "infrahub",
        "name": "dcim",
        "display_name": "DCIM",
        "description": "Data Center Infrastructure Management",
        "download_count": 686,
        "author": {"username": "alex-gittings"},
        "tags": [{"id": "abc", "name": "base"}],
        "latest_version": {"semver": "1.0.0"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/schemas"
        assert request.url.params.get("search") == "dcim"
        return _listing([real_item])

    entries = await _client(handler).search("dcim")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.namespace == "infrahub"
    assert entry.item_type == "schema"
    assert entry.latest_version == "1.0.0"
    assert entry.title == "DCIM"
    assert entry.author == "alex-gittings"
    assert entry.tags == ["base"]  # normalised from [{id, name}]
    assert entry.downloads == 686


async def test_search_follows_cursor_pagination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "CUR1":
            return _listing([{"namespace": "n", "name": "b"}], cursor=None)
        return _listing([{"namespace": "n", "name": "a"}], cursor="CUR1")

    entries = await _client(handler).search("x")
    assert [e.name for e in entries] == ["a", "b"]


async def test_search_limit_requests_single_page() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params.get("limit") == "1"
        return _listing([{"namespace": "n", "name": "a"}], cursor="CUR1")

    entries = await _client(handler).search("x", limit=1)
    assert len(entries) == 1
    assert calls == 1  # limit stops the cursor loop after one page


async def test_search_empty_is_not_an_error() -> None:
    entries = await _client(lambda _r: _listing([])).search("nomatch")
    assert entries == []


async def test_search_filters_namespace_and_tag_client_side() -> None:
    items = [
        {"namespace": "opsmill", "name": "dcim", "tags": ["network"]},
        {"namespace": "other", "name": "dcim", "tags": ["network"]},
        {"namespace": "opsmill", "name": "ipam", "tags": ["ipam"]},
    ]
    client = _client(lambda _r: _listing(items))
    assert [e.name for e in await client.search("x", namespace="opsmill")] == ["dcim", "ipam"]
    assert [e.namespace for e in await client.search("x", tag="network")] == ["opsmill", "other"]


async def test_search_collections_hits_collections_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/collections"
        return _listing([{"namespace": "opsmill", "name": "starter", "schema_count": 3}])

    entries = await _client(handler).search("starter", collections=True)
    assert entries[0].item_type == "collection"
    assert entries[0].schema_count == 3


async def test_search_server_error_is_unreachable() -> None:
    with pytest.raises(MarketplaceError) as exc:
        await _client(lambda _r: httpx.Response(503)).search("x")
    assert exc.value.category is MarketplaceErrorCategory.UNREACHABLE


async def test_search_transport_failure_is_unreachable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        msg = "boom"
        raise httpx.ConnectError(msg)

    with pytest.raises(MarketplaceError) as exc:
        await _client(handler).search("x")
    assert exc.value.category is MarketplaceErrorCategory.UNREACHABLE


async def test_search_invalid_json_is_unreachable() -> None:
    with pytest.raises(MarketplaceError) as exc:
        await _client(lambda _r: httpx.Response(200, text="not json")).search("x")
    assert exc.value.category is MarketplaceErrorCategory.UNREACHABLE


# --- get_schema -------------------------------------------------------------


def _schema_handler(
    *,
    download_status: int = 200,
    detail_status: int = 200,
    collection_status: int = 404,
    version_header: str = "1.0.0",
) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/download") or "/versions/" in request.url.path:
            if download_status != 200:
                return httpx.Response(download_status)
            return httpx.Response(200, text="version: '1.0'\nnodes: []\n", headers={"x-schema-version": version_header})
        # get_schema probes the collections path too, to detect an ambiguous ref (FR-011).
        # Default 404 = this ref is a schema only.
        if "/collections/" in request.url.path:
            if collection_status != 200:
                return httpx.Response(collection_status)
            return httpx.Response(200, json={"namespace": "opsmill", "name": "dcim"})
        # schema detail
        if detail_status != 200:
            return httpx.Response(detail_status)
        return httpx.Response(200, json={"namespace": "opsmill", "name": "dcim", "downloads": 5})

    return handler


async def test_get_schema_latest() -> None:
    payload = await _client(_schema_handler()).get_schema("opsmill/dcim")
    assert payload.namespace == "opsmill"
    assert payload.resolved_version == "1.0.0"
    assert "nodes" in payload.yaml
    assert payload.metadata == {"namespace": "opsmill", "name": "dcim", "downloads": 5}


async def test_get_schema_pinned_version() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/versions/2.0.0/download" in request.url.path:
            return httpx.Response(200, text="version: '2.0'\n")
        return httpx.Response(200, json={"namespace": "opsmill", "name": "dcim"})

    payload = await _client(handler).get_schema("opsmill/dcim", version="2.0.0")
    assert payload.resolved_version == "2.0.0"


async def test_get_schema_no_such_version() -> None:
    # detail exists (schema exists) but the pinned version download 404s
    with pytest.raises(MarketplaceError) as exc:
        await _client(_schema_handler(download_status=404)).get_schema("opsmill/dcim", version="9.9.9")
    assert exc.value.category is MarketplaceErrorCategory.NO_SUCH_VERSION


async def test_get_schema_not_found() -> None:
    with pytest.raises(MarketplaceError) as exc:
        await _client(_schema_handler(detail_status=404)).get_schema("opsmill/nope")
    assert exc.value.category is MarketplaceErrorCategory.NOT_FOUND


async def test_get_schema_gzip_payload_is_decompressed() -> None:
    body = gzip.compress(b"version: '1.0'\nnodes: []\n")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/download"):
            return httpx.Response(200, content=body, headers={"content-encoding": "gzip"})
        return httpx.Response(200, json={})

    payload = await _client(handler).get_schema("opsmill/dcim")
    assert "nodes: []" in payload.yaml


async def test_get_schema_invalid_ref() -> None:
    with pytest.raises(MarketplaceError) as exc:
        await _client(lambda _r: httpx.Response(200)).get_schema("bad-ref")
    assert exc.value.category is MarketplaceErrorCategory.INVALID_REF


async def test_get_schema_unambiguous_ref_carries_no_note() -> None:
    payload = await _client(_schema_handler()).get_schema("opsmill/dcim")
    assert payload.ambiguity is None


async def test_get_schema_ambiguous_ref_resolves_as_schema_and_says_so() -> None:
    """FR-011: a ref naming both a schema and a collection resolves to the schema, noted."""
    payload = await _client(_schema_handler(collection_status=200)).get_schema("opsmill/dcim")
    assert "nodes" in payload.yaml  # the *schema* won
    assert payload.ambiguity is not None
    assert "also names a collection" in payload.ambiguity
    assert "marketplace_get_collection" in payload.ambiguity


async def test_get_schema_collection_only_ref_points_at_the_collection_tool() -> None:
    handler = _schema_handler(detail_status=404, collection_status=200)
    with pytest.raises(MarketplaceError) as exc:
        await _client(handler).get_schema("opsmill/starter")
    assert exc.value.category is MarketplaceErrorCategory.NOT_FOUND
    assert exc.value.remediation is not None
    assert "marketplace_get_collection" in exc.value.remediation


async def test_get_schema_collection_probe_failure_does_not_fail_the_call() -> None:
    """The ambiguity probe is best effort — a broken collections endpoint must not break get_schema."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "/collections/" in request.url.path:
            return httpx.Response(500)
        if request.url.path.endswith("/download"):
            return httpx.Response(200, text="version: '1.0'\nnodes: []\n")
        return httpx.Response(200, json={"namespace": "opsmill", "name": "dcim"})

    payload = await _client(handler).get_schema("opsmill/dcim")
    assert "nodes" in payload.yaml
    assert payload.ambiguity is None


# --- get_collection ---------------------------------------------------------


async def test_get_collection_assembles_multidoc() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/collections/opsmill/starter":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"schema": {"namespace": "opsmill", "name": "dcim", "latest_version": {"semver": "1.0.0"}}},
                        {"schema": {"namespace": "opsmill", "name": "ipam", "latest_version": {"semver": "2.0.0"}}},
                    ]
                },
            )
        # member schema downloads (pinned versions)
        return httpx.Response(200, text="version: '1.0'\nnodes: []\n")

    payload = await _client(handler).get_collection("opsmill/starter")
    assert payload.members == ["opsmill/dcim", "opsmill/ipam"]
    # Two docs joined into a valid multi-document stream
    assert payload.yaml.count("---") >= 1
    docs = [d for d in payload.yaml.split("---") if d.strip()]
    assert len(docs) == 2


async def test_get_collection_too_large() -> None:
    with pytest.raises(MarketplaceError) as exc:
        await _client(lambda _r: httpx.Response(413)).get_collection("opsmill/huge")
    assert exc.value.category is MarketplaceErrorCategory.TOO_LARGE


async def test_get_collection_not_found() -> None:
    with pytest.raises(MarketplaceError) as exc:
        await _client(lambda _r: httpx.Response(404)).get_collection("opsmill/nope")
    assert exc.value.category is MarketplaceErrorCategory.NOT_FOUND


# --- FR-009: no Infrahub credentials on marketplace requests ---------------


async def test_requests_carry_no_infrahub_credentials() -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return _listing([{"namespace": "opsmill", "name": "dcim"}])

    await _client(handler).search("dcim")
    assert seen, "handler was not called"
    for headers in seen:
        assert "authorization" not in headers
        assert "x-infrahub-key" not in {k.lower() for k in headers}


@pytest.mark.parametrize("status", [400, 401, 403, 429])
async def test_unhandled_4xx_becomes_a_marketplace_error(status: int) -> None:
    """FR-010: only 404/413 carry caller meaning; every other 4xx must still be categorised.

    Previously these reached ``raise_for_status()`` and escaped as a raw
    ``httpx.HTTPStatusError``, which the tool layer does not catch.
    """
    with pytest.raises(MarketplaceError) as exc:
        await _client(lambda _r: httpx.Response(status)).search("dcim")
    assert exc.value.category is MarketplaceErrorCategory.UNREACHABLE


@pytest.mark.parametrize("status", [400, 403, 429])
async def test_unhandled_4xx_on_schema_download_becomes_a_marketplace_error(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/download"):
            return httpx.Response(status)
        if "/collections/" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, json={"namespace": "opsmill", "name": "dcim"})

    with pytest.raises(MarketplaceError) as exc:
        await _client(handler).get_schema("opsmill/dcim")
    assert exc.value.category is MarketplaceErrorCategory.UNREACHABLE


async def test_zero_downloads_is_reported_not_dropped() -> None:
    """A real download_count of 0 is falsy — it must not fall through to None and vanish."""
    entries = await _client(
        lambda _r: _listing([{"namespace": "opsmill", "name": "fresh", "download_count": 0}])
    ).search("fresh")
    assert entries[0].downloads == 0
    assert "downloads" in entries[0].model_dump(exclude_none=True)


def test_proxy_mounts_inherit_the_sdk_tls_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mounted transport does not inherit the client's ``verify``; it must be passed through.

    Otherwise a custom CA configured on the SDK is silently dropped for proxied requests.
    """
    from infrahub_sdk import Config  # noqa: PLC0415 - keep the SDK import local to this test

    from infrahub_mcp.marketplace import make_marketplace_http_client  # noqa: PLC0415

    captured: list[dict[str, Any]] = []
    real_transport = httpx.AsyncHTTPTransport

    class SpyTransport(real_transport):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: Any) -> None:
            captured.append(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", SpyTransport)

    config = Config(proxy_mounts={"http": "http://proxy.test:8080"}, api_token="x")  # type: ignore[arg-type]  # noqa: S106
    make_marketplace_http_client(config)

    assert captured, "expected a mounted transport to be constructed"
    for kwargs in captured:
        assert kwargs["verify"] is config.tls_context


def test_error_json_payload_shape() -> None:
    """Sanity: error carries a category and message (used by the tool layer)."""
    err = MarketplaceError(MarketplaceErrorCategory.NOT_FOUND, "nope", remediation="try again")
    assert err.category is MarketplaceErrorCategory.NOT_FOUND
    assert str(err) == "nope"
    assert json.loads(json.dumps({"category": err.category})) == {"category": "not-found"}
