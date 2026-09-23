"""API v1 router aggregation. Add one module per resource group (API.md)."""

from fastapi import APIRouter

from app.api.v1 import health

router = APIRouter()
router.include_router(health.router)
