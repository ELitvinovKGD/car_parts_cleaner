from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from body_repair_ai.domain import JobRecord
from body_repair_ai.image_processing import MaskBundle


class DatasetStore:
    """Filesystem-backed store with immutable originals and explicit artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def initialize(self) -> None:
        for name in (
            "raw",
            "annotations",
            "candidates",
            "accepted",
            "rejected",
            "exports",
            "jobs",
        ):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def save_inputs(
        self,
        job: JobRecord,
        original: Image.Image,
        masks: MaskBundle,
    ) -> JobRecord:
        self.initialize()
        job_key = str(job.id)
        raw_dir = self.root / "raw" / job_key
        annotation_dir = self.root / "annotations" / job_key
        raw_dir.mkdir(parents=True, exist_ok=False)
        annotation_dir.mkdir(parents=True, exist_ok=False)

        original_path = raw_dir / "original.png"
        hard_path = annotation_dir / "mask_hard.png"
        soft_path = annotation_dir / "mask_soft.png"

        original.convert("RGB").save(original_path, format="PNG")
        masks.hard.save(hard_path, format="PNG")
        masks.soft.save(soft_path, format="PNG")

        job.original_path = original_path
        job.hard_mask_path = hard_path
        job.soft_mask_path = soft_path
        self.save_job(job)
        return job

    def candidate_path(self, job: JobRecord, attempt: int = 1) -> Path:
        path = self.root / "candidates" / str(job.id) / f"attempt-{attempt:03d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def save_job(self, job: JobRecord) -> Path:
        path = self.root / "jobs" / f"{job.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_job(self, job_id: str) -> JobRecord:
        path = self.root / "jobs" / f"{job_id}.json"
        return JobRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
