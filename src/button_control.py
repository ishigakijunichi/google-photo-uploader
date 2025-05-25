#!/usr/bin/env python3
import time
import lgpio
import requests
import threading
from pathlib import Path
import logging

# GPIO設定
LED_PIN = 5      # Grove Base Hat D5ポートのLEDピン
BUTTON_PIN = 6   # Grove Base Hat D5ポートのボタンピン

# APIエンドポイント
API_BASE = "http://localhost:8080"
STATUS_ENDPOINT = f"{API_BASE}/check_status"
START_UPLOAD_ENDPOINT = f"{API_BASE}/start_upload"
STOP_UPLOAD_ENDPOINT = f"{API_BASE}/stop_upload"
STOP_SLIDESHOW_ENDPOINT = f"{API_BASE}/stop_slideshow"

# APIリクエストのタイムアウト値（秒）
API_TIMEOUT = 10

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# LEDの状態
LED_OFF = 0
LED_ON = 1
LED_BLINK = 2

class LEDController:
    def __init__(self, gpio_handler, led_pin):
        self.h = gpio_handler
        self.led_pin = led_pin
        self.current_state = LED_OFF
        self.blink_thread = None
        self.stop_blink = threading.Event()
    
    def set_state(self, state):
        """LEDの状態を設定する"""
        if state == self.current_state:
            return
            
        self.current_state = state
        
        # 点滅中なら停止
        if self.blink_thread and self.blink_thread.is_alive():
            self.stop_blink.set()
            self.blink_thread.join()
            self.stop_blink.clear()
        
        if state == LED_OFF:
            lgpio.gpio_write(self.h, self.led_pin, 0)
            logger.debug("LED: OFF")
        elif state == LED_ON:
            lgpio.gpio_write(self.h, self.led_pin, 1)
            logger.debug("LED: ON")
        elif state == LED_BLINK:
            self.blink_thread = threading.Thread(target=self._blink)
            self.blink_thread.daemon = True
            self.blink_thread.start()
            logger.debug("LED: BLINK")
    
    def _blink(self):
        """LEDを点滅させる"""
        while not self.stop_blink.is_set():
            lgpio.gpio_write(self.h, self.led_pin, 1)
            time.sleep(0.5)
            if self.stop_blink.is_set():
                break
            lgpio.gpio_write(self.h, self.led_pin, 0)
            time.sleep(0.5)
    
    def cleanup(self):
        """リソースを解放する"""
        if self.blink_thread and self.blink_thread.is_alive():
            self.stop_blink.set()
            self.blink_thread.join(timeout=1.0)
        lgpio.gpio_write(self.h, self.led_pin, 0)

def get_app_status():
    """アプリケーションの状態を取得する"""
    try:
        response = requests.get(STATUS_ENDPOINT, timeout=API_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            return data
        return {"uploader_running": False, "slideshow_running": False}
    except requests.exceptions.RequestException as e:
        logger.error(f"ステータス取得エラー: {e}")
        return {"uploader_running": False, "slideshow_running": False}

def start_upload():
    """アップロードを開始する"""
    try:
        data = {
            "album_name": "Photo Uploader",
            "slideshow": True,
            "fullscreen": True,
            "random": False,
            "slideshow_interval": 5,
            "bgm": False
        }
        response = requests.post(START_UPLOAD_ENDPOINT, json=data, timeout=API_TIMEOUT)
        logger.info(f"アップロード開始: {response.status_code} {response.text if response.text else ''}")
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        logger.error(f"アップロード開始エラー: {e}")
        return False

def stop_all():
    """すべての処理を停止する"""
    try:
        # アップローダーを停止
        upload_response = requests.post(STOP_UPLOAD_ENDPOINT, timeout=API_TIMEOUT)
        logger.info(f"アップロード停止: {upload_response.status_code}")
        
        # スライドショーも停止
        slideshow_response = requests.post(STOP_SLIDESHOW_ENDPOINT, timeout=API_TIMEOUT)
        logger.info(f"スライドショー停止: {slideshow_response.status_code}")
        
        return upload_response.status_code == 200 or slideshow_response.status_code == 200
    except requests.exceptions.RequestException as e:
        logger.error(f"停止エラー: {e}")
        return False

def main():
    # GPIOハンドラの初期化
    h = lgpio.gpiochip_open(0)
    
    # ピンのセットアップ
    lgpio.gpio_claim_output(h, LED_PIN)
    lgpio.gpio_claim_input(h, BUTTON_PIN, lgpio.SET_PULL_UP)
    
    # LED制御クラスの初期化
    led_controller = LEDController(h, LED_PIN)
    
    # ボタンの状態を追跡
    last_button_state = 1  # ボタンの前回の状態（プルアップのため、デフォルトは1）
    
    logger.info("LEDボタン制御を開始します...")
    logger.info("- ボタンを押すとアップロード開始/停止を切り替えます")
    logger.info("- LEDの状態: 消灯=待機中, 点滅=アップロード中, 点灯=スライドショーのみ")
    logger.info("Ctrl+Cで終了します")
    
    try:
        while True:
            # アプリの状態を確認
            status = get_app_status()
            uploader_running = status.get("uploader_running", False)
            slideshow_running = status.get("slideshow_running", False)
            
            # LEDの状態を更新
            if uploader_running:
                led_controller.set_state(LED_BLINK)
            elif slideshow_running:
                led_controller.set_state(LED_ON)
            else:
                led_controller.set_state(LED_OFF)
            
            # ボタンの状態を読み取る
            button_state = lgpio.gpio_read(h, BUTTON_PIN)
            
            # ボタンが押された瞬間（1→0の変化）を検出
            if button_state == 0 and last_button_state == 1:
                logger.info("ボタンが押されました")
                
                if uploader_running or slideshow_running:
                    logger.info("停止処理を実行します...")
                    stop_all()
                else:
                    logger.info("アップロード開始処理を実行します...")
                    start_upload()
                
                # ボタンのチャタリング防止のため少し待機
                time.sleep(0.5)
            
            last_button_state = button_state
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        logger.info("\n終了します")
    finally:
        # リソースの解放
        led_controller.cleanup()
        lgpio.gpio_free(h, LED_PIN)
        lgpio.gpio_free(h, BUTTON_PIN)
        lgpio.gpiochip_close(h)

if __name__ == "__main__":
    main() 