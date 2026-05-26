from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import dependencies
from api.config import settings
from api.routes import admin, health, results, scrape
from api.routes import settings as settings_router
from api.routes import discovery as discovery_router
from api.routes import stats as stats_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=settings.log_level)
    dependencies.ensure_configured()
    from utils.discovery.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(title="Automated Funding API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(results.router)
    app.include_router(scrape.router)
    app.include_router(settings_router.router)
    app.include_router(admin.router)
    app.include_router(discovery_router.router)
    app.include_router(stats_router.router)

    return app


app = create_app()
