import io
import zipfile

from fastapi.testclient import TestClient

from app.synthetic.corpus import required_scenarios


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_batch_zip_duplicate_malformed_and_retry(client: TestClient) -> None:
    from test_pipeline_and_api import _analyst_token

    token = _analyst_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    files = required_scenarios()
    payload = _zip(
        {
            "full_denial.835": files["full_denial.835"].encode("utf-8"),
            "malformed.835": files["malformed.835"].encode("utf-8"),
            "notes.exe": b"not a remittance",
            "nested/again.835": files["partial_denial.835"].encode("utf-8"),
        }
    )
    response = client.post(
        "/api/v1/remittances/batch",
        headers=headers,
        files={"files": ("drop.zip", payload, "application/zip")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    by_name = {item["filename"]: item for item in body["results"]}
    assert by_name["full_denial.835"]["lifecycle"] == "COMPLETED"
    assert by_name["malformed.835"]["lifecycle"] == "QUARANTINED"
    assert by_name["notes.exe"]["status"] == "rejected"
    assert by_name["again.835"]["status"] == "parsed"
    assert body["stats"]["duplicates"] == 0

    again = client.post(
        "/api/v1/remittances/batch",
        headers=headers,
        files={"files": ("full_denial.835", files["full_denial.835"].encode("utf-8"), "text/plain")},
    )
    assert again.status_code == 200, again.text
    assert again.json()["results"][0]["status"] == "duplicate"
    assert again.json()["results"][0]["lifecycle"] == "DUPLICATE"

    overview = client.get("/api/v1/analytics/overview", headers=headers)
    assert overview.status_code == 200
    assert overview.json()["total_paid"] is not None
    assert overview.json()["payers_analyzed"] >= 1

    quarantined_id = by_name["malformed.835"]["file_id"]
    report = client.get(f"/api/v1/remittances/{quarantined_id}/error-report", headers=headers)
    assert report.status_code == 200
    assert "parse" in report.text
    assert "ISA*this" not in report.text

    retry = client.post(f"/api/v1/remittances/{quarantined_id}/retry", headers=headers)
    assert retry.status_code == 200, retry.text
    assert retry.json()["lifecycle"] == "QUARANTINED"

    parsed_id = by_name["full_denial.835"]["file_id"]
    blocked = client.post(f"/api/v1/remittances/{parsed_id}/retry", headers=headers)
    assert blocked.status_code == 409

    detail = client.get(f"/api/v1/remittances/{parsed_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["lifecycle"] == "COMPLETED"
    assert detail.json()["claims"]
    assert any(stage["stage"] == "ANALYZING" for stage in detail.json()["stages"])


def test_zip_slip_is_rejected(client: TestClient) -> None:
    from test_pipeline_and_api import _analyst_token

    token = _analyst_token(client)
    payload = _zip({"../escape.835": b"ISA*no"})
    response = client.post(
        "/api/v1/remittances/batch",
        headers={"Authorization": f"Bearer {token}"},
        files={"files": ("bad.zip", payload, "application/zip")},
    )
    assert response.status_code == 400
    listed = client.get("/api/v1/remittances", headers={"Authorization": f"Bearer {token}"})
    assert listed.json()["total"] == 0
