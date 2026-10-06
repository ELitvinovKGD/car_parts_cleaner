from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from body_repair_ai.image_processing.masks import MaskBundle


@dataclass(frozen=True, slots=True)
class CropBundle:
    image: Image.Image
    hard_mask: Image.Image
    soft_mask: Image.Image
    box: tuple[int, int, int, int]
    source_crop_size: tuple[int, int]
    content_box: tuple[int, int, int, int]


def _ceil_to_multiple(value: int, multiple: int) -> int:
    return max(multiple, ((value + multiple - 1) // multiple) * multiple)


def _model_layout(
    source_size: tuple[int, int],
    *,
    max_edge: int,
    multiple: int,
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int, int, int]]:
    """Fit without stretching, then pad to model-compatible dimensions."""

    source_width, source_height = source_size
    usable_max_edge = max(multiple, (max_edge // multiple) * multiple)
    scale = min(1.0, usable_max_edge / max(source_width, source_height))
    content_width = max(1, round(source_width * scale))
    content_height = max(1, round(source_height * scale))
    canvas_width = min(usable_max_edge, _ceil_to_multiple(content_width, multiple))
    canvas_height = min(usable_max_edge, _ceil_to_multiple(content_height, multiple))
    left = (canvas_width - content_width) // 2
    top = (canvas_height - content_height) // 2
    content_box = (left, top, left + content_width, top + content_height)
    return (content_width, content_height), (canvas_width, canvas_height), content_box


def _pad_array_to_canvas(
    image: Image.Image,
    canvas_size: tuple[int, int],
    content_box: tuple[int, int, int, int],
    *,
    edge_padding: bool,
) -> Image.Image:
    array = np.asarray(image)
    left, top, right, bottom = content_box
    padding = ((top, canvas_size[1] - bottom), (left, canvas_size[0] - right))
    if array.ndim == 3:
        padding += ((0, 0),)
    mode = "edge" if edge_padding else "constant"
    return Image.fromarray(np.pad(array, padding, mode=mode))


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
    content_size, model_size, content_box = _model_layout(
        source_size,
        max_edge=max_edge,
        multiple=multiple,
    )

    image_content = original.crop(crop_box).resize(content_size, Image.Resampling.LANCZOS)
    hard_content = masks.hard.crop(crop_box).resize(content_size, Image.Resampling.NEAREST)
    soft_content = masks.soft.crop(crop_box).resize(content_size, Image.Resampling.BILINEAR)
    image_crop = _pad_array_to_canvas(
        image_content, model_size, content_box, edge_padding=True
    )
    hard_crop = _pad_array_to_canvas(
        hard_content, model_size, content_box, edge_padding=False
    )
    soft_crop = _pad_array_to_canvas(
        soft_content, model_size, content_box, edge_padding=False
    )
    return CropBundle(
        image=image_crop,
        hard_mask=hard_crop,
        soft_mask=soft_crop,
        box=crop_box,
        source_crop_size=source_size,
        content_box=content_box,
    )


def restore_crop_to_canvas(
    original: Image.Image,
    generated_crop: Image.Image,
    crop: CropBundle,
) -> Image.Image:
    """Place a generated crop on an original-sized canvas for final compositing."""

    canvas = original.convert("RGB").copy()
    normalized = generated_crop.convert("RGB")
    if normalized.size != crop.image.size:
        normalized = normalized.resize(crop.image.size, Image.Resampling.LANCZOS)
    restored = normalized.crop(crop.content_box).resize(
        crop.source_crop_size,
        Image.Resampling.LANCZOS,
    )
    canvas.paste(restored, (crop.box[0], crop.box[1]))
    return canvas
