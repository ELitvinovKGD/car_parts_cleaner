from pathlib import Path

from PIL import Image

from body_repair_ai.domain import JobRecord, Operation
from body_repair_ai.image_processing import prepare_masks
from body_repair_ai.storage import DatasetStore


def test_store_saves_inputs_and_metadata(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "data")
    original = Image.new("RGB", (16, 16), color="gray")
    mask = Image.new("L", (16, 16), color=0)
    for x in range(4, 12):
        for y in range(5, 11):
            mask.putpixel((x, y), 255)
    masks = prepare_masks(mask, expected_size=original.size)
    job = JobRecord(operation=Operation.REMOVE_DENT)

    saved = store.save_inputs(job, original, masks)

    assert saved.original_path and saved.original_path.exists()
    assert saved.hard_mask_path and saved.hard_mask_path.exists()
    assert saved.soft_mask_path and saved.soft_mask_path.exists()
    loaded = store.load_job(str(job.id))
    assert loaded.id == job.id
    assert loaded.operation is Operation.REMOVE_DENT
