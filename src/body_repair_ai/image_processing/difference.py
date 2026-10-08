from __future__ import annotations

import numpy as np
from PIL import Image, ImageChops, ImageFilter


def create_change_mask(
    before: Image.Image,
    after: Image.Image,
    part_mask: Image.Image,
    *,
    threshold: int = 18,
    expansion: int = 9,
) -> Image.Image:
    """Build a coarse editable mask from an aligned before/after pair.

    Small color noise is ignored, nearby changed pixels are joined, and the
    result is clipped to the user-selected body part.
    """

    if before.size != after.size:
        raise ValueError("Automatic change masks require equal image sizes.")
    if part_mask.size != before.size:
        raise ValueError("Part mask size does not match the reference image.")
    if not 1 <= threshold <= 255:
        raise ValueError("Difference threshold must be between 1 and 255.")
    if expansion < 1 or expansion % 2 == 0:
        raise ValueError("Expansion must be a positive odd number.")

    before_pixels = np.asarray(before.convert("RGB"), dtype=np.int16)
    after_pixels = np.asarray(after.convert("RGB"), dtype=np.int16)
    part = np.asarray(part_mask.convert("L"), dtype=np.uint8) > 127
    if not np.any(part):
        raise ValueError("Select the body part before finding changes.")

    difference = np.max(np.abs(after_pixels - before_pixels), axis=2)
    changed = (difference >= threshold) & part
    mask = Image.fromarray(np.where(changed, 255, 0).astype(np.uint8), mode="L")
    if mask.getbbox() is None:
        return mask

    # Join nearby changed pixels into convenient regions for training while
    # keeping the result strictly inside the selected part.
    mask = mask.filter(ImageFilter.MaxFilter(expansion))
    mask = mask.filter(ImageFilter.MedianFilter(size=5))
    binary_part = Image.fromarray(np.where(part, 255, 0).astype(np.uint8), mode="L")
    return ImageChops.multiply(mask, binary_part)
