from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from body_repair_ai.config import Settings
from body_repair_ai.web import create_app


def image_bytes(mode: str, color: int | tuple[int, int, int]) -> bytes:
    image = Image.new(mode, (24, 24), color=color)
    if mode == "L":
        for x in range(8, 16):
            for y in range(8, 16):
                image.putpixel((x, y), 255)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_create_job_and_accept_result(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data"))
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        data={"operation": "remove_dent"},
        files={
            "image": ("original.png", image_bytes("RGB", (50, 60, 70)), "image/png"),
            "mask": ("mask.png", image_bytes("L", 0), "image/png"),
        },
    )

    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "completed"
    assert client.get(job["result_url"]).status_code == 200

    review = client.post(f"/api/jobs/{job['id']}/review", json={"accepted": True})
    assert review.status_code == 200
    assert review.json()["status"] == "accepted"
