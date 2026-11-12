"""FastAPI application of the model block (protocol P2).

Routes: `GET /health`, `GET /v1/models`, `POST /v1/chat/completions` (JSON, or SSE with
`stream: true`), `POST /v1/embeddings`. There is no authentication: the service is reachable only on
the internal network. A failure after a stream has started is sent as an `error` event followed by
`[DONE]`, never as a second response.
"""

import json
from typing import Any, Dict, Iterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from laris.model.gpu_queue import QueueFull, QueueTimeout
from laris.model.service import ModelService
from laris.protocol import ProviderError, encode_done, encode_event
from laris.shared.core.errors import HardwareBudgetExceededError


def create_app(service: ModelService, max_body_bytes: int) -> FastAPI:
    app = FastAPI(title="laris-model", docs_url=None, redoc_url=None, openapi_url=None)

    async def read_json(request: Request) -> Dict[str, Any]:
        length = int(request.headers.get("content-length") or 0)
        if length > max_body_bytes:
            raise HTTPException(413, "request too large")
        raw = await request.body()
        if len(raw) > max_body_bytes:
            raise HTTPException(413, "request too large")
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise HTTPException(400, "invalid JSON") from None
        if not isinstance(body, dict):
            raise HTTPException(400, "the body must be a JSON object")
        return body

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return service.health()

    @app.get("/v1/models")
    def models() -> Dict[str, Any]:
        return service.models()

    def sse(chunks: Iterator[Dict[str, Any]]) -> Iterator[bytes]:
        try:
            for chunk in chunks:
                yield encode_event(chunk)
        except Exception as exc:  # after the first byte: an error event, then the end marker
            yield encode_event({"error": {"message": str(exc), "type": type(exc).__name__}})
        yield encode_done()

    @app.post("/v1/chat/completions", response_model=None)
    async def chat(request: Request) -> Any:
        body = await read_json(request)
        if not isinstance(body.get("messages"), list):
            raise HTTPException(400, "messages must be a list")
        try:
            if body.get("stream"):
                chunks = iter(service.stream(body))
                first = await run_in_threadpool(next, chunks, None)  # a failure here is HTTP

                def rest() -> Iterator[Dict[str, Any]]:
                    if first is not None:
                        yield first
                    yield from chunks

                return StreamingResponse(
                    sse(rest()),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-store"},
                )
            return await run_in_threadpool(service.complete, body)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        except (QueueFull, HardwareBudgetExceededError) as exc:
            raise HTTPException(503, str(exc)) from exc
        except QueueTimeout as exc:
            raise HTTPException(504, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/embeddings")
    async def embeddings(request: Request) -> Dict[str, Any]:
        body = await read_json(request)
        try:
            return await run_in_threadpool(service.embed, body)
        except (QueueFull, HardwareBudgetExceededError) as exc:
            raise HTTPException(503, str(exc)) from exc
        except QueueTimeout as exc:
            raise HTTPException(504, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    return app
