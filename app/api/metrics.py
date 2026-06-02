from prometheus_client import Counter

jobs_created_total = Counter(
    "jobs_created_total",
    "Total number of jobs created",
)

jobs_failed_total = Counter(
    "jobs_failed_total",
    "Total number of jobs that failed",
)
