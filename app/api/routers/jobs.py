import logging

from fastapi import APIRouter, HTTPException
from metrics import jobs_created_total, jobs_failed_total
from models import Job, JobCreate, JobStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

_store: dict[str, Job] = {}


@router.post("", status_code=201)
def create_job(body: JobCreate) -> Job:
    job = Job(name=body.name, payload=body.payload)
    _store[job.id] = job
    jobs_created_total.inc()
    logger.info("job created id=%s name=%s", job.id, job.name)
    return job


@router.get("/{job_id}")
def get_job(job_id: str) -> Job:
    job = _store.get(job_id)
    if not job:
        logger.warning("job not found id=%s", job_id)
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.patch("/{job_id}/fail", tags=["jobs"])
def fail_job(job_id: str) -> Job:
    """Mark a job as failed — useful for testing failure metrics."""
    job = _store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    job.status = JobStatus.failed
    jobs_failed_total.inc()
    logger.warning("job marked as failed id=%s", job_id)
    return job
