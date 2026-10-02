from pathlib import Path

from PIL import Image

from body_repair_ai.config import Settings
from body_repair_ai.domain import JobStatus, Operation
from body_repair_ai.inference import MockInferenceEngine
from body_repair_ai.service import RestorationService
from body_repair_ai.storage import DatasetStore


def test_service_runs_and_reviews_job(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    store = DatasetStore(settings.data_dir)
    service = RestorationService(settings, store, MockInferenceEngine())
    original = Image.new("RGB", (32, 32), color=(70, 80, 90))
    mask = Image.new("L", (32, 32), color=0)
    for x in range(10, 20):
        for y in range(10, 20):
            mask.putpixel((x, y), 255)

    job = service.process(original, mask, Operation.REMOVE_DENT)

    assert job.status is JobStatus.COMPLETED
    assert job.result_path and job.result_path.exists()
    reviewed = service.review(str(job.id), accepted=True)
    assert reviewed.status is JobStatus.ACCEPTED
    assert (settings.data_dir / "accepted" / str(job.id) / "result.png").exists()
