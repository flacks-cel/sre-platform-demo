import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    logger.info("health check called")
    return {"status": "alive"}


@router.get("/ready")
def ready():
    logger.info("readiness check called")
    return {"status": "ready"}
