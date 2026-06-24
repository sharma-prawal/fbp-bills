from PIL import Image, ImageDraw

from app.visual_audit import content_bbox


def test_content_bbox_finds_non_white_area() -> None:
    image = Image.new("RGB", (100, 80), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 15, 60, 45), fill="black")

    assert content_bbox(image) == (20, 15, 61, 46)
