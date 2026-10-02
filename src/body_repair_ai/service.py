from __future__ import annotations

from PIL import Image

from body_repair_ai.config import Settings
from body_repair_ai.domain import JobRecord, JobStatus, Operation
from body_repair_ai.image_processing.masks import composite_result, prepare_masks
from body_repair_ai.inference import InferenceEngine, InferenceRequest
from body_repair_ai.storage import DatasetStore


class RestorationService:
    def __init__(
        self,
        settings: Settings,
        store: DatasetStore,
        engine: InferenceEngine,
    ) -> None:
        self.settings = settings
        self.store = store
        self.engine = engine

    def process(self, original: Image.Image, mask: Image.Image, operation: Operation) -> JobRecord:
        original = original.convert("RGB")
        masks = prepare_masks(
            mask,
            expected_size=original.size,
            threshold=self.settings.mask_threshold,
            feather_radius=self.settings.mask_feather_radius,
        )
        job = JobRecord(operation=operation, backend=self.engine.name)
        self.store.save_inputs(job, original, masks)

        generated_path = self.store.candidate_path(job)
        try:
            job.transition(JobStatus.PROCESSING)
            self.store.save_job(job)
            self.engine.run(
                InferenceRequest(
                    image_path=job.original_path,
                    mask_path=job.hard_mask_path,
                    output_path=generated_path,
                    operation=operation,
                    seed=job.seed,
                )
            )
            with Image.open(job.original_path) as source_image:
                with Image.open(generated_path) as generated_image:
                    final = composite_result(source_image, generated_image, masks.soft)
            final.save(generated_path, format="PNG")
            job.result_path = generated_path
            job.transition(JobStatus.COMPLETED)
        except Exception as exc:
            job.transition(JobStatus.FAILED, error=str(exc))
            raise
        finally:
            self.store.save_job(job)
        return job

    def review(self, job_id: str, *, accepted: bool) -> JobRecord:
        job = self.store.load_job(job_id)
        if job.status not in {JobStatus.COMPLETED, JobStatus.ACCEPTED, JobStatus.REJECTED}:
            raise ValueError(f"Job in state {job.status} cannot be reviewed.")
        self.store.review_job(job, accepted=accepted)
        job.transition(JobStatus.ACCEPTED if accepted else JobStatus.REJECTED)
        self.store.save_job(job)
        return job
