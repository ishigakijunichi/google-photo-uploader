#!/usr/bin/env python3

"""
BGMフォルダを作成し、サンプルBGM音楽をセットアップするスクリプト
"""

import os
import sys
import logging
import argparse
from pathlib import Path
import shutil
import urllib.request
import zipfile
import tempfile

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# フリーBGM素材のサンプルURL
# 注意: これは例示用です。実際に使用する場合は著作権に注意してください
SAMPLE_BGM_URLS = [
    "https://www.free-stock-music.com/music/alexander-nakarada-superepic.mp3",
    "https://www.free-stock-music.com/music/purrple-cat-field-of-fireflies.mp3",
    "https://www.free-stock-music.com/music/jay-man-good-vibes.mp3"
]

def create_bgm_folder(destination=None):
    """
    BGMフォルダを作成する
    
    Args:
        destination: BGMフォルダの作成先。Noneの場合はプロジェクトルートに作成
    
    Returns:
        作成したBGMフォルダのパス
    """
    if destination:
        bgm_dir = Path(destination)
    else:
        # プロジェクトのルートディレクトリを特定
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent
        bgm_dir = project_root / 'bgm'
    
    # フォルダが存在しなければ作成
    if not bgm_dir.exists():
        logger.info(f"BGMフォルダを作成します: {bgm_dir}")
        bgm_dir.mkdir(parents=True, exist_ok=True)
    else:
        logger.info(f"既存のBGMフォルダを使用します: {bgm_dir}")
    
    return bgm_dir

def download_sample_bgm(bgm_dir):
    """
    サンプルBGMをダウンロードする
    
    Args:
        bgm_dir: BGMフォルダのパス
    """
    for i, url in enumerate(SAMPLE_BGM_URLS):
        try:
            filename = url.split('/')[-1]
            output_path = bgm_dir / filename
            
            # 既に存在する場合はスキップ
            if output_path.exists():
                logger.info(f"ファイルは既に存在します: {output_path}")
                continue
            
            logger.info(f"サンプルBGMをダウンロード中 ({i+1}/{len(SAMPLE_BGM_URLS)}): {filename}")
            urllib.request.urlretrieve(url, output_path)
            logger.info(f"ダウンロード完了: {output_path}")
        
        except Exception as e:
            logger.error(f"ダウンロード中にエラーが発生しました: {str(e)}")

def copy_existing_music(bgm_dir, source_dirs):
    """
    指定されたディレクトリから音楽ファイルをコピーする
    
    Args:
        bgm_dir: BGMフォルダのパス
        source_dirs: 検索対象のディレクトリリスト
    """
    # サポートする音楽ファイルの拡張子
    audio_extensions = ['.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a']
    
    copied_count = 0
    
    for source_dir in source_dirs:
        source_path = Path(source_dir)
        if not source_path.exists() or not source_path.is_dir():
            logger.warning(f"指定されたディレクトリが存在しません: {source_path}")
            continue
        
        logger.info(f"音楽ファイルを検索中: {source_path}")
        
        # 各拡張子について検索
        for ext in audio_extensions:
            for file_path in source_path.glob(f"**/*{ext}"):
                try:
                    # ファイル名の衝突を避けるためにユニークな名前を生成
                    dest_path = bgm_dir / file_path.name
                    # 既に存在する場合は別名でコピー
                    if dest_path.exists():
                        base_name = file_path.stem
                        extension = file_path.suffix
                        counter = 1
                        while dest_path.exists():
                            dest_path = bgm_dir / f"{base_name}_{counter}{extension}"
                            counter += 1
                    
                    # ファイルをコピー
                    shutil.copy2(file_path, dest_path)
                    logger.info(f"コピー完了: {file_path.name} -> {dest_path}")
                    copied_count += 1
                
                except Exception as e:
                    logger.error(f"ファイルコピー中にエラーが発生: {str(e)}")
    
    if copied_count > 0:
        logger.info(f"合計 {copied_count} 個の音楽ファイルをコピーしました")
    else:
        logger.warning("音楽ファイルは見つかりませんでした")

def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description='BGMフォルダのセットアップを行います')
    parser.add_argument('--destination', '-d', type=str, help='BGMフォルダの作成先')
    parser.add_argument('--sample', '-s', action='store_true', help='サンプルBGMをダウンロードする')
    parser.add_argument('--copy-from', '-c', nargs='+', help='指定フォルダから音楽ファイルをコピーする')
    args = parser.parse_args()
    
    # BGMフォルダを作成
    bgm_dir = create_bgm_folder(args.destination)
    
    # サンプルBGMのダウンロード
    if args.sample:
        download_sample_bgm(bgm_dir)
    
    # 指定フォルダから音楽ファイルをコピー
    if args.copy_from:
        copy_existing_music(bgm_dir, args.copy_from)
    
    # 何も指定されなかった場合のデフォルト動作
    if not args.sample and not args.copy_from:
        logger.info("音楽ファイルを追加するには次のオプションを使用してください:")
        logger.info("  --sample: サンプルBGMをダウンロード")
        logger.info("  --copy-from DIR1 [DIR2...]: 指定フォルダから音楽ファイルをコピー")
    
    logger.info(f"BGMフォルダのセットアップが完了しました: {bgm_dir}")
    logger.info("スライドショーでBGMを使用するには:")
    logger.info("  python src/slideshow.py --bgm --random-bgm")

if __name__ == "__main__":
    main() 