from PIL import Image, ImageChops

from body_repair_ai.image_processing.tiles import split_mask_into_tiles


def test_small_mask_is_not_split() -> None:
    mask = Image.new("L", (200, 100), color=0)
    mask.paste(255, (20, 20, 80, 60))

    tiles = split_mask_into_tiles(mask, max_span=100)

    assert len(tiles) == 1
    assert ImageChops.difference(tiles[0], mask).getbbox() is None


def test_long_mask_is_split_and_fully_covered() -> None:
    mask = Image.new("L", (500, 120), color=0)
    mask.paste(255, (10, 50, 490, 70))

    tiles = split_mask_into_tiles(mask, max_span=128, overlap=16)
    union = Image.new("L", mask.size, color=0)
    for tile in tiles:
        union = ImageChops.lighter(union, tile)

    assert len(tiles) == 4
    assert ImageChops.difference(union, mask).getbbox() is None
    assert all(tile.getbbox() is not None for tile in tiles)


def test_empty_mask_has_no_tiles() -> None:
    assert split_mask_into_tiles(Image.new("L", (100, 100)), max_span=64) == []
