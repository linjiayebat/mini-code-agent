from __future__ import annotations

import httpx
import pytest

from mini_code_agent.providers.base import ProviderError, ProviderErrorCode
from mini_code_agent.providers.http import ProviderHttpTransport


def make_client(handler: httpx.AsyncBaseTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


@pytest.mark.asyncio
async def test_post_json_returns_validated_object_and_bounded_request_id() -> None:
    request_id = "r" * 200

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://provider.test/v1/messages"
        return httpx.Response(
            200,
            json={"type": "message", "content": []},
            headers={"request-id": request_id},
            request=request,
        )

    client = make_client(httpx.MockTransport(handler))
    transport = ProviderHttpTransport(
        base_url="https://provider.test",
        timeout_seconds=3,
        client=client,
    )

    payload, returned_request_id = await transport.post_json(
        "v1/messages",
        headers={"x-api-key": "test-key"},
        payload={"model": "test"},
    )

    assert payload == {"type": "message", "content": []}
    assert returned_request_id == "r" * 128
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (400, ProviderErrorCode.INVALID_RESPONSE, False),
        (401, ProviderErrorCode.AUTHENTICATION, False),
        (403, ProviderErrorCode.AUTHENTICATION, False),
        (408, ProviderErrorCode.TIMEOUT, True),
        (429, ProviderErrorCode.RATE_LIMIT, True),
        (500, ProviderErrorCode.SERVER, True),
        (504, ProviderErrorCode.TIMEOUT, True),
        (529, ProviderErrorCode.SERVER, True),
    ],
)
async def test_post_json_normalizes_http_statuses(
    status_code: int,
    expected_code: ProviderErrorCode,
    retryable: bool,
) -> None:
    secret = "provider-secret-value"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": {"message": f"rejected {secret}"}},
            request=request,
        )

    client = make_client(httpx.MockTransport(handler))
    transport = ProviderHttpTransport(
        base_url="https://provider.test",
        timeout_seconds=3,
        client=client,
    )

    with pytest.raises(ProviderError) as captured:
        await transport.post_json(
            "v1/messages",
            headers={"x-api-key": secret},
            payload={},
        )

    assert captured.value.code is expected_code
    assert captured.value.retryable is retryable
    assert secret not in captured.value.public_message
    assert secret not in str(captured.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_post_json_rejects_oversized_body_before_json_decode() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 33, request=request)

    client = make_client(httpx.MockTransport(handler))
    transport = ProviderHttpTransport(
        base_url="https://provider.test",
        timeout_seconds=3,
        max_response_bytes=32,
        client=client,
    )

    with pytest.raises(ProviderError, match="response exceeded") as captured:
        await transport.post_json("v1/messages", headers={}, payload={})

    assert captured.value.code is ProviderErrorCode.INVALID_RESPONSE
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        b"not-json",
        b"[]",
        b'{"value": NaN}',
        b"\xff",
    ],
)
async def test_post_json_rejects_malformed_or_non_object_json(content: bytes) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request)

    client = make_client(httpx.MockTransport(handler))
    transport = ProviderHttpTransport(
        base_url="https://provider.test",
        timeout_seconds=3,
        client=client,
    )

    with pytest.raises(ProviderError) as captured:
        await transport.post_json("v1/messages", headers={}, payload={})

    assert captured.value.code is ProviderErrorCode.INVALID_RESPONSE
    assert captured.value.retryable is False
    await client.aclose()


@pytest.mark.asyncio
async def test_post_json_normalizes_timeout_without_raw_exception() -> None:
    secret = "secret-in-exception"

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timed out with {secret}", request=request)

    client = make_client(httpx.MockTransport(handler))
    transport = ProviderHttpTransport(
        base_url="https://provider.test",
        timeout_seconds=3,
        client=client,
    )

    with pytest.raises(ProviderError) as captured:
        await transport.post_json("v1/messages", headers={}, payload={})

    assert captured.value.code is ProviderErrorCode.TIMEOUT
    assert captured.value.retryable is True
    assert secret not in str(captured.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_transport_closes_only_an_internally_owned_client() -> None:
    external = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    borrowed = ProviderHttpTransport(
        base_url="https://provider.test",
        timeout_seconds=3,
        client=external,
    )
    owned = ProviderHttpTransport(
        base_url="https://provider.test",
        timeout_seconds=3,
    )

    await borrowed.aclose()
    await owned.aclose()

    assert external.is_closed is False
    assert owned.is_closed is True
    await external.aclose()


@pytest.mark.parametrize(
    ("base_url", "timeout_seconds", "max_response_bytes"),
    [
        ("provider.test", 3, 1024),
        ("ftp://provider.test", 3, 1024),
        ("https://user:password@provider.test", 3, 1024),
        ("https://provider.test?secret=value", 3, 1024),
        ("https://provider.test", 0, 1024),
        ("https://provider.test", 3, 0),
        ("https://provider.test", 3, 20 * 1024 * 1024),
    ],
)
def test_transport_rejects_unsafe_or_unbounded_configuration(
    base_url: str,
    timeout_seconds: float,
    max_response_bytes: int,
) -> None:
    with pytest.raises(ValueError):
        ProviderHttpTransport(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
        )
