import logging
import os
import sys
from pathlib import Path
from typing import List, Optional, Set

# ロギングの設定
def setup_logging(level: int = logging.INFO) -> None:
    """ロギングの基本設定を行う

    Args:
        level: ログレベル
    """
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(Path.home() / '.google_photos_uploader' / 'uploader.log')
        ]
    )

# ファイル関連の定数
SUPPORTED_EXTENSIONS: Set[str] = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp',  # 画像ファイル
    '.mp4', '.mov', '.avi', '.wmv', '.mkv'    # 動画ファイル
}

AUDIO_EXTENSIONS: Set[str] = {
    '.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a'
}

def find_sd_card(volume_name: str = "PHOTO_UPLOAD_SD") -> Optional[Path]:
    """SDカードのマウントポイントを探す

    Args:
        volume_name: SDカードのボリューム名

    Returns:
        Optional[Path]: SDカードのパス。見つからない場合はNone
    """
    # macOSの場合は/Volumes以下を探す
    if sys.platform == 'darwin':
        sd_path = Path('/Volumes') / volume_name
        if sd_path.exists():
            return sd_path
    # Linuxの場合は/media/$USER以下を探す
    elif sys.platform.startswith('linux'):
        user = os.environ.get('USER', 'user')
        sd_path = Path(f'/media/{user}') / volume_name
        if sd_path.exists():
            return sd_path
        # Ubuntuの別のパターン
        sd_path = Path('/media') / volume_name
        if sd_path.exists():
            return sd_path
    # Windowsの場合はドライブレターを探す
    elif sys.platform == 'win32':
        import win32api
        drives = win32api.GetLogicalDriveStrings().split('\000')[:-1]
        for drive in drives:
            try:
                volume_name = win32api.GetVolumeInformation(drive)[0]
                if volume_name == volume_name:
                    return Path(drive)
            except:
                continue
                
    return None

def get_dcim_path(sd_path: Path) -> Optional[Path]:
    """SDカード内のDCIMフォルダのパスを取得

    Args:
        sd_path: SDカードのパス

    Returns:
        Optional[Path]: DCIMフォルダのパス。見つからない場合はNone
    """
    dcim_path = sd_path / "DCIM"
    if dcim_path.exists():
        return dcim_path
    return None

def find_media_files(directory: Path, extensions: Optional[Set[str]] = None) -> List[Path]:
    """指定されたディレクトリ内のメディアファイルを検索

    Args:
        directory: 検索対象のディレクトリ
        extensions: 検索対象の拡張子のセット。Noneの場合はSUPPORTED_EXTENSIONSを使用

    Returns:
        List[Path]: メディアファイルのパスのリスト
    """
    if extensions is None:
        extensions = SUPPORTED_EXTENSIONS
    
    media_files = []
    for ext in extensions:
        media_files.extend(directory.glob(f"**/*{ext}"))
        media_files.extend(directory.glob(f"**/*{ext.upper()}"))
    
    return sorted(media_files)
