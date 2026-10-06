from __future__ import annotations

from PIL import Image, ImageChops


def split_mask_into_tiles(
    mask: Image.Image,
    *,
    max_span: int,
    overlap: int | None = None,
) -> list[Image.Image]:
    """Split a large mask into local, slightly overlapping model regions."""

    if max_span <= 0:
        raise ValueError("max_span must be positive.")
    if overlap is None:
        overlap = min(32, max_span // 4)
    if overlap < 0 or overlap >= max_span // 2:
        raise ValueError("overlap must be non-negative and smaller than half max_span.")
    normalized = mask.convert("L")
    bounding_box = normalized.getbbox()
    if bounding_box is None:
        return []

    left, top, right, bottom = bounding_box
    if right - left <= max_span and bottom - top <= max_span:
        return [normalized]

    tiles: list[Image.Image] = []
    for core_top in range(top, bottom, max_span):
        core_bottom = min(bottom, core_top + max_span)
        for core_left in range(left, right, max_span):
            core_right = min(right, core_left + max_span)
            tile_left = max(left, core_left - overlap)
            tile_top = max(top, core_top - overlap)
            tile_right = min(right, core_right + overlap)
            tile_bottom = min(bottom, core_bottom + overlap)
            window = Image.new("L", normalized.size, color=0)
            window.paste(255, (tile_left, tile_top, tile_right, tile_bottom))
            tile = ImageChops.multiply(normalized, window)
            if tile.getbbox() is not None:
                tiles.append(tile)
    return tiles
