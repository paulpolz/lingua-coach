from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.health import router as health_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.lessons import router as lessons_router
from app.api.v1.onboarding import router as onboarding_router
from app.api.v1.profile import router as profile_router
from app.api.v1.progress import router as progress_router
from app.api.v1.reports import router as reports_router
from app.api.v1.telemetry import router as telemetry_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(chat_router)
api_router.include_router(onboarding_router)
api_router.include_router(profile_router)
api_router.include_router(progress_router)
api_router.include_router(reports_router)
api_router.include_router(lessons_router)
api_router.include_router(jobs_router)
api_router.include_router(telemetry_router)
