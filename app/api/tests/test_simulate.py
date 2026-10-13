from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_cpu_work_executes_exact_iteration_count():
    response = client.get("/simulate/cpu-work?iterations=1000")

    assert response.status_code == 200
    body = response.json()
    assert body["iterations"] == 1000
    assert body["message"] == "fixed CPU work completed"
    assert body["checksum"] > 0


def test_cpu_work_rejects_iteration_count_below_minimum():
    response = client.get("/simulate/cpu-work?iterations=999")

    assert response.status_code == 422
