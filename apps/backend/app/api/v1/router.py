from fastapi import APIRouter

from app.api.v1 import auth, chat, health, jobs, lessons, onboarding, profile, progress, reports

api_router = APIRouter()
for module in (health, auth, chat, onboarding, profile, progress, reports, lessons, jobs):
    api_router.include_router(module.router)
