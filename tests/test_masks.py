import numpy as np
import pytest
from PIL import Image

from body_repair_ai.image_processing.masks import composite_result, prepare_masks


def test_prepare_masks_builds_binary_mask_and_bbox() -> None:
    mask_array = np.zeros((10, 12), dtype=np.uint8)
    mask_array[2:7, 3:9] = 240
    mask = Image.fromarray(mask_array, mode="L")

    bundle = prepare_masks(mask, expected_size=(12, 10), feather_radius=2)

    assert bundle.bounding_box == (3, 2, 9, 7)
    assert set(np.unique(np.asarray(bundle.hard))) == {0, 255}
    assert bundle.soft.size == mask.size


def test_prepare_masks_rejects_wrong_size() -> None:
    mask = Image.new("L", (4, 4), color=255)

    with pytest.raises(ValueError, match="does not match"):
        prepare_masks(mask, expected_size=(8, 8))


def test_prepare_masks_rejects_empty_mask() -> None:
    mask = Image.new("L", (8, 8), color=0)

    with pytest.raises(ValueError, match="editable region"):
        prepare_masks(mask, expected_size=(8, 8))


def test_composite_keeps_pixels_outside_mask() -> None:
    original = Image.new("RGB", (4, 4), color=(10, 20, 30))
    generated = Image.new("RGB", (4, 4), color=(200, 210, 220))
    mask = Image.new("L", (4, 4), color=0)
    mask.putpixel((1, 1), 255)

    result = composite_result(original, generated, mask)

    assert result.getpixel((0, 0)) == (10, 20, 30)
    assert result.getpixel((1, 1)) == (200, 210, 220)
