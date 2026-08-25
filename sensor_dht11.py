# -*- coding: utf-8 -*-
"""
DHT11センサーから室温・湿度を読み取るモジュール。

配線 (BCM番号):
    VCC  -> 3.3V or 5V (モジュールによる。基板に3.3Vと明記があれば3.3V)
    GND  -> GND
    DATA -> config.DHT11_GPIO_PIN (デフォルト GPIO4)
    ※ DATA-VCC間に4.7k〜10kΩのプルアップ抵抗を入れると読み取りが安定する
       (基板付きモジュールは大抵内蔵済み)

DHT11は読み取り失敗(タイムアウト)が頻繁に起きるセンサーのため、
バックグラウンドスレッドで一定間隔ごとにリトライしながら読み続ける。
"""
import threading
import time

import config

try:
    import board
    import adafruit_dht

    HARDWARE_AVAILABLE = True
except (ImportError, NotImplementedError):
    # Raspberry Pi以外(開発PC)ではimportに失敗するので、
    # その場合はダミー値を返すモードで動作する。
    HARDWARE_AVAILABLE = False


class DHT11Sensor:
    def __init__(self):
        self.temperature = None
        self.humidity = None
        self._lock = threading.Lock()
        self._running = False
        self._device = None

        if HARDWARE_AVAILABLE:
            try:
                pin = getattr(board, f"D{config.DHT11_GPIO_PIN}")
                self._device = adafruit_dht.DHT11(pin, use_pulseio=False)
            except Exception:
                self._device = None

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False
        if self._device is not None:
            try:
                self._device.exit()
            except Exception:
                pass

    def _loop(self):
        while self._running:
            if self._device is not None:
                try:
                    temp = self._device.temperature
                    hum = self._device.humidity
                    if temp is not None and hum is not None:
                        with self._lock:
                            self.temperature = temp
                            self.humidity = hum
                except RuntimeError:
                    # チェックサムエラー等。DHT11では頻発するので無視して次回に期待する
                    pass
                except Exception:
                    pass
            else:
                # 開発環境用ダミー値
                with self._lock:
                    self.temperature = 26
                    self.humidity = 30
            time.sleep(config.SENSOR_UPDATE_INTERVAL_SEC)

    def get(self):
        with self._lock:
            return {"temperature": self.temperature, "humidity": self.humidity}


if __name__ == "__main__":
    s = DHT11Sensor()
    s.start()
    for _ in range(5):
        time.sleep(3)
        print(s.get())
    s.stop()
