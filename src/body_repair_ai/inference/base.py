from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from body_repair_ai.domain import Operation


@dataclass(frozen=True, slots=True)
class InferenceRequest:
    image_path: Path
    mask_path: Path
    output_path: Path
    operation: Operation
    seed: int | None = None


class InferenceEngine(Protocol):
    name: str

    def run(self, request: InferenceRequest) -> Path: ...
