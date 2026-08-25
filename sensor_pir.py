# -*- coding: utf-8 -*-
"""
PIR人感センサー(HC-SR501等)を監視し、検知結果に応じて照明を自動制御するモジュール。

配線 (BCM番号):
    VCC  -> 5V
    GND  -> GND
    OUT  -> config.PIR_GPIO_PIN (デフォルト GPIO27)

動作:
    バックグラウンドスレッドで一定間隔(config.PIR_POLL_INTERVAL_SEC)ごとに
    センサー状態をポーリングし、
    - 人を検知したら即座に照明ON
    - 最終検知から config.PIR_LIGHT_OFF_DELAY_SEC 秒間 反応が無ければ照明OFF
    にする。

    照明そのものの制御は light_control.LightController が担当する。
    コンストラクタにlightを渡さなかった場合は、点灯/消灯のタイミングを
    コンソールに出力するだけのダミー動作になる(配線前の動作確認用)。
"""
import threading
import time
from datetime import datetime

import config

try:
    from gpiozero import MotionSensor

    HARDWARE_AVAILABLE = True
except (ImportError, NotImplementedError):
    # Raspberry Pi以外(開発PC)ではimportに失敗する、またはピンファクトリが
    # 存在せず失敗するので、その場合は常に「未検知」を返すダミーモードで動作する。
    HARDWARE_AVAILABLE = False


class PIRSensor:
    def __init__(self, gpio_pin=None, light_off_delay_sec=None, light=None):
        self.gpio_pin = gpio_pin if gpio_pin is not None else config.PIR_GPIO_PIN
        self.light_off_delay_sec = (
            light_off_delay_sec
            if light_off_delay_sec is not None
            else config.PIR_LIGHT_OFF_DELAY_SEC
        )
        # on()/off()を持つオブジェクト(light_control.LightController)。
        # Noneならコンソール出力だけのダミー動作にする。
        self.light = light

        self.motion_detected = False
        self.last_detected_at = None
        self.light_on = False

        self._lock = threading.Lock()
        self._running = False
        self._sensor = None

        if HARDWARE_AVAILABLE:
            try:
                self._sensor = MotionSensor(self.gpio_pin)
            except Exception:
                self._sensor = None

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            detected = self._read_motion()
            now = datetime.now()

            with self._lock:
                self.motion_detected = detected
                if detected:
                    self.last_detected_at = now
                last_detected_at = self.last_detected_at
                light_on = self.light_on

            if detected and not light_on:
                self._turn_light_on()
            elif (
                light_on
                and last_detected_at is not None
                and (now - last_detected_at).total_seconds() > self.light_off_delay_sec
            ):
                self._turn_light_off()

            time.sleep(config.PIR_POLL_INTERVAL_SEC)

    def _read_motion(self):
        if self._sensor is not None:
            try:
                return bool(self._sensor.motion_detected)
            except Exception:
                return False
        # 開発環境用ダミー値: 実機センサーが無いので常に「未検知」とする
        return False

    def _turn_light_on(self):
        with self._lock:
            self.light_on = True
        if self.light is not None:
            self.light.on()
        else:
            print("[PIR] 人を検知しました -> 照明ON(ダミー)")

    def _turn_light_off(self):
        with self._lock:
            self.light_on = False
        if self.light is not None:
            self.light.off()
        else:
            print("[PIR] 反応が無いためタイムアウト -> 照明OFF(ダミー)")

    def get(self):
        with self._lock:
            snapshot = {
                "motion_detected": self.motion_detected,
                "last_detected_at": self.last_detected_at,
                "light_on": self.light_on,
            }
        # 照明カードで実際の明るさを表示できるよう、調光中の値も渡す
        snapshot["brightness"] = self.light.get()["brightness"] if self.light else 0.0
        return snapshot


if __name__ == "__main__":
    # 単体テスト用: python3 sensor_pir.py
    s = PIRSensor()
    s.start()
    try:
        for _ in range(30):
            time.sleep(1)
            print(s.get())
    finally:
        s.stop()
