import logging

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from routers import health, jobs, simulate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="jobs-api",
    description="SRE Platform Demo — job processing API",
    version="1.0.0",
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(simulate.router)


@app.get("/", tags=["root"])
def root():
    return {"service": "jobs-api", "status": "running"}
