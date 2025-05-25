import sys
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "src"))

from google_photos_uploader.utils import find_sd_card


def test_find_sd_card_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32", raising=False)

    drives = ["C:\\", "E:\\"]

    def mock_GetLogicalDriveStrings():
        return "\000".join(drives) + "\000"

    def mock_GetVolumeInformation(drive):
        if drive == "C:\\":
            return ("System", None, None, None, None)
        elif drive == "E:\\":
            return ("PHOTO_UPLOAD_SD", None, None, None, None)
        raise OSError

    mock_win32api = SimpleNamespace(
        GetLogicalDriveStrings=mock_GetLogicalDriveStrings,
        GetVolumeInformation=mock_GetVolumeInformation,
    )
    monkeypatch.setitem(sys.modules, "win32api", mock_win32api)

    path = find_sd_card("PHOTO_UPLOAD_SD")
    assert path == Path("E:\\")
