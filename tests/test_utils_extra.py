import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "src"))

from google_photos_uploader.utils import find_media_files, get_dcim_path


def test_get_dcim_path(tmp_path):
    sd = tmp_path / "SD"
    dcim_dir = sd / "DCIM"
    dcim_dir.mkdir(parents=True)
    assert get_dcim_path(sd) == dcim_dir


def test_get_dcim_path_none(tmp_path):
    sd = tmp_path / "SD"
    sd.mkdir()
    assert get_dcim_path(sd) is None


def test_find_media_files(tmp_path):
    img = tmp_path / "img.JPG"
    img.write_text("test")
    video = tmp_path / "movie.mp4"
    video.write_text("test")
    other = tmp_path / "other.txt"
    other.write_text("nope")

    files = find_media_files(tmp_path)
    assert img in files
    assert video in files
    assert other not in files
