import numpy as np
import pytest
from PIL import Image

from body_repair_ai.image_processing.difference import create_change_mask


def test_change_mask_detects_changes_only_inside_part() -> None:
    before = Image.new("RGB", (20, 20), color=(10, 10, 10))
    after = before.copy()
    for x in range(6, 10):
        for y in range(6, 10):
            after.putpixel((x, y), (80, 80, 80))
    after.putpixel((18, 18), (255, 255, 255))
    part = Image.new("L", (20, 20), color=0)
    for x in range(2, 15):
        for y in range(2, 15):
            part.putpixel((x, y), 255)

    mask = create_change_mask(before, after, part)

    pixels = np.asarray(mask)
    assert pixels[7, 7] == 255
    assert pixels[18, 18] == 0
    assert np.all(pixels[np.asarray(part) == 0] == 0)


def test_change_mask_requires_aligned_images() -> None:
    with pytest.raises(ValueError, match="equal image sizes"):
        create_change_mask(
            Image.new("RGB", (10, 10)),
            Image.new("RGB", (10, 11)),
            Image.new("L", (10, 10), color=255),
        )
