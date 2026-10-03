import numpy as np
import pytest
from PIL import Image

from body_repair_ai.image_processing.semantic import parse_layer_masks, parse_semantic_mask


def test_parse_semantic_mask_separates_labels() -> None:
    annotation = Image.new("RGB", (12, 10), color="black")
    annotation.putpixel((1, 1), (255, 255, 255))
    annotation.putpixel((2, 2), (255, 0, 0))
    annotation.putpixel((3, 3), (255, 255, 0))
    annotation.putpixel((4, 4), (255, 0, 255))

    masks = parse_semantic_mask(annotation, expected_size=annotation.size)

    assert masks.labels_present == ("dent", "dirt", "scratch")
    assert np.asarray(masks.part)[2, 2] == 255
    assert np.asarray(masks.editable)[1, 1] == 0
    assert np.asarray(masks.editable)[2, 2] == 255


def test_parse_semantic_mask_requires_a_defect_label() -> None:
    annotation = Image.new("RGB", (8, 8), color="white")

    with pytest.raises(ValueError, match="Mark at least one defect"):
        parse_semantic_mask(annotation, expected_size=annotation.size)


def test_independent_layers_can_overlap() -> None:
    size = (8, 8)
    part = Image.new("L", size, color=255)
    dent = Image.new("L", size, color=0)
    dirt = Image.new("L", size, color=0)
    scratch = Image.new("L", size, color=0)
    dent.putpixel((3, 4), 255)
    dirt.putpixel((3, 4), 255)

    masks = parse_layer_masks(
        part=part,
        dent=dent,
        dirt=dirt,
        scratch=scratch,
        expected_size=size,
    )

    assert masks.labels_present == ("dent", "dirt")
    assert masks.dent.getpixel((3, 4)) == 255
    assert masks.dirt.getpixel((3, 4)) == 255


def test_defect_layers_are_clipped_to_part_boundary() -> None:
    size = (8, 8)
    part = Image.new("L", size, color=0)
    part.putpixel((2, 2), 255)
    dent = Image.new("L", size, color=0)
    dent.putpixel((2, 2), 255)
    dent.putpixel((7, 7), 255)
    empty = Image.new("L", size, color=0)

    masks = parse_layer_masks(
        part=part,
        dent=dent,
        dirt=empty,
        scratch=empty,
        expected_size=size,
    )

    assert masks.dent.getpixel((2, 2)) == 255
    assert masks.dent.getpixel((7, 7)) == 0
