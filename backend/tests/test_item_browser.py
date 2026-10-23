"""API-68 / TSK-03: paginated task selection uses indexed identity, never filename guesses."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.ingest.models import Item, PhaseInfo, VolumeRef
from tests.test_api_ingest import ctx_of


def test_item_browser_filters_then_pages_active_items(client: TestClient) -> None:
    pid = client.post("/api/v1/projects", json={"name": "arbitrary identifiers"}).json()[
        "project_id"
    ]
    ctx = ctx_of(client)
    items = [
        Item(
            item_id=f"{case}.{scan}.complete.-",
            case_id=case,
            scan_idx=scan,
            scope="complete",
            side="-",
            phase=PhaseInfo(canonical=phase),
            modality=modality,
            import_id="synthetic",
            status=status,
            image=VolumeRef(ref=f"DATA:images/{name}.nii.gz"),
            masks={"organ": VolumeRef(ref="DERIVED:mask.nii.gz")} if mask else {},
        )
        for case, scan, name, phase, modality, status, mask in [
            ("subject-B", "01", "unrelated-name", "arterial", "MR", "active", False),
            ("subject-A", "02", "scan-two", "venous", "CT", "active", True),
            ("subject-A", "01", "scan-one", "arterial", "CT", "active", False),
            ("hidden", "01", "excluded", "venous", "CT", "excluded_upstream", False),
        ]
    ]
    ctx.index.replace(pid, items, [], [])
    url = f"/api/v1/projects/{pid}/items"
    first = client.get(url, params={"limit": 1})
    assert first.status_code == 200, first.text
    page = first.json()
    assert page["total"] == 3 and page["next_cursor"] == "1"
    assert page["items"][0]["item_id"] == "subject-A.01.complete.-"
    second = client.get(url, params={"cursor": page["next_cursor"], "limit": 1}).json()
    assert second["items"][0]["item_id"] == "subject-A.02.complete.-"
    for filters, expected in [
        ({"q": "UNRELATED"}, ["subject-B.01.complete.-"]),
        ({"q": "subject-a", "phase": "arterial"}, ["subject-A.01.complete.-"]),
        ({"modality": "CT", "has_mask": True}, ["subject-A.02.complete.-"]),
        ({"scope": "voi"}, []),
        ({"has_mask": False}, ["subject-A.01.complete.-", "subject-B.01.complete.-"]),
    ]:
        result = client.get(url, params=filters)
        assert result.status_code == 200, result.text
        assert [row["item_id"] for row in result.json()["items"]] == expected
    assert client.get(url, params={"cursor": "invalid"}).status_code == 422
    assert client.get("/api/v1/projects/missing/items").status_code == 404
    token = client.post(f"/api/v1/projects/{pid}/view-token").json()["view_token"]
    view = client.get(f"/api/v1/view/{token}/items")
    assert view.status_code == 200
    assert view.json()["total"] == 3
    assert pid not in view.text
