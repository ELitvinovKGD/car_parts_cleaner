from PIL import Image

from body_repair_ai.image_processing.crop import create_context_crop, restore_crop_to_canvas
from body_repair_ai.image_processing.masks import prepare_masks


def test_context_crop_adds_padding_and_uses_model_dimensions() -> None:
    original = Image.new("RGB", (2000, 1200), color="gray")
    mask = Image.new("L", original.size, color=0)
    for x in range(800, 1200):
        for y in range(500, 700):
            mask.putpixel((x, y), 255)
    masks = prepare_masks(mask, expected_size=original.size)

    crop = create_context_crop(
        original,
        masks,
        padding_ratio=0.5,
        min_crop_edge=64,
        max_edge=1024,
    )

    assert crop.box == (600, 300, 1400, 900)
    assert crop.source_crop_size == (800, 600)
    assert crop.image.size == (768, 576)
    assert crop.hard_mask.size == crop.image.size


def test_context_crop_is_clamped_to_image_boundaries() -> None:
    original = Image.new("RGB", (100, 80), color="gray")
    mask = Image.new("L", original.size, color=0)
    for x in range(0, 20):
        for y in range(0, 10):
            mask.putpixel((x, y), 255)
    masks = prepare_masks(mask, expected_size=original.size)

    crop = create_context_crop(original, masks, padding_ratio=1.0, max_edge=1024)

    assert crop.box[0] == 0
    assert crop.box[1] == 0


def test_context_crop_keeps_minimum_surrounding_context() -> None:
    original = Image.new("RGB", (1200, 800), color="gray")
    mask = Image.new("L", original.size, color=0)
    for x in range(590, 610):
        for y in range(390, 410):
            mask.putpixel((x, y), 255)
    masks = prepare_masks(mask, expected_size=original.size)

    crop = create_context_crop(original, masks, padding_ratio=0.5, min_crop_edge=512)

    assert crop.source_crop_size == (512, 512)
    assert crop.image.size == (512, 512)


def test_restore_crop_preserves_canvas_size() -> None:
    original = Image.new("RGB", (300, 200), color="black")
    mask = Image.new("L", original.size, color=0)
    for x in range(100, 150):
        for y in range(70, 110):
            mask.putpixel((x, y), 255)
    masks = prepare_masks(mask, expected_size=original.size)
    crop = create_context_crop(original, masks, min_crop_edge=64)
    generated = Image.new("RGB", crop.image.size, color="white")

    canvas = restore_crop_to_canvas(original, generated, crop)

    assert canvas.size == original.size
    assert canvas.getpixel((0, 0)) == (0, 0, 0)
    assert canvas.getpixel((125, 90)) == (255, 255, 255)
