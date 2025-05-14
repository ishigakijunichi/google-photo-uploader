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
from datetime import datetime
import socket
import webbrowser

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
SETTINGS_FILE = CONFIG_DIR / 'settings.json'  # 設定ファイルのパスを追加

# ---------------------------------------------
# アップロード開始時刻を保存するためのグローバル変数
# ---------------------------------------------
UPLOAD_START_TIME: datetime | None = None

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

# --------------------------------------------------
# プロセス停止ヘルパー
# --------------------------------------------------

def kill_slideshow_processes(force: bool = False):
    """slideshow.py / album_slideshow.py を確実に停止するヘルパー

    Raspberry Pi OS 環境で ``pkill`` がパターンマッチせず残存するケースが報告されたため、
    psutil でプロセスリストを走査し、Cmdline に対象スクリプト名が含まれるものを
    `SIGTERM`（または `SIGKILL`）で個別に終了させる。

    Args:
        force: True の場合は SIGKILL (-9) を送る。
    """
    try:
        patterns = ["slideshow.py", "album_slideshow.py"]
        sig = signal.SIGKILL if force else signal.SIGTERM

        for proc in psutil.process_iter(["pid", "cmdline"]):
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if any(p in cmdline for p in patterns):
                try:
                    logger.info(f"スライドショープロセス停止: PID={proc.pid} CMD='{cmdline}' (signal={sig})")
                    os.kill(proc.pid, sig)
                except ProcessLookupError:
                    # 既に終了している
                    continue
                except Exception as e:
                    logger.warning(f"PID {proc.pid} の終了に失敗しました: {e}")
    except Exception as e:
        logger.error(f"スライドショープロセス停止中にエラーが発生しました: {e}")

def cleanup():
    """アプリケーション終了時に実行される関数"""
    try:
        # auto_uploader.pyのプロセスを停止
        subprocess.run(['pkill', '-f', 'python.*auto_uploader.py'], check=False)
        # slideshow 関連プロセスを停止（補完として pkill も用いる）
        subprocess.run(['pkill', '-f', 'python.*(slideshow|album_slideshow).py'], check=False)
        kill_slideshow_processes()
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
        # 監視機能は廃止: デフォルトで無効
        watch = data.get('watch', False)
        # ポーリング間隔。0 の場合は監視/ポーリングを行わない
        interval = data.get('interval', 0)
        slideshow = data.get('slideshow', True)
        fullscreen = data.get('fullscreen', True)
        all_photos = data.get('all_photos', False)
        current_only = data.get('current_only', False)
        slideshow_interval = data.get('slideshow_interval', 5)
        random = data.get('random', False)
        no_pending = data.get('no_pending', False)
        verbose = data.get('verbose', False)
        bgm = data.get('bgm', False)
        
        # ---------------------------------------------
        # SDカードの存在を確認
        # ---------------------------------------------
        try:
            from auto_uploader import find_sd_card, DCIM_PATH  # 遅延インポートして依存を最小化
        except ImportError as ie:
            logger.error(f"auto_uploader モジュールの読み込みに失敗しました: {ie}")
            return jsonify({'status': 'error', 'message': '内部エラー: SDカード検出モジュールの読み込みに失敗しました'}), 500

        sd_path = find_sd_card()
        if not sd_path or not (sd_path / DCIM_PATH).exists():
            # SDカードが見つからない
            return jsonify({'status': 'error', 'message': 'SDカードがありません'}), 400

        # 起動時間を記録
        global UPLOAD_START_TIME
        UPLOAD_START_TIME = datetime.now()
        
        # 設定を保存
        settings = {
            'album_name': album_name,
            'watch': watch,
            'interval': interval,
            'slideshow': slideshow,
            'fullscreen': fullscreen,
            'all_photos': all_photos,
            'current_only': current_only,
            'slideshow_interval': slideshow_interval,
            'random': random,
            'no_pending': no_pending,
            'verbose': verbose,
            'bgm': bgm
        }
        save_settings(settings)
        
        # auto_uploader.pyのパスを取得
        uploader_script = Path(__file__).parent / "auto_uploader.py"
        
        # コマンドを構築
        command = ['python3', str(uploader_script)]
        
        # オプションを追加
        if album_name:
            command.extend(['--album', album_name])
        # 監視は使用しないため --watch は付与しない
        # --interval 0 でポーリングを無効化
        command.extend(['--interval', '0'])
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
        if bgm:
            command.append('--bgm')
        
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
        # slideshow 関連プロセスも確実に停止
        pkill_status = os.system("pkill -f '(slideshow|album_slideshow)\.py'")
        logger.debug(f'pkill result code: {pkill_status}')
        kill_slideshow_processes()
        
        # 進捗ファイルを削除
        progress_path = Path.home() / '.google_photos_uploader' / 'upload_progress.json'
        if progress_path.exists():
            try:
                os.remove(progress_path)
                logger.info("停止操作により進捗ファイルを削除しました")
            except Exception as e:
                logger.error(f"進捗ファイルの削除に失敗しました: {e}")
                
        # アップロード開始時刻をリセット
        global UPLOAD_START_TIME
        UPLOAD_START_TIME = None
        
        return jsonify({'status': 'success', 'message': '停止しました'})
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/unmount_sd', methods=['POST'])
def unmount_sd():
    try:
        # ---------------------------------------------
        # SD アンマウント前に関連プロセスを確実に停止
        # ---------------------------------------------
        logger.info("アンマウント前にスライドショー / アップローダーを停止します")

        # 1) slideshow / album_slideshow
        kill_slideshow_processes(force=False)

        # 2) auto_uploader
        os.system("pkill -f auto_uploader.py")

        # 少し待機して確認
        time.sleep(1)
        if (is_process_running('slideshow.py') or is_process_running('album_slideshow.py')):
            logger.warning("SIGTERM でスライドショーが終了しなかったため SIGKILL を送信")
            kill_slideshow_processes(force=True)

        if is_process_running('auto_uploader.py'):
            logger.warning("SIGTERM で auto_uploader が終了しなかったため SIGKILL を送信")
            os.system("pkill -9 -f auto_uploader.py")

        # ---------------------------------------------
        # ここから SD アンマウント処理本体
        # ---------------------------------------------
        message = ''  # アンマウント結果
        # プラットフォームに応じたアンマウントロジック
        if platform.system() == 'Darwin':  # macOS
            # /Volumes 以下を走査し、DCIM フォルダを含むボリュームを探す
            volumes_dir = Path('/Volumes')
            target_volumes = [v for v in volumes_dir.iterdir() if (v / 'DCIM').exists()]
            if not target_volumes:
                # 後方互換: 旧来のボリューム名が存在する場合はそれも対象に
                legacy_path = Path('/Volumes/PHOTO_UPLOAD_SD')
                if legacy_path.exists():
                    target_volumes.append(legacy_path)
            if target_volumes:
                for vol in target_volumes:
                    try:
                        subprocess.run(['diskutil', 'unmount', str(vol)], check=True)
                        message = f'{vol.name} をアンマウントしました'
                        break  # 最初に成功したボリュームで終了
                    except subprocess.CalledProcessError:
                        # 次の候補を試す
                        continue
                else:
                    message = 'DCIM フォルダを含むボリュームのアンマウントに失敗しました'
            else:
                message = 'DCIM フォルダを含むボリュームが見つかりません'
        elif platform.system() == 'Linux':
            # Linuxでは /media/$USER, /media, /mnt, /run/media を探索
            user = os.environ.get('USER', 'user')
            mount_points = [
                Path(f'/media/{user}'),
                Path('/media'),
                Path('/mnt'),
                Path('/run/media'),
                Path(f'/media/{user}/disk')
            ]
            candidate_paths = []
            for base in mount_points:
                if not base.exists():
                    continue
                for p in base.iterdir():
                    if (p / 'DCIM').exists():
                        candidate_paths.append(p)
            if not candidate_paths:
                # 後方互換
                legacy = Path(f'/media/{user}/PHOTO_UPLOAD_SD')
                if legacy.exists():
                    candidate_paths.append(legacy)
                legacy2 = Path('/media/PHOTO_UPLOAD_SD')
                if legacy2.exists():
                    candidate_paths.append(legacy2)
            if candidate_paths:
                for mp in candidate_paths:
                    try:
                        subprocess.run(['umount', str(mp)], check=True)
                        message = f'{mp} をアンマウントしました'
                        break
                    except subprocess.CalledProcessError:
                        continue
                else:
                    message = 'DCIM フォルダを含むマウントポイントのアンマウントに失敗しました'
            else:
                message = 'DCIM フォルダを含むマウントポイントが見つかりません'
        elif platform.system() == 'Windows':
            # Windows向けのアンマウント処理は不要のため未サポート扱い
            message = 'このプラットフォームではSDカードのアンマウントをサポートしていません'
        else:
            message = 'このプラットフォームではSDカードのアンマウントをサポートしていません'
        # 結果を返却
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
        
        # クエリパラメータ all=true ならフィルタを無効化
        all_logs = request.args.get('all', 'false').lower() == 'true'
        
        # 取得する行数を決定
        line_count = 500 if all_logs else 100
        
        # 最新の行を取得
        with open(log_file, 'r', encoding='utf-8') as f:
            logs = f.readlines()[-line_count:]
        
        # 空行を削除し、各行の末尾の改行を削除
        logs = [log.strip() for log in logs if log.strip()]
        
        # 起動時刻以降のログに限定（フィルタ無効時はスキップ）
        if (not all_logs) and UPLOAD_START_TIME is not None:
            filtered_logs = []
            for line in logs:
                try:
                    ts_str = line.split(' - ', 1)[0]
                    log_time = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                    if log_time >= UPLOAD_START_TIME:
                        filtered_logs.append(line)
                except (ValueError, IndexError):
                    filtered_logs.append(line)
            logs = filtered_logs
        
        return jsonify({'logs': logs})
    except Exception as e:
        logger.error(f"ログの取得中にエラーが発生しました: {e}")
        return jsonify({'logs': [f"ログの取得中にエラーが発生しました: {str(e)}"]})

@app.route('/get_console_log')
def get_console_log():
    """コンソールログを取得するエンドポイント"""
    try:
        all_logs = request.args.get('all', 'false').lower() == 'true'
        log_files = [
            Path.home() / '.google_photos_uploader' / 'uploader.log',
            Path.home() / '.google_photos_uploader' / 'slideshow.log'
        ]
        
        line_count = 500 if all_logs else 100
        all_lines = []
        for log_file in log_files:
            if log_file.exists():
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()[-line_count:]
                    lines = [line.strip() for line in lines if line.strip()]
                    all_lines.extend(lines)
        
        if not all_logs:
            # 時刻でソート
            tmp = []
            for line in all_lines:
                try:
                    ts_str = line.split(' - ', 1)[0]
                    log_time = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                    tmp.append((log_time, line))
                except (ValueError, IndexError):
                    tmp.append((datetime.min, line))
            tmp.sort(key=lambda x: x[0], reverse=True)
            all_lines = [t[1] for t in tmp][:line_count]
        
        return jsonify({'logs': all_lines})
    except Exception as e:
        logger.error(f"コンソールログの取得中にエラーが発生しました: {e}")
        return jsonify({'logs': [f"コンソールログの取得中にエラーが発生しました: {str(e)}"]})

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
        bgm = data.get('bgm', False)
        
        # 設定を保存
        settings = {
            'album_name': album_name,
            'interval': interval,
            'random': random,
            'fullscreen': fullscreen,
            'verbose': verbose,
            'bgm': bgm
        }
        save_settings(settings)
        
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
        if bgm:
            command.append('--bgm')
        
        # バックグラウンドで実行
        subprocess.Popen(command)
        
        return jsonify({'status': 'success', 'message': 'スライドショーを起動中'})
    except Exception as e:
        logger.error(f"スライドショー起動中にエラーが発生しました: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/stop_slideshow', methods=['POST'])
def stop_slideshow():
    try:
        # SIGTERM → SIGKILL の順に試行
        kill_slideshow_processes(force=False)

        # 少し待機して残存確認
        time.sleep(1)
        if is_process_running('slideshow.py') or is_process_running('album_slideshow.py'):
            logger.warning('SIGTERM で終了しなかったため SIGKILL を送信します')
            kill_slideshow_processes(force=True)
        
        return jsonify({'status': 'success', 'message': 'スライドショーを停止しました'})
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/test')
def test():
    return render_template('test.html')

@app.route('/get_settings', methods=['GET'])
def get_settings():
    """保存されている設定を取得する"""
    try:
        settings = load_settings()
        return jsonify(settings)
    except Exception as e:
        logger.error(f"設定の取得中にエラーが発生しました: {e}")
        return jsonify({'error': str(e)}), 500

def load_settings():
    """設定ファイルから設定を読み込む"""
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"設定の読み込み中にエラーが発生しました: {e}")
        return {}

def save_settings(settings):
    """設定をファイルに保存する"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        logger.error(f"設定の保存中にエラーが発生しました: {e}")

# --------------------------------------------------
# ネットワーク関連関数
# --------------------------------------------------

def get_ip_address():
    """
    マシンのIPアドレスを取得する
    
    Returns:
        str: IPアドレス。取得できない場合は127.0.0.1
    """
    try:
        # 外部に接続して自分のIPアドレスを確認する方法
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 実際には接続しない
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        logger.error(f"IPアドレスの取得に失敗しました: {e}")
        return '127.0.0.1'  # ローカルホストを返す

def open_browser(url):
    """ブラウザを開く関数"""
    try:
        # Raspberry Pi向けの最適化
        if platform.system() == 'Linux':
            # ユーザーデータディレクトリをホームディレクトリに作成
            user_data_dir = Path.home() / '.google_photos_uploader' / 'browser_data'
            user_data_dir.mkdir(parents=True, exist_ok=True)
            
            # 最適化された起動オプション
            chrome_options = [
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--disable-extensions',
                '--disable-notifications',
                '--disable-infobars',
                '--disable-translate',
                '--disable-features=TranslateUI',
                '--disable-features=site-per-process',
                '--disable-features=IsolateOrigins',
                '--disable-site-isolation-trials',
                '--disable-web-security',
                '--disable-features=BlockInsecurePrivateNetworkRequests',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-features=TranslateUI',
                '--disable-features=site-per-process',
                '--disable-features=IsolateOrigins',
                '--disable-site-isolation-trials',
                '--disable-web-security',
                '--disable-features=BlockInsecurePrivateNetworkRequests',
                f'--user-data-dir={user_data_dir}',
                '--start-maximized',
                '--kiosk',
                url
            ]
            
            # Chromeを起動
            subprocess.Popen(['chromium-browser'] + chrome_options)
        else:
            # その他のプラットフォームでは通常の方法でブラウザを開く
            webbrowser.open(url)
    except Exception as e:
        logger.error(f"ブラウザ起動中にエラーが発生しました: {e}")

# Flaskのアクセスログを無効化
logging.getLogger('werkzeug').setLevel(logging.ERROR)

if __name__ == '__main__':
    # 静的ファイルのパスを確認
    if not STATIC_DIR.exists():
        logging.error(f"静的ファイルディレクトリが見つかりません: {STATIC_DIR}")
    if not TEMPLATE_DIR.exists():
        logging.error(f"テンプレートディレクトリが見つかりません: {TEMPLATE_DIR}")
    
    # IPアドレスを取得
    ip_address = get_ip_address()
    port = 8080
    url = f"http://{ip_address}:{port}"
    
    logger.info(f"アプリケーションを起動します: {url}")
    
    # ブラウザを開く（少し遅延させる）
    import threading
    threading.Timer(2.0, lambda: open_browser(url)).start()
    
    # デバッグモードで起動
    app.run(host='0.0.0.0', port=port, debug=True) 