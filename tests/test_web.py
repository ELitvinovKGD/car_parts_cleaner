from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from body_repair_ai.config import Settings
from body_repair_ai.web import create_app


def image_bytes(mode: str, color: int | tuple[int, int, int]) -> bytes:
    image = Image.new(mode, (24, 24), color=color)
    if mode == "RGB" and color == (0, 0, 0):
        for x in range(8, 16):
            for y in range(8, 16):
                image.putpixel((x, y), (255, 0, 0))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def mask_bytes(*, filled: bool = False) -> bytes:
    image = Image.new("L", (24, 24), color=0)
    if filled:
        for x in range(8, 16):
            for y in range(8, 16):
                image.putpixel((x, y), 255)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_index_separates_processing_and_reference_workspaces(tmp_path: Path) -> None:
    client = TestClient(
        create_app(Settings(data_dir=tmp_path / "data", inference_backend="mock"))
    )

    response = client.get("/")

    assert response.status_code == 200
    assert 'id="repair-workspace"' in response.text
    assert 'id="reference-workspace"' in response.text
    assert 'id="repair-editor-slot"' in response.text
    assert 'id="reference-editor-slot"' in response.text
    assert 'id="donor-panel" class="donor-panel" hidden' in response.text


def test_create_job_and_accept_result(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", inference_backend="mock"))
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        data={"operation": "mixed_repair"},
        files={
            "image": ("original.png", image_bytes("RGB", (50, 60, 70)), "image/png"),
            "annotation": (
                "semantic.png",
                image_bytes("RGB", (0, 0, 0)),
                "image/png",
            ),
        },
    )

    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "completed"
    assert client.get(job["result_url"]).status_code == 200

    review = client.post(f"/api/jobs/{job['id']}/review", json={"accepted": True})
    assert review.status_code == 200
    assert review.json()["status"] == "accepted"


def test_single_semantic_label_selects_specific_operation(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", inference_backend="mock"))
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        data={"operation": "mixed_repair"},
        files={
            "image": ("original.png", image_bytes("RGB", (50, 60, 70)), "image/png"),
            "annotation": (
                "semantic.png",
                image_bytes("RGB", (255, 0, 255)),
                "image/png",
            ),
        },
    )

    assert response.status_code == 201
    assert response.json()["operation"] == "remove_scratch"


def test_layered_job_saves_independent_masks_and_stages(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", inference_backend="mock"))
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        files={
            "image": ("original.png", image_bytes("RGB", (50, 60, 70)), "image/png"),
            "part_mask": ("part.png", mask_bytes(filled=True), "image/png"),
            "dent_mask": ("dent.png", mask_bytes(filled=True), "image/png"),
            "scratch_mask": ("scratch.png", mask_bytes(filled=True), "image/png"),
            "dirt_mask": ("dirt.png", mask_bytes(), "image/png"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["completed_stages"] == ["remove_dent", "remove_scratch"]
    assert set(payload["layer_urls"]) == {
        "part",
        "dent",
        "scratch",
        "dirt",
        "retouch",
    }
    assert client.get(payload["layer_urls"]["dent"]).status_code == 200


def test_donor_job_saves_pair_and_returns_result(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", inference_backend="mock"))
    client = TestClient(app)

    response = client.post(
        "/api/donor-jobs",
        data={"match_color": "false"},
        files={
            "image": ("target.png", image_bytes("RGB", (50, 60, 70)), "image/png"),
            "part_mask": ("part.png", mask_bytes(filled=True), "image/png"),
            "donor_image": ("donor.png", image_bytes("RGB", (120, 30, 20)), "image/png"),
            "donor_mask": ("donor-mask.png", mask_bytes(filled=True), "image/png"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["operation"] == "donor_transfer"
    assert payload["backend"] == "local-donor-align"
    assert client.get(payload["result_url"]).status_code == 200
    assert client.get(payload["donor_url"]).status_code == 200
    assert client.get(payload["donor_mask_url"]).status_code == 200


def test_reference_pair_can_be_annotated_and_imported(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    sample_dir = data_dir / "references" / "black-bumper"
    sample_dir.mkdir(parents=True)
    Image.new("RGB", (24, 24), (50, 60, 70)).save(sample_dir / "before.png")
    Image.new("RGB", (24, 24), (40, 50, 60)).save(
        sample_dir / "approved_after.png"
    )

    app = create_app(Settings(data_dir=data_dir, inference_backend="mock"))
    client = TestClient(app)

    listing = client.get("/api/references")
    assert listing.status_code == 200
    assert listing.json()["items"] == [
        {
            "id": "black-bumper",
            "before_size": [24, 24],
            "after_size": [24, 24],
            "same_size": True,
            "annotated": False,
            "reference_quality": None,
            "annotation_level": None,
        }
    ]

    response = client.post(
        "/api/references/black-bumper/annotations",
        data={"reference_quality": "visual_reference"},
        files={
            "part_mask": ("part.png", mask_bytes(filled=True), "image/png"),
            "dent_mask": ("dent.png", mask_bytes(), "image/png"),
            "scratch_mask": ("scratch.png", mask_bytes(), "image/png"),
            "dirt_mask": ("dirt.png", mask_bytes(filled=True), "image/png"),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["backend"] == "external-reference"
    assert payload["reference_quality"] == "visual_reference"
    assert payload["dataset_collection"] == "visual_references"
    job_id = payload["dataset_job_id"]

    assert (data_dir / "raw" / job_id / "original.png").is_file()
    assert (data_dir / "annotations" / job_id / "part.png").is_file()
    assert (data_dir / "visual_references" / job_id / "result.png").is_file()
    assert (sample_dir / "protect_mask.png").is_file()
    assert (sample_dir / "metadata.json").is_file()

    artifact = client.get(
        "/api/references/black-bumper/artifacts/approved_after"
    )
    assert artifact.status_code == 200
    listed = client.get("/api/references").json()["items"][0]
    assert listed["annotated"] is True
    assert listed["reference_quality"] == "visual_reference"
    assert listed["annotation_level"] == "detailed"

    reclassified = client.post(
        "/api/references/black-bumper/annotations",
        data={"reference_quality": "pixel_aligned"},
        files={
            "part_mask": ("part.png", mask_bytes(filled=True), "image/png"),
            "dent_mask": ("dent.png", mask_bytes(), "image/png"),
            "scratch_mask": ("scratch.png", mask_bytes(), "image/png"),
            "dirt_mask": ("dirt.png", mask_bytes(filled=True), "image/png"),
        },
    )
    assert reclassified.status_code == 200
    assert reclassified.json()["dataset_job_id"] == job_id
    assert (data_dir / "accepted" / job_id / "result.png").is_file()
    assert not (data_dir / "visual_references" / job_id / "result.png").exists()


def test_visual_reference_allows_a_different_target_size(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    sample_dir = data_dir / "references" / "shifted-bumper"
    sample_dir.mkdir(parents=True)
    Image.new("RGB", (24, 24), (50, 60, 70)).save(sample_dir / "before.png")
    Image.new("RGB", (24, 25), (40, 50, 60)).save(
        sample_dir / "approved_after.png"
    )
    client = TestClient(
        create_app(Settings(data_dir=data_dir, inference_backend="mock"))
    )
    files = {
        "part_mask": ("part.png", mask_bytes(filled=True), "image/png"),
        "dent_mask": ("dent.png", mask_bytes(), "image/png"),
        "scratch_mask": ("scratch.png", mask_bytes(), "image/png"),
        "dirt_mask": ("dirt.png", mask_bytes(filled=True), "image/png"),
    }

    visual = client.post(
        "/api/references/shifted-bumper/annotations",
        data={"reference_quality": "visual_reference"},
        files=files,
    )
    assert visual.status_code == 200
    assert visual.json()["dataset_collection"] == "visual_references"

    exact = client.post(
        "/api/references/shifted-bumper/annotations",
        data={"reference_quality": "pixel_aligned"},
        files=files,
    )
    assert exact.status_code == 422


def test_reference_auto_mask_can_be_saved_as_general_retouch(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    sample_dir = data_dir / "references" / "gold-bumper"
    sample_dir.mkdir(parents=True)
    before = Image.new("RGB", (24, 24), (20, 20, 20))
    after = before.copy()
    for x in range(8, 16):
        for y in range(8, 16):
            after.putpixel((x, y), (90, 90, 90))
    before.save(sample_dir / "before.png")
    after.save(sample_dir / "approved_after.png")
    client = TestClient(
        create_app(Settings(data_dir=data_dir, inference_backend="mock"))
    )

    auto_mask = client.post(
        "/api/references/gold-bumper/auto-mask",
        files={"part_mask": ("part.png", mask_bytes(filled=True), "image/png")},
    )

    assert auto_mask.status_code == 200
    generated_mask = Image.open(BytesIO(auto_mask.content))
    assert generated_mask.getbbox() is not None

    saved = client.post(
        "/api/references/gold-bumper/annotations",
        data={"reference_quality": "pixel_aligned"},
        files={
            "part_mask": ("part.png", mask_bytes(filled=True), "image/png"),
            "dent_mask": ("dent.png", mask_bytes(), "image/png"),
            "scratch_mask": ("scratch.png", mask_bytes(), "image/png"),
            "dirt_mask": ("dirt.png", mask_bytes(), "image/png"),
            "retouch_mask": ("retouch.png", auto_mask.content, "image/png"),
        },
    )

    assert saved.status_code == 200
    metadata = (sample_dir / "metadata.json").read_text(encoding="utf-8")
    assert '"annotation_level": "general"' in metadata
    assert (sample_dir / "retouch_mask.png").is_file()
    assert client.get("/api/references").json()["items"][0]["annotation_level"] == "general"


def test_reference_can_be_saved_with_part_mask_only(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    sample_dir = data_dir / "references" / "part-only"
    sample_dir.mkdir(parents=True)
    Image.new("RGB", (24, 24), (20, 20, 20)).save(sample_dir / "before.png")
    Image.new("RGB", (24, 24), (30, 30, 30)).save(
        sample_dir / "approved_after.png"
    )
    client = TestClient(
        create_app(Settings(data_dir=data_dir, inference_backend="mock"))
    )

    response = client.post(
        "/api/references/part-only/annotations",
        data={"reference_quality": "pixel_aligned"},
        files={
            "part_mask": ("part.png", mask_bytes(filled=True), "image/png"),
            "dent_mask": ("dent.png", mask_bytes(), "image/png"),
            "scratch_mask": ("scratch.png", mask_bytes(), "image/png"),
            "dirt_mask": ("dirt.png", mask_bytes(), "image/png"),
        },
    )

    assert response.status_code == 200
    job_id = response.json()["dataset_job_id"]
    assert (data_dir / "annotations" / job_id / "mask_hard.png").is_file()
    assert client.get("/api/references").json()["items"][0]["annotation_level"] == "part_only"
