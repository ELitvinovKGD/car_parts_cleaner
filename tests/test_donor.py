from PIL import Image

from body_repair_ai.image_processing.donor import transfer_donor_part
from body_repair_ai.image_processing.masks import prepare_masks


def test_donor_transfer_preserves_target_outside_mask() -> None:
    target = Image.new("RGB", (100, 80), color=(20, 30, 40))
    target_mask = Image.new("L", target.size, color=0)
    target_mask.paste(255, (20, 20, 80, 60))
    donor = Image.new("RGB", (60, 60), color=(200, 50, 40))
    donor_mask = Image.new("L", donor.size, color=0)
    donor_mask.paste(255, (10, 10, 50, 50))

    transfer = transfer_donor_part(
        target,
        prepare_masks(target_mask, expected_size=target.size, feather_radius=2),
        donor,
        prepare_masks(donor_mask, expected_size=donor.size, feather_radius=2),
        match_color=False,
    )

    assert transfer.image.size == target.size
    assert transfer.image.getpixel((0, 0)) == (20, 30, 40)
    assert transfer.image.getpixel((50, 40)) == (200, 50, 40)
    assert transfer.target_box == (20, 20, 80, 60)
    assert transfer.donor_box == (10, 10, 50, 50)


def test_donor_color_matching_moves_donor_toward_target() -> None:
    target = Image.new("RGB", (40, 40), color=(40, 50, 60))
    donor = Image.new("RGB", (40, 40), color=(200, 180, 160))
    mask = Image.new("L", (40, 40), color=255)
    masks = prepare_masks(mask, expected_size=mask.size, feather_radius=0)

    transfer = transfer_donor_part(target, masks, donor, masks, match_color=True)

    assert transfer.image.getpixel((20, 20)) == (40, 50, 60)
