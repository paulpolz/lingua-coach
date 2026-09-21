from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.config import settings
from app.core.errors import APIError, api_error_handler, unhandled_exception_handler
from app.core.logging import get_logger, setup_logging
from app.core.middleware import RequestContextMiddleware

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        from app.services.quality import hydrate_quality_event_gauges

        await hydrate_quality_event_gauges()
    except Exception:
        logger.exception("quality_gauge_hydrate_failed")
    yield


app = FastAPI(title="Lingua Coach API", version="0.1.0", lifespan=lifespan)

app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# Starlette applies middleware in reverse add order: last added runs first.
# RequestContextMiddleware must wrap CORS so every response gets X-Request-ID.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestContextMiddleware)

app.include_router(api_router, prefix="/api/v1")

if settings.metrics_enabled:
    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/metrics", "/api/v1/health"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
