#!/usr/bin/env python3

import os
import json
import argparse
import mimetypes
import requests
import logging
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import sys

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# APIのスコープを定義
SCOPES = [
    'https://www.googleapis.com/auth/photoslibrary.appendonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly',
    'https://www.googleapis.com/auth/photoslibrary.sharing'
]

# Google Photos APIのエンドポイント
API_BASE_URL = 'https://photoslibrary.googleapis.com/v1'

# 認証情報のパス
CREDENTIALS_DIR = Path.home() / '.google_photos_uploader'
TOKEN_FILE = CREDENTIALS_DIR / 'token.json'
CREDENTIALS_FILE = CREDENTIALS_DIR / 'credentials.json'

def get_credentials():
    """Google API認証情報を取得"""
    creds = None
    
    # 既存のトークンファイルがあるか確認
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_info(
            json.loads(TOKEN_FILE.read_text()), SCOPES)
    
    # 有効な認証情報がない場合
    if not creds or not creds.valid:
        # リフレッシュトークンがある場合は更新
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.error(f"トークンの更新に失敗しました: {e}")
                creds = None
        
        # リフレッシュに失敗または認証情報がない場合は新規認証
        if not creds:
            if not CREDENTIALS_FILE.exists():
                logger.error(f"credentials.jsonファイルが見つかりません: {CREDENTIALS_FILE}")
                sys.exit(1)
                
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES)
            # access_type='offline' と prompt='consent' を設定して refresh_token を取得
            creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        
        # トークンを保存
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())
    
    return creds

def upload_media(file_path, creds, token_only=False):
    """
    メディアファイルをアップロード
    
    Args:
        file_path: メディアファイルのパス
        creds: 認証情報
        token_only: Trueの場合、アップロードトークンのみを返す
    
    Returns:
        token_only=Falseの場合はアップロード成功の有無(bool)
        token_only=Trueの場合はアップロードトークン(str)
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        logger.error(f"ファイルが見つかりません: {file_path}")
        return None if token_only else False
    
    try:
        # ファイルのMIMEタイプを推定
        mime_type = get_mime_type(file_path)
        
        # アップロードリクエストのヘッダーを設定
        headers = {
            'Authorization': f'Bearer {creds.token}',
            'Content-Type': 'application/octet-stream',
            'X-Goog-Upload-Content-Type': mime_type,
            'X-Goog-Upload-Protocol': 'raw',
        }
        
        # ファイルをバイナリモードで開く
        with open(file_path, 'rb') as f:
            file_data = f.read()
        
        # アップロードリクエスト
        logger.info(f"ファイルバイトをアップロード中: {file_path}")
        response = requests.post(API_BASE_URL + '/uploads', headers=headers, data=file_data)
        
        if response.status_code == 200:
            upload_token = response.text
            logger.info(f"アップロードトークン取得: {upload_token[:10]}...")
            
            if token_only:
                return upload_token
            
            # メディアアイテムの作成
            return create_media_item(upload_token, file_path.name, creds)
        else:
            logger.error(f"アップロード失敗: {response.status_code} - {response.text}")
            return None if token_only else False
    
    except Exception as e:
        logger.error(f"アップロード中にエラーが発生: {e}")
        return None if token_only else False

def batch_create_media_items(tokens, album_name, creds):
    """
    複数のメディアアイテムをバッチで作成
    
    Args:
        tokens: アップロードトークンのリスト
        album_name: アルバム名 (オプション)
        creds: 認証情報
    
    Returns:
        dict: 成功と失敗したトークンのリスト
    """
    if not tokens:
        logger.error("アップロードトークンが指定されていません")
        return {"success": [], "failed": []}
    
    try:
        # リクエストヘッダーを設定
        headers = {
            'Authorization': f'Bearer {creds.token}',
            'Content-Type': 'application/json'
        }
        
        # リクエスト本文を作成
        request_body = {
            'newMediaItems': []
        }
        
        # 各トークンについてnewMediaItemを追加
        for token in tokens:
            request_body['newMediaItems'].append({
                'simpleMediaItem': {
                    'uploadToken': token
                }
            })
        
        # アルバムIDを指定（アルバム名がある場合）
        if album_name:
            album_id = get_or_create_album(album_name, creds)
            if album_id:
                request_body['albumId'] = album_id
        
        # バッチ作成リクエストを送信
        logger.info(f"{len(tokens)}個のメディアアイテムをバッチ作成中")
        response = requests.post(API_BASE_URL + '/mediaItems:batchCreate', headers=headers, json=request_body)
        
        if response.status_code == 200:
            response_data = response.json()
            
            # 結果をパース
            success_tokens = []
            failed_tokens = []
            
            for result, token in zip(response_data.get('newMediaItemResults', []), tokens):
                status = result.get('status', {})
                # 成功時は code == 0 または status フィールド自体が省略されるケースがある
                if status.get('code', 0) == 0:
                    success_tokens.append(token)
                else:
                    logger.warning(f"アイテム作成失敗: {status.get('message')}")
                    failed_tokens.append(token)
            
            logger.info(f"バッチ作成完了: 成功={len(success_tokens)}, 失敗={len(failed_tokens)}")
            return {
                "success": success_tokens,
                "failed": failed_tokens
            }
        else:
            logger.error(f"バッチ作成リクエスト失敗: {response.status_code} - {response.text}")
            return {"success": [], "failed": tokens}
    
    except Exception as e:
        logger.error(f"バッチ作成中にエラーが発生: {e}")
        return {"success": [], "failed": tokens}

def create_media_item(upload_token, file_name, creds, album_name=None):
    """メディアアイテムを作成"""
    try:
        # リクエストヘッダーを設定
        headers = {
            'Authorization': f'Bearer {creds.token}',
            'Content-Type': 'application/json'
        }
        
        # リクエスト本文を作成
        request_body = {
            'newMediaItems': [
                {
                    'simpleMediaItem': {
                        'uploadToken': upload_token,
                        'fileName': file_name  # オリジナルのファイル名を保持
                    }
                }
            ]
        }
        
        # アルバムIDを指定（アルバム名がある場合）
        if album_name:
            album_id = get_or_create_album(album_name, creds)
            if album_id:
                request_body['albumId'] = album_id
        
        # メディアアイテム作成リクエストを送信
        logger.info(f"メディアアイテムを作成中: {file_name}")
        response = requests.post(API_BASE_URL + '/mediaItems:batchCreate', headers=headers, json=request_body)
        
        if response.status_code == 200:
            logger.info(f"メディアアイテム作成成功: {file_name}")
            return True
        else:
            logger.error(f"メディアアイテム作成失敗: {response.status_code} - {response.text}")
            return False
    
    except Exception as e:
        logger.error(f"メディアアイテム作成中にエラーが発生: {e}")
        return False

def get_albums(creds, include_non_app_created=True, page_size=50):
    """ユーザーのアルバム一覧を取得
    
    Args:
        creds: 認証情報
        include_non_app_created (bool): Trueの場合、Google フォト UI などで作成されたアルバムも含める
        page_size (int): 1ページあたりの取得件数（最大100）
    Returns:
        list: アルバム情報のリスト
    """
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json'
    }
    
    albums = []
    page_token = None
    
    # excludeNonAppCreatedData=false を明示することで、アプリ外で作成されたアルバムも取得可能
    exclude_param = 'false' if include_non_app_created else 'true'
    
    while True:
        params = {
            'pageSize': str(page_size),
            'excludeNonAppCreatedData': exclude_param
        }
        if page_token:
            params['pageToken'] = page_token
        
        response = requests.get(API_BASE_URL + '/albums', headers=headers, params=params)
        if response.status_code != 200:
            logger.error(f"アルバム一覧取得失敗: {response.status_code} - {response.text}")
            break
        
        data = response.json()
        albums.extend(data.get('albums', []))
        page_token = data.get('nextPageToken')
        if not page_token:
            break
    
    logger.debug(f"取得したアルバム数: {len(albums)}")
    return albums

def create_album(album_name, creds):
    """指定名のアルバムを新規作成しIDを返す"""
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json'
    }
    response = requests.post(
        API_BASE_URL + '/albums',
        headers=headers,
        json={'album': {'title': album_name}}
    )
    if response.status_code == 200:
        album_id = response.json().get('id')
        logger.info(f"新しいアルバムを作成: {album_name}")
        return album_id
    else:
        logger.error(f"アルバム作成失敗: {response.status_code} - {response.text}")
        return None

def add_to_album(album_id, media_ids, creds):
    """既存メディアをアルバムに追加
    Args:
        album_id (str): 追加先のアルバムID
        media_ids (list): 追加するメディアIDのリスト
        creds: 認証情報
    Returns:
        bool: 成功したかどうか
    """
    if not media_ids:
        return True
    headers = {
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json'
    }
    response = requests.post(
        f"{API_BASE_URL}/albums/{album_id}:batchAddMediaItems",
        headers=headers,
        json={'mediaItemIds': media_ids}
    )
    if response.status_code == 200:
        return True
    else:
        logger.error(f"アルバムへの追加失敗: {response.status_code} - {response.text}")
        return False

def get_or_create_album(album_name, creds):
    """アルバムIDを取得または新規作成
    Google フォト UI 等で事前に作られているアルバムも検索対象に含める
    """
    albums = get_albums(creds, include_non_app_created=True)
    for album in albums:
        if album.get('title') == album_name:
            logger.info(f"既存のアルバムを使用: {album_name}")
            return album.get('id')
    
    # 見つからなければ新規作成
    logger.info(f"新しいアルバムを作成: {album_name}")
    return create_album(album_name, creds)

def get_mime_type(file_path):
    """ファイルのMIMEタイプを取得"""
    # MIMEタイプを初期化
    mimetypes.init()
    
    # ファイル拡張子からMIMEタイプを推測
    mime_type, _ = mimetypes.guess_type(file_path)
    
    # 推測できない場合はデフォルト値を使用
    if mime_type is None:
        if file_path.suffix.lower() in ['.jpg', '.jpeg']:
            mime_type = 'image/jpeg'
        elif file_path.suffix.lower() == '.png':
            mime_type = 'image/png'
        elif file_path.suffix.lower() in ['.mp4', '.mov']:
            mime_type = 'video/mp4'
        else:
            mime_type = 'application/octet-stream'
    
    return mime_type

def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description='Google Photosにファイルをアップロードする')
    parser.add_argument('files', metavar='FILE', type=str, nargs='*',
                        help='アップロードするファイルのパス')
    parser.add_argument('--album', type=str, help='アップロード先のアルバム名（オプション）')
    parser.add_argument('--verbose', action='store_true', help='詳細なログを出力する')
    
    # 新しい機能: トークンのみ取得モード
    parser.add_argument('--token-only', action='store_true', help='アップロードトークンのみを返す')
    
    # 新しい機能: バッチ作成モード
    parser.add_argument('--batch-create', action='store_true', help='バッチでメディアアイテムを作成する')
    parser.add_argument('--tokens-file', type=str, help='アップロードトークンのJSONファイル')
    
    args = parser.parse_args()
    
    # 詳細ログモードが指定された場合
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("詳細ログモードが有効です")
    
    try:
        # 認証情報を取得
        creds = get_credentials()
        
        # トークンのみ取得モード
        if args.token_only:
            if len(args.files) != 1:
                logger.error("--token-only モードでは、ちょうど 1 つの FILE を指定してください")
                sys.exit(1)
            # 単一ファイルのトークンを取得して出力
            token = upload_media(args.files[0], creds, token_only=True)
            if token:
                print(token)  # 標準出力にトークンを出力
                sys.exit(0)
            else:
                sys.exit(1)
        
        # バッチ作成モード
        elif args.batch_create and args.tokens_file:
            # トークンファイルを読み込み
            with open(args.tokens_file, 'r') as f:
                tokens = json.load(f)
            
            # バッチ作成を実行
            result = batch_create_media_items(tokens, args.album, creds)
            
            # 結果をJSON形式で標準出力に出力
            print(json.dumps(result))
            
            # 成功したトークンがあれば成功とする
            if result["success"]:
                sys.exit(0)
            else:
                sys.exit(1)
        
        # 通常のアップロードモード
        else:
            # ファイルが指定されていない場合は終了
            if not args.files:
                logger.error("アップロードするファイルを指定してください")
                sys.exit(1)
                
            # アルバムIDを取得（指定された場合）
            album_id = None
            if args.album:
                try:
                    albums = get_albums(creds)
                    for album in albums:
                        if album.get('title') == args.album:
                            album_id = album.get('id')
                            break
                
                    if not album_id:
                        logger.info(f"アルバム '{args.album}' が見つかりません。新しく作成します。")
                        album_id = create_album(args.album, creds)
                        if album_id:
                            logger.debug(f"新しいアルバムが作成されました: ID={album_id}")
                        else:
                            logger.error("アルバムの作成に失敗しました")
                except Exception as error:
                    logger.error(f"アルバム操作中にエラーが発生しました: {error}")
                    return
            
            # ファイルをアップロード
            success_count = 0
            for file_path in args.files:
                if not os.path.exists(file_path):
                    logger.warning(f"ファイルが見つかりません: {file_path}")
                    continue
                
                logger.info(f"アップロード中: {file_path}")
                
                # ファイル情報をログに記録
                if args.verbose:
                    file_size = os.path.getsize(file_path) / (1024 * 1024)  # MBに変換
                    logger.debug(f"ファイル情報: サイズ={file_size:.2f}MB, パス={file_path}")
                
                media_id = upload_media(file_path, creds, token_only=False)
                
                if media_id and album_id:
                    logger.debug(f"メディアID: {media_id}, アルバムID: {album_id}")
                    if add_to_album(album_id, [media_id], creds):
                        logger.info(f"ファイル '{file_path}' をアルバム '{args.album}' にアップロードしました")
                        success_count += 1
                    else:
                        logger.warning(f"ファイル '{file_path}' をアップロードしましたが、アルバムへの追加に失敗しました")
                elif media_id:
                    logger.info(f"ファイル '{file_path}' をアップロードしました")
                    success_count += 1
                else:
                    logger.error(f"ファイル '{file_path}' のアップロードに失敗しました")
            
            logger.info(f"アップロード完了: 成功={success_count}/{len(args.files)}")
            
            # すべて成功したかどうかで終了コードを設定
            if success_count == len(args.files):
                sys.exit(0)
            else:
                sys.exit(1)
    
    except Exception as e:
        logger.error(f"予期せぬエラーが発生しました: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
