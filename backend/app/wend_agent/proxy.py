"""Stream SSE bytes from a wend-agent container's cloudflared URL to the client."""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


async def proxy_dispatch(
    request: Request,
    tunnel_url: str,
    body: dict,
) -> StreamingResponse:
    upstream = f"{tunnel_url.rstrip('/')}/v1/dispatch"

    async def gen() -> AsyncIterator[bytes]:
        client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=None, write=10.0, pool=None))
        try:
            async with client.stream("POST", upstream, json=body) as r:
                if r.status_code >= 400:
                    text = (await r.aread()).decode("utf-8", "replace")
                    yield f"event: error\ndata: {json.dumps({'status': r.status_code, 'body': text})}\n\n".encode("utf-8")
                    yield b"event: done\ndata: {\"code\":-1}\n\n"
                    return
                async for chunk in r.aiter_raw():
                    if await request.is_disconnected():
                        logger.info("client disconnected; cancelling upstream")
                        break
                    yield chunk
        except httpx.HTTPError as exc:
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n".encode("utf-8")
            yield b"event: done\ndata: {\"code\":-1}\n\n"
        finally:
            await client.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    })
