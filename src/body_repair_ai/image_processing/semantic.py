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


def parse_layer_masks(
    *,
    part: Image.Image,
    dent: Image.Image,
    dirt: Image.Image,
    scratch: Image.Image,
    expected_size: tuple[int, int],
    threshold: int = 127,
) -> SemanticMasks:
    """Normalize four independent grayscale annotation layers.

    Layers deliberately remain independent: a dirty dent may be present in both
    masks without one annotation destroying the other.
    """

    source_layers = {"part": part, "dent": dent, "dirt": dirt, "scratch": scratch}
    conditions: dict[str, np.ndarray] = {}
    for name, image in source_layers.items():
        if image.size != expected_size:
            raise ValueError(
                f"{name} mask size {image.size} does not match image size {expected_size}."
            )
        conditions[name] = np.asarray(image.convert("L"), dtype=np.uint8) > threshold

    if not np.any(conditions["part"]):
        raise ValueError("Select the body part before marking defects.")

    # The part layer is the hard safety boundary. Defect strokes outside it are
    # clipped so the background and neighbouring panels remain protected.
    for name in ("dent", "dirt", "scratch"):
        conditions[name] &= conditions["part"]
    editable_condition = conditions["dent"] | conditions["dirt"] | conditions["scratch"]
    if not np.any(editable_condition):
        raise ValueError("Mark at least one defect inside the selected body part.")
    return SemanticMasks(
        part=_binary_image(conditions["part"]),
        dent=_binary_image(conditions["dent"]),
        dirt=_binary_image(conditions["dirt"]),
        scratch=_binary_image(conditions["scratch"]),
        editable=_binary_image(editable_condition),
    )


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
