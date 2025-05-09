from flask import Flask, render_template, request, jsonify
import subprocess
import os
import signal
from pathlib import Path
import logging
import platform
import atexit
import psutil
import json
import time

# アプリケーションのルートディレクトリを設定
APP_ROOT = Path(__file__).parent
TEMPLATE_DIR = APP_ROOT / 'templates'
STATIC_DIR = APP_ROOT / 'static'

app = Flask(__name__,
           template_folder=str(TEMPLATE_DIR),
           static_folder=str(STATIC_DIR))

# 必要なディレクトリとファイルのパスを設定
CONFIG_DIR = Path.home() / '.google_photos_uploader'
LOG_FILE = CONFIG_DIR / 'app.log'
UPLOADER_LOG = CONFIG_DIR / 'uploader.log'
PROGRESS_FILE = CONFIG_DIR / 'upload_progress.json'
CREDENTIALS_FILE = CONFIG_DIR / 'credentials.json'

# 必要なディレクトリとファイルを作成
def setup_directories():
    """必要なディレクトリとファイルを作成する"""
    try:
        # 設定ディレクトリを作成
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        # ログファイルを作成（存在しない場合）
        LOG_FILE.touch(exist_ok=True)
        UPLOADER_LOG.touch(exist_ok=True)
        
        # 進捗ファイルを作成（存在しない場合）
        if not PROGRESS_FILE.exists():
            with open(PROGRESS_FILE, 'w') as f:
                json.dump({}, f)
        
        # credentials.jsonの存在確認
        if not CREDENTIALS_FILE.exists():
            logging.warning("credentials.jsonが見つかりません。Google認証の設定が必要です。")
            logging.warning("Google Cloud Consoleから認証情報をダウンロードし、~/.google_photos_uploader/credentials.jsonに配置してください。")
        
        logging.info("必要なディレクトリとファイルの作成が完了しました")
    except Exception as e:
        logging.error(f"ディレクトリとファイルの作成中にエラーが発生しました: {e}")
        raise

# アプリケーション起動時にディレクトリをセットアップ
setup_directories()

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()  # 標準出力にもログを出力
    ]
)
logger = logging.getLogger(__name__)

def cleanup():
    """アプリケーション終了時に実行される関数"""
    try:
        # auto_uploader.pyのプロセスを停止
        subprocess.run(['pkill', '-f', 'python.*auto_uploader.py'], check=False)
        # slideshow.pyのプロセスを停止
        subprocess.run(['pkill', '-f', 'python.*slideshow.py'], check=False)
        logger.info('全プロセスを停止しました')
    except Exception as e:
        logger.error(f'プロセス停止中にエラーが発生しました: {e}')

# 終了時の処理を登録
atexit.register(cleanup)

# プロセスが実行中かどうかをチェックする関数
def is_process_running(process_name):
    """指定された名前のプロセスが実行中かどうかをチェックする"""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            if process_name in ' '.join(proc.info['cmdline'] or []):
                return True
        return False
    except Exception as e:
        logger.error(f"プロセスチェック中にエラーが発生しました: {e}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_upload', methods=['POST'])
def start_upload():
    try:
        data = request.get_json()
        album_name = data.get('album_name', 'Photo Uploader')
        watch = data.get('watch', True)
        interval = data.get('interval', 60)
        slideshow = data.get('slideshow', True)
        fullscreen = data.get('fullscreen', True)
        all_photos = data.get('all_photos', False)
        current_only = data.get('current_only', False)
        slideshow_interval = data.get('slideshow_interval', 5)
        random = data.get('random', False)
        no_pending = data.get('no_pending', False)
        verbose = data.get('verbose', False)
        
        # auto_uploader.pyのパスを取得
        uploader_script = Path(__file__).parent / "auto_uploader.py"
        
        # コマンドを構築
        command = ['python3', str(uploader_script)]
        
        # オプションを追加
        if album_name:
            command.extend(['--album', album_name])
        if watch:
            command.append('--watch')
        if interval != 60:  # デフォルト値と異なる場合のみ追加
            command.extend(['--interval', str(interval)])
        if slideshow:
            command.append('--slideshow')
        if not fullscreen:
            command.append('--no-fullscreen')
        if all_photos:
            command.append('--all-photos')
        if current_only:
            command.append('--current-only')
        if slideshow_interval != 5:  # デフォルト値と異なる場合のみ追加
            command.extend(['--slideshow-interval', str(slideshow_interval)])
        if random:
            command.append('--random')
        if no_pending:
            command.append('--no-pending')
        if verbose:
            command.append('--verbose')
        
        # バックグラウンドで実行
        subprocess.Popen(command)
        
        return jsonify({'status': 'success', 'message': '起動中'})
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/stop_upload', methods=['POST'])
def stop_upload():
    try:
        # 実行中のプロセスを終了
        os.system("pkill -f auto_uploader.py")
        os.system("pkill -f slideshow.py")  # スライドショーのプロセスも停止
        
        # 進捗ファイルを削除
        progress_path = Path.home() / '.google_photos_uploader' / 'upload_progress.json'
        if progress_path.exists():
            try:
                os.remove(progress_path)
                logger.info("停止操作により進捗ファイルを削除しました")
            except Exception as e:
                logger.error(f"進捗ファイルの削除に失敗しました: {e}")
                
        return jsonify({'status': 'success', 'message': '停止しました'})
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/unmount_sd', methods=['POST'])
def unmount_sd():
    try:
        # プラットフォームに応じたアンマウントコマンドを実行
        if platform.system() == 'Darwin':  # macOS
            subprocess.run(['diskutil', 'unmount', '/Volumes/PHOTO_UPLOAD_SD'], check=True)
            message = 'SDカードをアンマウントしました'
        elif platform.system() == 'Linux':
            # Linuxの場合、ユーザー名を取得
            user = os.environ.get('USER', 'user')
            mount_point = f'/media/{user}/PHOTO_UPLOAD_SD'
            if not os.path.exists(mount_point):
                mount_point = '/media/PHOTO_UPLOAD_SD'
            subprocess.run(['umount', mount_point], check=True)
            message = 'SDカードをアンマウントしました'
        elif platform.system() == 'Windows':
            # Windowsの場合は、ドライブレターを探してアンマウント
            import win32api
            drives = win32api.GetLogicalDriveStrings().split('\000')[:-1]
            for drive in drives:
                try:
                    volume_name = win32api.GetVolumeInformation(drive)[0]
                    if volume_name == 'PHOTO_UPLOAD_SD':
                        subprocess.run(['eject', drive], check=True)
                        message = 'SDカードをアンマウントしました'
                        break
                except:
                    continue
            else:
                message = 'SDカードが見つかりません'
        else:
            message = 'このプラットフォームではSDカードのアンマウントをサポートしていません'
        
        return jsonify({'message': message})
    except subprocess.CalledProcessError as e:
        return jsonify({'message': f'アンマウント中にエラーが発生しました: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'message': f'予期せぬエラーが発生しました: {str(e)}'}), 500

@app.route('/get_log')
def get_log():
    try:
        log_file = Path.home() / '.google_photos_uploader' / 'uploader.log'
        if not log_file.exists():
            return jsonify({'logs': []})
        
        # 最新の100行を取得
        with open(log_file, 'r', encoding='utf-8') as f:
            logs = f.readlines()[-100:]
        
        # 空行を削除し、各行の末尾の改行を削除
        logs = [log.strip() for log in logs if log.strip()]
        
        return jsonify({'logs': logs})
    except Exception as e:
        logger.error(f"ログの取得中にエラーが発生しました: {e}")
        return jsonify({'logs': [f"ログの取得中にエラーが発生しました: {str(e)}"]})

@app.route('/check_status', methods=['GET'])
def check_status():
    """現在のアップロードやスライドショーの状態を取得する"""
    try:
        uploader_running = is_process_running('auto_uploader.py')
        slideshow_running = is_process_running('slideshow.py') or is_process_running('album_slideshow.py')
        
        return jsonify({
            'uploader_running': uploader_running,
            'slideshow_running': slideshow_running
        })
    except Exception as e:
        logger.error(f"ステータスチェック中にエラーが発生しました: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_albums', methods=['GET'])
def get_albums():
    """Google Photosのアルバムリストを取得する"""
    try:
        # album_slideshow.pyのパスを取得
        slideshow_script = Path(__file__).parent / "album_slideshow.py"
        
        # アルバムリスト取得コマンドを実行
        result = subprocess.run(
            ['python3', str(slideshow_script), '--list-albums-only'],
            capture_output=True,
            text=True,
            check=True
        )
        
        # JSONとして解析
        albums = json.loads(result.stdout)
        return jsonify(albums)
    except subprocess.CalledProcessError as e:
        logger.error(f"アルバムリスト取得中にエラーが発生しました: {e}")
        return jsonify({'error': f"アルバムリスト取得中にエラーが発生しました: {e.stderr}"}), 500
    except Exception as e:
        logger.error(f"アルバムリスト取得中にエラーが発生しました: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/start_slideshow', methods=['POST'])
def start_slideshow():
    try:
        # 現在のプロセス状態をチェック
        uploader_running = is_process_running('auto_uploader.py')
        slideshow_running = is_process_running('slideshow.py') or is_process_running('album_slideshow.py')
        
        if uploader_running:
            return jsonify({'status': 'error', 'message': 'アップロードが実行中です。先に停止してください。'}), 400
        
        if slideshow_running:
            return jsonify({'status': 'error', 'message': 'スライドショーは既に実行中です。'}), 400
            
        data = request.get_json()
        album_name = data.get('album_name', '')
        interval = data.get('interval', 5)
        random = data.get('random', False)
        fullscreen = data.get('fullscreen', True)
        verbose = data.get('verbose', False)
        
        # album_slideshow.pyのパスを取得
        slideshow_script = Path(__file__).parent / "album_slideshow.py"
        
        # コマンドを構築
        command = ['python3', str(slideshow_script)]
        
        # オプションを追加
        if album_name:
            command.extend(['--album', album_name])
            command.append('--exact-match')  # 完全一致のアルバム名が必要なオプションを追加
        
        if interval != 5:  # デフォルト値と異なる場合のみ追加
            command.extend(['--interval', str(interval)])
        if random:
            command.append('--random')
        if fullscreen:
            command.append('--fullscreen')
        if verbose:
            command.append('--verbose')
        
        # バックグラウンドで実行
        subprocess.Popen(command)
        
        return jsonify({'status': 'success', 'message': 'スライドショーを起動中'})
    except Exception as e:
        logger.error(f"スライドショー起動中にエラーが発生しました: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/stop_slideshow', methods=['POST'])
def stop_slideshow():
    try:
        # スライドショープロセスを確実に終了
        os.system("pkill -f 'slideshow.py|album_slideshow.py'")
        # 念のため少し待機
        time.sleep(1)
        # プロセスが残っていないか確認
        if is_process_running('slideshow.py') or is_process_running('album_slideshow.py'):
            # より強力な終了シグナルを送信
            os.system("pkill -9 -f 'slideshow.py|album_slideshow.py'")
        
        return jsonify({'status': 'success', 'message': 'スライドショーを停止しました'})
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/test')
def test():
    return render_template('test.html')

# Flaskのアクセスログを無効化
logging.getLogger('werkzeug').setLevel(logging.ERROR)

if __name__ == '__main__':
    # 静的ファイルのパスを確認
    if not STATIC_DIR.exists():
        logging.error(f"静的ファイルディレクトリが見つかりません: {STATIC_DIR}")
    if not TEMPLATE_DIR.exists():
        logging.error(f"テンプレートディレクトリが見つかりません: {TEMPLATE_DIR}")
    
    # デバッグモードで起動
    app.run(host='0.0.0.0', port=5000, debug=True) 