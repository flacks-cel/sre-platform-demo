from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_create_job_returns_201():
    response = client.post("/jobs", json={"name": "test-job", "payload": {}})
    assert response.status_code == 201


def test_create_job_returns_job_id():
    response = client.post("/jobs", json={"name": "test-job", "payload": {}})
    data = response.json()
    assert "id" in data
    assert len(data["id"]) > 0


def test_create_job_default_status_is_pending():
    response = client.post("/jobs", json={"name": "test-job", "payload": {}})
    assert response.json()["status"] == "pending"


def test_get_job_returns_created_job():
    create = client.post("/jobs", json={"name": "fetch-job", "payload": {"key": "val"}})
    job_id = create.json()["id"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["id"] == job_id
    assert response.json()["name"] == "fetch-job"


def test_get_job_not_found_returns_404():
    response = client.get("/jobs/nonexistent-id")
    assert response.status_code == 404


def test_create_job_empty_name_returns_422():
    response = client.post("/jobs", json={"name": "", "payload": {}})
    assert response.status_code == 422


def test_fail_job_marks_status_as_failed():
    create = client.post("/jobs", json={"name": "fail-job", "payload": {}})
    job_id = create.json()["id"]

    response = client.patch(f"/jobs/{job_id}/fail")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
