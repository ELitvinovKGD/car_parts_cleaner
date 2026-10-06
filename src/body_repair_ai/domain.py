from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Operation(StrEnum):
    MIXED_REPAIR = "mixed_repair"
    DONOR_TRANSFER = "donor_transfer"
    REMOVE_DENT = "remove_dent"
    REMOVE_DIRT = "remove_dirt"
    REMOVE_SCRATCH = "remove_scratch"


class JobStatus(StrEnum):
    CREATED = "created"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class JobRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    operation: Operation
    status: JobStatus = JobStatus.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    original_path: Path | None = None
    hard_mask_path: Path | None = None
    soft_mask_path: Path | None = None
    semantic_mask_path: Path | None = None
    donor_path: Path | None = None
    donor_mask_path: Path | None = None
    layer_mask_paths: dict[str, Path] = Field(default_factory=dict)
    completed_stages: list[Operation] = Field(default_factory=list)
    stage_tile_counts: dict[str, int] = Field(default_factory=dict)
    result_path: Path | None = None
    backend: str = "mock"
    seed: int | None = None
    crop_box: tuple[int, int, int, int] | None = None
    model_input_size: tuple[int, int] | None = None
    error: str | None = None

    def transition(self, status: JobStatus, *, error: str | None = None) -> None:
        self.status = status
        self.error = error
        self.updated_at = datetime.now(UTC)
