"""API v1 route modules."""
from __future__ import annotations

from fastapi import APIRouter

from .analytics import router as analytics_router
from .auth import router as auth_router
from .exports import router as exports_router
from .parcels import audit_router
from .parcels import router as parcels_router
from .succession import router as succession_router
from .system import router as system_router
from .upload import router as upload_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(upload_router)
api_router.include_router(parcels_router)
api_router.include_router(audit_router)
api_router.include_router(succession_router)
api_router.include_router(analytics_router)
api_router.include_router(exports_router)
api_router.include_router(system_router)

__all__ = ["api_router"]
