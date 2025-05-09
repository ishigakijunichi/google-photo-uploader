#!/usr/bin/env python3

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from .auth import get_credentials
from .service import upload_media, batch_create_media_items
from .utils import setup_logging, find_media_files

logger = logging.getLogger(__name__)

def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパース

    Returns:
        argparse.Namespace: パースされた引数
    """
    parser = argparse.ArgumentParser(description='Google Photos Uploader')
    
    # ファイル関連の引数
    parser.add_argument('files', nargs='*', help='アップロードするファイルのパス')
    parser.add_argument('--directory', '-d', help='アップロードするディレクトリのパス')
    
    # アルバム関連の引数
    parser.add_argument('--album', '-a', help='アップロード先のアルバム名')
    
    # バッチ処理関連の引数
    parser.add_argument('--batch-create', action='store_true', help='バッチ作成モード')
    parser.add_argument('--tokens-file', help='アップロードトークンのJSONファイル')
    
    # その他の引数
    parser.add_argument('--token-only', action='store_true', help='アップロードトークンのみを取得')
    parser.add_argument('--verbose', '-v', action='store_true', help='詳細なログを出力')
    
    return parser.parse_args()

def main() -> int:
    """メイン関数

    Returns:
        int: 終了コード（0: 成功, 1: 失敗）
    """
    args = parse_args()
    
    # ログレベルの設定
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    
    # 認証情報の取得
    creds = get_credentials()
    if not creds:
        logger.error("認証に失敗しました")
        return 1
    
    # ファイルリストの作成
    files_to_upload: List[Path] = []
    
    # コマンドライン引数で指定されたファイルを追加
    for file_path in args.files:
        path = Path(file_path)
        if path.exists():
            files_to_upload.append(path)
        else:
            logger.warning(f"ファイルが見つかりません: {path}")
    
    # ディレクトリが指定された場合は、その中のメディアファイルを追加
    if args.directory:
        dir_path = Path(args.directory)
        if dir_path.exists() and dir_path.is_dir():
            files_to_upload.extend(find_media_files(dir_path))
        else:
            logger.warning(f"ディレクトリが見つかりません: {dir_path}")
    
    if not files_to_upload:
        logger.error("アップロードするファイルが指定されていません")
        return 1
    
    # バッチ作成モード
    if args.batch_create:
        if args.tokens_file:
            try:
                with open(args.tokens_file, 'r') as f:
                    import json
                    tokens = json.load(f)
            except Exception as e:
                logger.error(f"トークンファイルの読み込みに失敗: {e}")
                return 1
        else:
            logger.error("バッチ作成モードでは--tokens-fileが必要です")
            return 1
        
        result = batch_create_media_items(tokens, args.album, creds)
        print(json.dumps(result))  # 結果をJSON形式で出力
        return 0
    
    # 通常のアップロードモード
    success_count = 0
    for file_path in files_to_upload:
        result = upload_media(file_path, creds, args.token_only)
        if result:
            success_count += 1
            if args.token_only:
                print(result)  # トークンのみを出力
    
    logger.info(f"アップロード完了: 成功={success_count}, 失敗={len(files_to_upload) - success_count}")
    return 0 if success_count == len(files_to_upload) else 1

if __name__ == '__main__':
    sys.exit(main()) 