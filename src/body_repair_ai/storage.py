from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from shutil import copyfile

from PIL import Image, ImageChops

from body_repair_ai.domain import JobRecord
from body_repair_ai.image_processing import MaskBundle, SemanticMasks


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
            "visual_references",
            "rejected",
            "exports",
            "jobs",
            "work",
            "references",
        ):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def save_inputs(
        self,
        job: JobRecord,
        original: Image.Image,
        masks: MaskBundle,
        semantic_mask: Image.Image | None = None,
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
        semantic_path = annotation_dir / "semantic.png"

        original.convert("RGB").save(original_path, format="PNG")
        masks.hard.save(hard_path, format="PNG")
        masks.soft.save(soft_path, format="PNG")
        if semantic_mask is not None:
            semantic_mask.convert("RGB").save(semantic_path, format="PNG")

        job.original_path = original_path
        job.hard_mask_path = hard_path
        job.soft_mask_path = soft_path
        job.semantic_mask_path = semantic_path if semantic_mask is not None else None
        self.save_job(job)
        return job

    def save_layer_inputs(
        self,
        job: JobRecord,
        original: Image.Image,
        masks: MaskBundle,
        semantic_masks: SemanticMasks,
    ) -> JobRecord:
        """Save an immutable original plus each independent annotation layer."""

        self.save_inputs(job, original, masks)
        annotation_dir = self.root / "annotations" / str(job.id)
        layer_paths: dict[str, Path] = {}
        for name in ("part", "dent", "scratch", "dirt", "retouch"):
            path = annotation_dir / f"{name}.png"
            getattr(semantic_masks, name).convert("L").save(path, format="PNG")
            layer_paths[name] = path
        job.layer_mask_paths = layer_paths
        self.save_job(job)
        return job

    def save_donor_inputs(
        self,
        job: JobRecord,
        target: Image.Image,
        target_masks: MaskBundle,
        donor: Image.Image,
        donor_masks: MaskBundle,
    ) -> JobRecord:
        """Save both sides of an experimental donor-transfer pair."""

        self.save_inputs(job, target, target_masks)
        raw_dir = self.root / "raw" / str(job.id)
        annotation_dir = self.root / "annotations" / str(job.id)
        donor_path = raw_dir / "donor.png"
        donor_mask_path = annotation_dir / "donor_mask.png"
        donor.convert("RGB").save(donor_path, format="PNG")
        donor_masks.hard.save(donor_mask_path, format="PNG")
        job.donor_path = donor_path
        job.donor_mask_path = donor_mask_path
        self.save_job(job)
        return job

    def candidate_path(self, job: JobRecord, attempt: int = 1) -> Path:
        path = self.root / "candidates" / str(job.id) / f"attempt-{attempt:03d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def work_path(self, job: JobRecord, filename: str) -> Path:
        path = self.root / "work" / str(job.id) / filename
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

    def review_job(self, job: JobRecord, *, accepted: bool) -> Path:
        if job.result_path is None or not job.result_path.exists():
            raise ValueError("Job has no result to review.")
        collection = "accepted" if accepted else "rejected"
        destination = self.root / collection / str(job.id) / "result.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        copyfile(job.result_path, destination)
        if job.donor_path is not None and job.donor_path.exists():
            copyfile(job.donor_path, destination.parent / "donor.png")
        if job.donor_mask_path is not None and job.donor_mask_path.exists():
            copyfile(job.donor_mask_path, destination.parent / "donor_mask.png")
        return destination

    def _reference_dir(self, sample_id: str) -> Path:
        if not sample_id or Path(sample_id).name != sample_id or sample_id in {".", ".."}:
            raise ValueError("Invalid reference sample id.")
        root = (self.root / "references").resolve()
        path = (root / sample_id).resolve()
        if path.parent != root:
            raise ValueError("Invalid reference sample id.")
        return path

    def list_references(self) -> list[dict[str, object]]:
        self.initialize()
        items: list[dict[str, object]] = []
        for path in sorted((self.root / "references").iterdir(), key=lambda item: item.name):
            if not path.is_dir():
                continue
            before = path / "before.png"
            approved_after = path / "approved_after.png"
            if not before.is_file() or not approved_after.is_file():
                continue
            with Image.open(before) as before_image, Image.open(approved_after) as after_image:
                before_size = before_image.size
                after_size = after_image.size
            metadata: dict[str, object] = {}
            metadata_path = path / "metadata.json"
            if metadata_path.is_file():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    metadata = {}
            reference_quality = metadata.get("reference_quality")
            if reference_quality not in {"pixel_aligned", "visual_reference"}:
                reference_quality = None
            annotation_level = metadata.get("annotation_level")
            if annotation_level not in {"part_only", "general", "detailed"}:
                annotation_level = None
            mask_names = ("part_mask", "dent_mask", "scratch_mask", "dirt_mask")
            annotated = metadata.get("annotated") is True or all(
                (path / f"{name}.png").is_file() for name in mask_names
            )
            items.append(
                {
                    "id": path.name,
                    "before_size": before_size,
                    "after_size": after_size,
                    "same_size": before_size == after_size,
                    "annotated": annotated,
                    "reference_quality": reference_quality,
                    "annotation_level": annotation_level,
                }
            )
        return items

    def reference_artifact_path(self, sample_id: str, artifact: str) -> Path:
        filenames = {
            "before": "before.png",
            "approved_after": "approved_after.png",
            "part_mask": "part_mask.png",
            "dent_mask": "dent_mask.png",
            "scratch_mask": "scratch_mask.png",
            "dirt_mask": "dirt_mask.png",
            "retouch_mask": "retouch_mask.png",
            "protect_mask": "protect_mask.png",
            "editable_mask": "editable_mask.png",
            "metadata": "metadata.json",
        }
        filename = filenames.get(artifact)
        if filename is None:
            raise ValueError("Unknown reference artifact.")
        path = self._reference_dir(sample_id) / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def save_reference_annotations(
        self,
        sample_id: str,
        masks: SemanticMasks,
        *,
        image_size: tuple[int, int],
        reference_quality: str,
    ) -> dict[str, object]:
        if reference_quality not in {"pixel_aligned", "visual_reference"}:
            raise ValueError("Unknown reference quality.")
        sample_dir = self._reference_dir(sample_id)
        if not sample_dir.is_dir():
            raise FileNotFoundError(sample_dir)
        for name in ("part", "dent", "scratch", "dirt", "retouch"):
            getattr(masks, name).convert("L").save(
                sample_dir / f"{name}_mask.png",
                format="PNG",
            )
        masks.editable.convert("L").save(sample_dir / "editable_mask.png", format="PNG")
        protect = ImageChops.subtract(masks.part.convert("L"), masks.editable.convert("L"))
        protect.save(sample_dir / "protect_mask.png", format="PNG")

        metadata_path = sample_dir / "metadata.json"
        metadata: dict[str, object] = {}
        if metadata_path.is_file():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        labels_present = list(masks.labels_present)
        annotation_level = (
            "part_only"
            if not labels_present
            else "general"
            if labels_present == ["retouch"]
            else "detailed"
        )
        metadata.update(
            {
                "id": sample_id,
                "source": "external_reference",
                "synthetic_target": True,
                "accepted": True,
                "original": "before.png",
                "target": "approved_after.png",
                "image_size": list(image_size),
                "reference_quality": reference_quality,
                "labels_present": labels_present,
                "annotation_level": annotation_level,
                "annotated": True,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return metadata

    def save_reference_metadata(
        self,
        sample_id: str,
        metadata: dict[str, object],
    ) -> Path:
        path = self._reference_dir(sample_id) / "metadata.json"
        path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
