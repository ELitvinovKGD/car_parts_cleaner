from __future__ import annotations

import secrets

from PIL import Image

from body_repair_ai.config import Settings
from body_repair_ai.domain import JobRecord, JobStatus, Operation
from body_repair_ai.image_processing.crop import create_context_crop, restore_crop_to_canvas
from body_repair_ai.image_processing.donor import transfer_donor_part
from body_repair_ai.image_processing.masks import composite_result, prepare_masks
from body_repair_ai.image_processing.semantic import SemanticMasks
from body_repair_ai.image_processing.tiles import split_mask_into_tiles
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

    def _run_stage(
        self,
        current: Image.Image,
        stage_mask: Image.Image,
        operation: Operation,
        job: JobRecord,
        *,
        stage_index: int,
    ) -> Image.Image:
        tile_masks = split_mask_into_tiles(
            stage_mask,
            max_span=self.settings.max_mask_tile_span,
        )
        stage_name = operation.value
        job.stage_tile_counts[stage_name] = len(tile_masks)

        for tile_index, tile_mask in enumerate(tile_masks, start=1):
            masks = prepare_masks(
                tile_mask,
                expected_size=current.size,
                threshold=self.settings.mask_threshold,
                feather_radius=self.settings.mask_feather_radius,
            )
            crop = create_context_crop(
                current,
                masks,
                padding_ratio=self.settings.crop_padding_ratio,
                min_crop_edge=self.settings.min_crop_edge,
                max_edge=self.settings.max_model_edge,
            )
            prefix = f"{stage_index:02d}-{stage_name}-{tile_index:02d}"
            work_image_path = self.store.work_path(job, f"{prefix}-input.png")
            work_mask_path = self.store.work_path(job, f"{prefix}-mask.png")
            generated_crop_path = self.store.work_path(job, f"{prefix}-generated.png")
            crop.image.save(work_image_path, format="PNG")
            crop.hard_mask.save(work_mask_path, format="PNG")
            self.engine.run(
                InferenceRequest(
                    image_path=work_image_path,
                    mask_path=work_mask_path,
                    output_path=generated_crop_path,
                    operation=operation,
                    seed=(job.seed or 0) + (stage_index - 1) * 1000 + tile_index - 1,
                )
            )
            with Image.open(generated_crop_path) as generated_crop:
                generated_canvas = restore_crop_to_canvas(current, generated_crop, crop)
                current = composite_result(current, generated_canvas, masks.soft)
            current.save(
                self.store.work_path(job, f"{prefix}-result.png"),
                format="PNG",
            )
            job.crop_box = crop.box
            job.model_input_size = crop.image.size
            self.store.save_job(job)
        return current

    def process(
        self,
        original: Image.Image,
        mask: Image.Image,
        operation: Operation,
        *,
        semantic_mask: Image.Image | None = None,
    ) -> JobRecord:
        original = original.convert("RGB")
        masks = prepare_masks(
            mask,
            expected_size=original.size,
            threshold=self.settings.mask_threshold,
            feather_radius=self.settings.mask_feather_radius,
        )
        job = JobRecord(
            operation=operation,
            backend=self.engine.name,
            seed=secrets.randbelow(2**32),
        )
        self.store.save_inputs(job, original, masks, semantic_mask)

        result_path = self.store.candidate_path(job)
        try:
            job.transition(JobStatus.PROCESSING)
            self.store.save_job(job)
            final = self._run_stage(
                original,
                masks.hard,
                operation,
                job,
                stage_index=1,
            )
            final.save(result_path, format="PNG")
            job.result_path = result_path
            job.transition(JobStatus.COMPLETED)
        except Exception as exc:
            job.transition(JobStatus.FAILED, error=str(exc))
            raise
        finally:
            self.store.save_job(job)
        return job

    def process_layers(
        self,
        original: Image.Image,
        semantic_masks: SemanticMasks,
    ) -> JobRecord:
        """Run independent defect layers in a deterministic restoration order."""

        original = original.convert("RGB")
        stages = [
            (Operation.REMOVE_DENT, semantic_masks.dent),
            (Operation.REMOVE_SCRATCH, semantic_masks.scratch),
            (Operation.REMOVE_DIRT, semantic_masks.dirt),
        ]
        stages = [(operation, mask) for operation, mask in stages if mask.getbbox()]
        operation = stages[0][0] if len(stages) == 1 else Operation.MIXED_REPAIR
        combined_masks = prepare_masks(
            semantic_masks.editable,
            expected_size=original.size,
            threshold=self.settings.mask_threshold,
            feather_radius=self.settings.mask_feather_radius,
        )
        job = JobRecord(
            operation=operation,
            backend=self.engine.name,
            seed=secrets.randbelow(2**32),
        )
        self.store.save_layer_inputs(job, original, combined_masks, semantic_masks)

        current = original.copy()
        result_path = self.store.candidate_path(job)
        try:
            job.transition(JobStatus.PROCESSING)
            self.store.save_job(job)
            for index, (stage_operation, stage_mask) in enumerate(stages, start=1):
                current = self._run_stage(
                    current,
                    stage_mask,
                    stage_operation,
                    job,
                    stage_index=index,
                )
                job.completed_stages.append(stage_operation)
                self.store.save_job(job)

            current.save(result_path, format="PNG")
            job.result_path = result_path
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

    def process_donor(
        self,
        target: Image.Image,
        target_mask: Image.Image,
        donor: Image.Image,
        donor_mask: Image.Image,
        *,
        match_color: bool = True,
    ) -> JobRecord:
        target = target.convert("RGB")
        donor = donor.convert("RGB")
        target_masks = prepare_masks(
            target_mask,
            expected_size=target.size,
            threshold=self.settings.mask_threshold,
            feather_radius=self.settings.mask_feather_radius,
        )
        donor_masks = prepare_masks(
            donor_mask,
            expected_size=donor.size,
            threshold=self.settings.mask_threshold,
            feather_radius=self.settings.mask_feather_radius,
        )
        job = JobRecord(operation=Operation.DONOR_TRANSFER, backend="local-donor-align")
        self.store.save_donor_inputs(job, target, target_masks, donor, donor_masks)
        result_path = self.store.candidate_path(job)
        try:
            job.transition(JobStatus.PROCESSING)
            self.store.save_job(job)
            transfer = transfer_donor_part(
                target,
                target_masks,
                donor,
                donor_masks,
                match_color=match_color,
            )
            transfer.aligned_donor.save(
                self.store.work_path(job, "aligned-donor.png"), format="PNG"
            )
            transfer.composite_mask.save(
                self.store.work_path(job, "composite-mask.png"), format="PNG"
            )
            transfer.image.save(result_path, format="PNG")
            job.crop_box = transfer.target_box
            job.model_input_size = donor.size
            job.result_path = result_path
            job.transition(JobStatus.COMPLETED)
        except Exception as exc:
            job.transition(JobStatus.FAILED, error=str(exc))
            raise
        finally:
            self.store.save_job(job)
        return job
