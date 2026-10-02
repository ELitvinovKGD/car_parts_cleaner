from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from body_repair_ai.image_processing.masks import MaskBundle


@dataclass(frozen=True, slots=True)
class CropBundle:
    image: Image.Image
    hard_mask: Image.Image
    soft_mask: Image.Image
    box: tuple[int, int, int, int]
    source_crop_size: tuple[int, int]


def _model_dimension(value: int, *, max_edge: int, multiple: int) -> int:
    limited = min(value, max_edge)
    rounded = round(limited / multiple) * multiple
    return max(multiple, min(max_edge, rounded))


def create_context_crop(
    original: Image.Image,
    masks: MaskBundle,
    *,
    padding_ratio: float = 0.5,
    min_crop_edge: int = 512,
    max_edge: int = 1024,
    multiple: int = 64,
) -> CropBundle:
    """Crop around the defect while preserving surrounding lighting context."""

    left, top, right, bottom = masks.bounding_box
    defect_width = right - left
    defect_height = bottom - top
    padding = round(max(defect_width, defect_height) * padding_ratio)

    desired_width = min(original.width, max(right - left + 2 * padding, min_crop_edge))
    desired_height = min(original.height, max(bottom - top + 2 * padding, min_crop_edge))
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    crop_left = max(0, min(original.width - desired_width, center_x - desired_width // 2))
    crop_top = max(0, min(original.height - desired_height, center_y - desired_height // 2))
    crop_box = (
        crop_left,
        crop_top,
        crop_left + desired_width,
        crop_top + desired_height,
    )
    source_size = (crop_box[2] - crop_box[0], crop_box[3] - crop_box[1])
    model_size = (
        _model_dimension(source_size[0], max_edge=max_edge, multiple=multiple),
        _model_dimension(source_size[1], max_edge=max_edge, multiple=multiple),
    )

    image_crop = original.crop(crop_box).resize(model_size, Image.Resampling.LANCZOS)
    hard_crop = masks.hard.crop(crop_box).resize(model_size, Image.Resampling.NEAREST)
    soft_crop = masks.soft.crop(crop_box).resize(model_size, Image.Resampling.BILINEAR)
    return CropBundle(
        image=image_crop,
        hard_mask=hard_crop,
        soft_mask=soft_crop,
        box=crop_box,
        source_crop_size=source_size,
    )


def restore_crop_to_canvas(
    original: Image.Image,
    generated_crop: Image.Image,
    crop: CropBundle,
) -> Image.Image:
    """Place a generated crop on an original-sized canvas for final compositing."""

    canvas = original.convert("RGB").copy()
    restored = generated_crop.convert("RGB").resize(
        crop.source_crop_size,
        Image.Resampling.LANCZOS,
    )
    canvas.paste(restored, (crop.box[0], crop.box[1]))
    return canvas
