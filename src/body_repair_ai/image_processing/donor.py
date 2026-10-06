from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageChops

from body_repair_ai.image_processing.masks import MaskBundle


@dataclass(frozen=True, slots=True)
class DonorTransfer:
    image: Image.Image
    aligned_donor: Image.Image
    composite_mask: Image.Image
    target_box: tuple[int, int, int, int]
    donor_box: tuple[int, int, int, int]


def _match_color(
    donor: Image.Image,
    target: Image.Image,
    mask: Image.Image,
) -> Image.Image:
    donor_array = np.asarray(donor.convert("RGB"), dtype=np.float32)
    target_array = np.asarray(target.convert("RGB"), dtype=np.float32)
    active = np.asarray(mask.convert("L")) > 127
    if active.sum() < 16:
        return donor

    donor_pixels = donor_array[active]
    target_pixels = target_array[active]
    donor_mean = donor_pixels.mean(axis=0)
    target_mean = target_pixels.mean(axis=0)
    donor_std = np.maximum(donor_pixels.std(axis=0), 8.0)
    target_std = np.maximum(target_pixels.std(axis=0), 8.0)
    scale = np.clip(target_std / donor_std, 0.5, 2.0)
    matched = (donor_array - donor_mean) * scale + target_mean
    return Image.fromarray(np.clip(matched, 0, 255).astype(np.uint8), mode="RGB")


def transfer_donor_part(
    target: Image.Image,
    target_masks: MaskBundle,
    donor: Image.Image,
    donor_masks: MaskBundle,
    *,
    match_color: bool = True,
) -> DonorTransfer:
    """Align a masked donor by bounding boxes and composite it into the target part."""

    target = target.convert("RGB")
    donor = donor.convert("RGB")
    target_box = target_masks.bounding_box
    donor_box = donor_masks.bounding_box
    target_size = (target_box[2] - target_box[0], target_box[3] - target_box[1])

    donor_crop = donor.crop(donor_box).resize(target_size, Image.Resampling.LANCZOS)
    donor_mask_crop = donor_masks.hard.crop(donor_box).resize(
        target_size,
        Image.Resampling.NEAREST,
    )
    aligned_donor = target.copy()
    aligned_donor.paste(donor_crop, (target_box[0], target_box[1]))
    aligned_mask = Image.new("L", target.size, color=0)
    aligned_mask.paste(donor_mask_crop, (target_box[0], target_box[1]))
    composite_mask = ImageChops.multiply(target_masks.soft, aligned_mask)

    if match_color:
        aligned_donor = _match_color(aligned_donor, target, composite_mask)
    result = Image.composite(aligned_donor, target, composite_mask)
    return DonorTransfer(
        image=result,
        aligned_donor=aligned_donor,
        composite_mask=composite_mask,
        target_box=target_box,
        donor_box=donor_box,
    )
