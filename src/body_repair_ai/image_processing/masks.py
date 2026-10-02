from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter


@dataclass(frozen=True, slots=True)
class MaskBundle:
    hard: Image.Image
    soft: Image.Image
    bounding_box: tuple[int, int, int, int]


def prepare_masks(
    mask: Image.Image,
    *,
    expected_size: tuple[int, int],
    threshold: int = 127,
    feather_radius: float = 8.0,
) -> MaskBundle:
    """Normalize a user mask and produce hard/soft variants.

    White pixels mark the editable region. The hard mask is suitable for
    inpainting; the soft mask is suitable for compositing the result.
    """

    if mask.size != expected_size:
        raise ValueError(
            f"Mask size {mask.size} does not match image size {expected_size}."
        )

    grayscale = np.asarray(mask.convert("L"), dtype=np.uint8)
    binary = np.where(grayscale > threshold, 255, 0).astype(np.uint8)
    if not np.any(binary):
        raise ValueError("Mask does not contain an editable region.")

    hard = Image.fromarray(binary, mode="L")
    bbox = hard.getbbox()
    if bbox is None:  # Defensive: np.any above should already prevent this.
        raise ValueError("Mask does not contain an editable region.")

    soft = hard.filter(ImageFilter.GaussianBlur(radius=feather_radius))
    return MaskBundle(hard=hard, soft=soft, bounding_box=bbox)


def composite_result(
    original: Image.Image,
    generated: Image.Image,
    soft_mask: Image.Image,
) -> Image.Image:
    """Guarantee that pixels outside the mask come from the original image."""

    if generated.size != original.size or soft_mask.size != original.size:
        raise ValueError("Original, generated image, and mask must have equal sizes.")
    return Image.composite(generated.convert("RGB"), original.convert("RGB"), soft_mask)
