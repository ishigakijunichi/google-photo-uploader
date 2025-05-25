#!/usr/bin/env python3
import time
import lgpio

# Grove-LED ButtonをD5ポートに接続
# D5ポートは制御信号用
LED_PIN = 5      # LEDのピン
BUTTON_PIN = 6   # ボタンのピン（D5の次のピン）

def main():
    # GPIOハンドラの初期化
    h = lgpio.gpiochip_open(0)
    
    # ピンのセットアップ
    lgpio.gpio_claim_output(h, LED_PIN)  # LED用ピンを出力に設定
    lgpio.gpio_claim_input(h, BUTTON_PIN, lgpio.SET_PULL_UP)  # ボタン用ピンを入力に設定（プルアップ）
    
    print("LEDボタンのテストを開始します...")
    print("・ボタンを押すとLEDが点灯します")
    print("・ボタンを離すとLEDが消灯します")
    print("終了するには Ctrl+C を押してください")
    
    try:
        while True:
            button_state = lgpio.gpio_read(h, BUTTON_PIN)
            if button_state == 0:  # ボタンが押された（プルアップのため0）
                lgpio.gpio_write(h, LED_PIN, 1)  # LEDをオン
                print("ボタンが押されました - LEDオン")
            else:  # ボタンが離された
                lgpio.gpio_write(h, LED_PIN, 0)  # LEDをオフ
                print("ボタンが離されました - LEDオフ")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nテストを終了します")
    finally:
        # リソースの解放
        lgpio.gpio_write(h, LED_PIN, 0)  # LED消灯
        lgpio.gpio_free(h, LED_PIN)
        lgpio.gpio_free(h, BUTTON_PIN)
        lgpio.gpiochip_close(h)

if __name__ == "__main__":
    main() 