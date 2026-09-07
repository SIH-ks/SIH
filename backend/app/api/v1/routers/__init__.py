"""API v1 route modules."""
from __future__ import annotations

from fastapi import APIRouter

from .parcels import router as parcels_router
from .upload import router as upload_router

api_router = APIRouter()
api_router.include_router(upload_router)
api_router.include_router(parcels_router)

__all__ = ["api_router"]
