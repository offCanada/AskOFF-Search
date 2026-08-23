import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opensearchpy.exceptions import ConnectionError, TransportError

from config.settings import settings

from .routes import router

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.logging_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _configure_logging()
        from query.dictionaries import load_dynamic_dictionaries
        load_dynamic_dictionaries()
        yield

    app = FastAPI(
        title="Search Platform API",
        version="0.2.0",
        description="Search and retrieval API for search products",
        debug=settings.api_debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Do not log arbitrary exception strings: upstream transport errors can
            # embed credentials or internal URLs.
            logger.error("request_failed request_id=%s path=%s", request_id, request.url.path)
            response = JSONResponse(
                status_code=500,
                content={"error": "internal_server_error", "request_id": request_id},
            )
            response.headers["X-Request-ID"] = request_id
            return response
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_complete request_id=%s method=%s path=%s status=%s latency_ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    @app.exception_handler(ConnectionError)
    async def opensearch_connection_error_handler(
        request: Request, exc: ConnectionError
    ) -> JSONResponse:
        logger.warning(
            "opensearch_connection_error request_id=%s",
            request.headers.get("X-Request-ID"),
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": "search_engine_unavailable",
                "detail": "Search is temporarily unavailable.",
            },
        )

    @app.exception_handler(TransportError)
    async def opensearch_transport_error_handler(
        request: Request, exc: TransportError
    ) -> JSONResponse:
        status_code = exc.status_code if isinstance(exc.status_code, int) else 500
        out_status = status_code if 400 <= status_code < 500 else 503
        logger.warning(
            "opensearch_transport_error request_id=%s status=%s",
            request.headers.get("X-Request-ID"),
            status_code,
        )

        return JSONResponse(
            status_code=out_status,
            content={
                "error": (
                    "search_engine_error"
                    if out_status == 400
                    else "search_engine_unavailable"
                ),
                "detail": "Search request could not be completed.",
            },
        )

    app.include_router(router)
    return app


app = create_app()

