import asyncio
import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/simulate", tags=["simulate"])


@router.get("/error")
def simulate_error():
    """Force an HTTP 500 — used to test alerting and error rate dashboards."""
    logger.error("simulated error triggered")
    return JSONResponse(
        status_code=500,
        content={"error": "simulated internal server error"},
    )


@router.get("/latency")
async def simulate_latency(
    seconds: float = Query(default=2.0, ge=0.1, le=30.0, description="Delay in seconds"),
):
    """Introduce artificial latency — used to test latency dashboards and alerts."""
    logger.info("simulated latency triggered seconds=%.1f", seconds)
    await asyncio.sleep(seconds)
    return {"message": f"responded after {seconds}s delay"}
