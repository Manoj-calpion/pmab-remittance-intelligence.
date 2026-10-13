"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app import __version__
from app.api.errors import AppError
from app.api.router import router
from app.core.config import get_settings, validate_runtime
from app.core.database import get_session_factory, init_schema


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    validate_runtime(settings)
    init_schema()
    db = get_session_factory()()
    try:
        from app.seed.reference import ensure_denial_mappings, ensure_demo_users, ensure_knowledge, ensure_roles

        ensure_roles(db)
        ensure_denial_mappings(db)
        ensure_knowledge(db)
        if settings.demo_mode:
            ensure_demo_users(db, settings)
            from app.models import RemittanceFile
            from sqlalchemy import select

            if db.scalar(select(RemittanceFile.id).limit(1)) is None:
                from app.seed.demo import seed_demo_corpus

                seed_demo_corpus(db, settings)
        db.commit()
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    validate_runtime(settings)
    app = FastAPI(
        title=settings.project_name,
        version=__version__,
        summary="Read-only ERA/835 remittance intelligence. Central Reach is never modified.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(_request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})

    @app.get("/", include_in_schema=False)
    def root():
        dashboard = settings.cors_origin_list[0] if settings.cors_origin_list else "http://127.0.0.1:5173"
        return HTMLResponse(
            f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{settings.project_name}</title>
  <style>
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #07111c; color: #e7eef8; font-family: "Segoe UI", sans-serif; }}
    main {{ width: min(32rem, calc(100% - 2rem)); }}
    a {{ color: #2dd4bf; }}
    .card {{ margin-top: 1rem; padding: 1rem 1.1rem; border: 1px solid #1e3348; border-radius: 12px; background: #0c1a2c; }}
  </style>
</head>
<body>
  <main>
    <p style="letter-spacing:.16em;text-transform:uppercase;color:#2dd4bf;font-size:.75rem">PMAB</p>
    <h1>Remittance intelligence</h1>
    <p>This address is the API. The dashboard is a separate page.</p>
    <div class="card">
      <p><a href="{dashboard}">Open the dashboard</a></p>
      <p><a href="/docs">Open the API documentation</a></p>
    </div>
  </main>
</body>
</html>"""
        )

    @app.get("/health", tags=["health"])
    def root_health():
        return {"status": "ok"}

    app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
