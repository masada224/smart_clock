# -*- coding: utf-8 -*-
"""
USB給電のLEDライトバーを、NチャンネルMOSFETのローサイドスイッチで
点灯/消灯・調光(PWM)するモジュール。sensor_pir.pyから人感センサーの
検知結果に応じて呼ばれる。

配線 (BCM番号):
    ライトバーはPi本体からではなく別のUSB電源(充電器/セルフパワーハブ)から
    給電し、GND側だけをMOSFETで切る「ローサイドスイッチ」にする。
    Pi Zero 2W自身の5Vから取るとライトの消費電流でPiが不安定になりやすい。

        USB電源 5V ------------------+
                                     |
                                 ライトバー
                                     |
        config.LIGHT_GPIO_PIN --[220Ω]--+-- MOSFETゲート
                                        |
                                     [10kΩ]      MOSFETドレイン --+
                                        |                          |
        Pi GND ---------------------- 共通GND -- MOSFETソース -----+
                                                    (USB電源のGNDとも必ず繋ぐ)

    ・MOSFETは3.3Vのゲート電圧で十分オンになる「ロジックレベル品」を選ぶこと
      (AO3400 / IRLML2502 など)。よく売られているIRF520モジュールは
      ロジックレベルではないため3.3V駆動では十分にオンにならず発熱する。
    ・ゲートの10kΩプルダウンは必須。Piの起動中GPIOは不定(ハイインピーダンス)
      になるため、これが無いと起動時にライトが勝手に光ることがある。
    ・LEDは誘導性負荷ではないのでフライバックダイオードは不要。

PWM調光について:
    LEDと抵抗だけの素直なライトバーなら問題なく調光できる。ただしタッチ調光
    などの制御回路を内蔵した製品はPWMで誤動作することがある。その場合は
    config.LIGHT_FADE_SEC = 0 かつ config.LIGHT_BRIGHTNESS = 1.0 にして、
    実質ON/OFFのみで使うとよい。

pigpioデーモン (Raspberry Pi実機側の前提):
    sudo systemctl enable --now pigpiod
"""
import threading
import time

import config

try:
    import pigpio

    HARDWARE_AVAILABLE = True
except ImportError:
    # Raspberry Pi以外(開発PC)ではimportに失敗するので、
    # その場合は明るさの変化をコンソールに出力するだけのモードで動作する。
    HARDWARE_AVAILABLE = False


# PWMの分解能。デフォルトの255段階だとフェードで段が見えるため広げる。
_PWM_RANGE = 1000


class LightController:
    def __init__(self, gpio_pin=None, pwm_freq_hz=None, fade_sec=None):
        self.gpio_pin = gpio_pin if gpio_pin is not None else config.LIGHT_GPIO_PIN
        self.pwm_freq_hz = pwm_freq_hz if pwm_freq_hz is not None else config.LIGHT_PWM_FREQ_HZ
        self.fade_sec = fade_sec if fade_sec is not None else config.LIGHT_FADE_SEC

        self.brightness = 0.0     # 現在の明るさ (0.0〜1.0)
        self._lock = threading.Lock()
        self._pi = None
        self._fade_thread = None
        self._fade_cancel = threading.Event()

        if HARDWARE_AVAILABLE:
            try:
                pi = pigpio.pi()
                if pi.connected:
                    pi.set_mode(self.gpio_pin, pigpio.OUTPUT)
                    pi.set_PWM_range(self.gpio_pin, _PWM_RANGE)
                    pi.set_PWM_frequency(self.gpio_pin, self.pwm_freq_hz)
                    pi.set_PWM_dutycycle(self.gpio_pin, 0)
                    self._pi = pi
                else:
                    # pigpiod未起動など -> フォールバック(コンソール出力)扱いにする
                    pi.stop()
            except Exception:
                self._pi = None

    # ---- 内部: 実際にPWMを出す ----
    def _apply(self, brightness):
        brightness = max(0.0, min(1.0, brightness))
        with self._lock:
            self.brightness = brightness
        if self._pi is not None:
            try:
                self._pi.set_PWM_dutycycle(self.gpio_pin, int(brightness * _PWM_RANGE))
            except Exception:
                pass

    def _cancel_fade(self):
        """進行中のフェードを止める(新しい指示が来たとき用)。"""
        if self._fade_thread is not None and self._fade_thread.is_alive():
            self._fade_cancel.set()
            self._fade_thread.join(timeout=1.0)
        self._fade_cancel.clear()
        self._fade_thread = None

    def _fade_worker(self, start, target, duration_sec):
        started_at = time.monotonic()
        while not self._fade_cancel.is_set():
            elapsed = time.monotonic() - started_at
            if elapsed >= duration_sec:
                break
            ratio = elapsed / duration_sec
            self._apply(start + (target - start) * ratio)
            time.sleep(1.0 / 60)
        if not self._fade_cancel.is_set():
            self._apply(target)

    # ---- 公開API ----
    def set_brightness(self, brightness, fade_sec=None):
        """明るさ(0.0〜1.0)を変更する。fade_secを指定するとその時間をかけて変化させる。"""
        brightness = max(0.0, min(1.0, brightness))
        fade_sec = self.fade_sec if fade_sec is None else fade_sec

        self._cancel_fade()
        with self._lock:
            start = self.brightness
        if fade_sec <= 0 or start == brightness:
            self._apply(brightness)
            return

        self._fade_thread = threading.Thread(
            target=self._fade_worker, args=(start, brightness, fade_sec), daemon=True
        )
        self._fade_thread.start()

    def on(self, brightness=None, fade_sec=None):
        target = brightness if brightness is not None else config.LIGHT_BRIGHTNESS
        self.set_brightness(target, fade_sec=fade_sec)
        if self._pi is None:
            print(f"[LIGHT] 点灯(ハードウェア未接続): 明るさ {target:.0%}")

    def off(self, fade_sec=None):
        self.set_brightness(0.0, fade_sec=fade_sec)
        if self._pi is None:
            print("[LIGHT] 消灯(ハードウェア未接続)")

    def get(self):
        with self._lock:
            return {
                "brightness": self.brightness,
                "is_on": self.brightness > 0.0,
                "available": self._pi is not None,
            }

    def close(self):
        self._cancel_fade()
        self._apply(0.0)
        if self._pi is not None:
            try:
                self._pi.set_PWM_dutycycle(self.gpio_pin, 0)
                self._pi.stop()
            except Exception:
                pass
            self._pi = None


if __name__ == "__main__":
    # 単体テスト用: python3 light_control.py
    # ゆっくり点灯 -> 半分の明るさ -> 消灯 を一巡する
    light = LightController()
    try:
        print("点灯(フェードあり)")
        light.on()
        time.sleep(1.5)
        print("現在:", light.get())

        print("明るさ50%へ")
        light.set_brightness(0.5)
        time.sleep(1.5)
        print("現在:", light.get())

        print("消灯")
        light.off()
        time.sleep(1.5)
        print("現在:", light.get())
    finally:
        light.close()
