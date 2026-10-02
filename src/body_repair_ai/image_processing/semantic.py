from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

SEMANTIC_COLORS = {
    "part": (255, 255, 255),
    "dent": (255, 0, 0),
    "dirt": (255, 255, 0),
    "scratch": (255, 0, 255),
}


@dataclass(frozen=True, slots=True)
class SemanticMasks:
    part: Image.Image
    dent: Image.Image
    dirt: Image.Image
    scratch: Image.Image
    editable: Image.Image

    @property
    def labels_present(self) -> tuple[str, ...]:
        labels = []
        for name in ("dent", "dirt", "scratch"):
            if np.any(np.asarray(getattr(self, name))):
                labels.append(name)
        return tuple(labels)


def _binary_image(condition: np.ndarray) -> Image.Image:
    return Image.fromarray(np.where(condition, 255, 0).astype(np.uint8))


def parse_semantic_mask(
    annotation: Image.Image,
    *,
    expected_size: tuple[int, int],
    color_tolerance: int = 16,
) -> SemanticMasks:
    """Convert a palette annotation into independent model and dataset masks."""

    if annotation.size != expected_size:
        raise ValueError(
            f"Semantic mask size {annotation.size} does not match image size {expected_size}."
        )
    pixels = np.asarray(annotation.convert("RGB"), dtype=np.int16)

    def matches(color: tuple[int, int, int]) -> np.ndarray:
        target = np.asarray(color, dtype=np.int16)
        return np.max(np.abs(pixels - target), axis=2) <= color_tolerance

    part_condition = matches(SEMANTIC_COLORS["part"])
    dent_condition = matches(SEMANTIC_COLORS["dent"])
    dirt_condition = matches(SEMANTIC_COLORS["dirt"])
    scratch_condition = matches(SEMANTIC_COLORS["scratch"])
    editable_condition = dent_condition | dirt_condition | scratch_condition
    if not np.any(editable_condition):
        raise ValueError(
            "Mark at least one defect: red for dents, yellow for dirt, or magenta for scratches."
        )

    # Defect pixels are part of the selected body element even when they overwrite white strokes.
    part_condition |= editable_condition
    return SemanticMasks(
        part=_binary_image(part_condition),
        dent=_binary_image(dent_condition),
        dirt=_binary_image(dirt_condition),
        scratch=_binary_image(scratch_condition),
        editable=_binary_image(editable_condition),
    )
