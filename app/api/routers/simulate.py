import asyncio
import logging
import math
import time

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


@router.get("/cpu")
def simulate_cpu(
    seconds: float = Query(
        default=5.0,
        ge=0.1,
        le=30.0,
        description="CPU burn duration in seconds",
    ),
):
    """
    Burn CPU for a configurable amount of time.
    Useful for demonstrating Kubernetes HPA based on CPU utilization.
    """
    logger.info("simulated cpu load triggered seconds=%.1f", seconds)

    end_time = time.perf_counter() + seconds
    iterations = 0

    while time.perf_counter() < end_time:
        # CPU-intensive floating point work
        math.sqrt(iterations % 10000)
        iterations += 1

    logger.info("cpu simulation finished iterations=%d", iterations)

    return {
        "message": f"CPU load generated for {seconds:.1f}s",
        "iterations": iterations,
    }