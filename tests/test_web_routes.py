from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app import web
from app.web import app


def test_get_bundle_builds_default_month(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_generate_bill(user_id: int, bill_type: str, month: str):
        calls.append((user_id, bill_type, month))
        return {"generated": []}

    def fake_export_bundle(month: str) -> Path:
        bundle = tmp_path / month / f"bundle-{month}.zip"
        bundle.parent.mkdir()
        bundle.write_bytes(b"zip")
        return bundle

    monkeypatch.setattr(web, "user_id", lambda: 7)
    monkeypatch.setattr("app.db.profile_is_complete", lambda *args: True)
    monkeypatch.setattr(web, "generate_bill", fake_generate_bill)
    monkeypatch.setattr(web, "export_bundle", fake_export_bundle)

    client = TestClient(app)
    response = client.get("/bundle", follow_redirects=False)
    expected_month = date.today().strftime("%Y-%m")

    assert response.status_code == 303
    assert f"/bundle-{expected_month}.zip?v=" in response.headers["location"]
    assert calls == [(7, "all", expected_month)]
