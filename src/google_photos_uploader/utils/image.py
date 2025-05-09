from PIL import Image, ExifTags
from typing import Tuple

__all__ = [
    "resize_to_fit",
    "rotate_exif",
]

# EXIF Orientation タグを検索
_ORIENTATION_TAG = None
for k, v in ExifTags.TAGS.items():
    if v == "Orientation":
        _ORIENTATION_TAG = k
        break

def rotate_exif(img: Image.Image) -> Image.Image:
    """EXIF の Orientation 情報に従い画像を回転して返す"""
    try:
        if _ORIENTATION_TAG is None:
            return img
        exif = img._getexif()
        if exif is None:
            return img
        orient = exif.get(_ORIENTATION_TAG)
        if orient == 2:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        elif orient == 3:
            img = img.transpose(Image.ROTATE_180)
        elif orient == 4:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        elif orient == 5:
            img = img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_90)
        elif orient == 6:
            img = img.transpose(Image.ROTATE_270)
        elif orient == 7:
            img = img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_270)
        elif orient == 8:
            img = img.transpose(Image.ROTATE_90)
    except Exception:
        pass
    return img

def resize_to_fit(img: Image.Image, max_size: Tuple[int, int]) -> Image.Image:
    """指定された最大サイズに収まるようアスペクト比を維持してリサイズ"""
    max_w, max_h = max_size
    w, h = img.size
    if w == 0 or h == 0:
        return img
    aspect = w / h
    if w > max_w:
        w = max_w
        h = int(w / aspect)
    if h > max_h:
        h = max_h
        w = int(h * aspect)
    return img.resize((w, h), Image.Resampling.LANCZOS) 