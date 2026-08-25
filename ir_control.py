# -*- coding: utf-8 -*-
"""
赤外線(IR)LEDから、エアコン等のリモコン信号(生の波形データ)を送信するモジュール。

配線 (BCM番号):
    IR LED (+ NPNトランジスタ等でのドライブ推奨) -> config.IR_TX_GPIO_PIN (デフォルト GPIO17)

波形データの形式:
    マーク(IR ON)/スペース(IR OFF)の継続時間を交互に並べたマイクロ秒単位のリスト。
    先頭は必ずマークから始まる想定 (例: [3400, 1700, 420, 420, ...])。
    実際のエアコンの信号は ir_receiver.py で学習してir_codes.jsonに保存し、
    send_named() で名前を指定して送信する。本モジュールにはテスト用の
    ダミー波形も残してある。

pigpioデーモン (Raspberry Pi実機側の前提):
    sudo systemctl enable --now pigpiod
"""
import time

import config
import ir_codes

try:
    import pigpio

    HARDWARE_AVAILABLE = True
except ImportError:
    # Raspberry Pi以外(開発PC)ではimportに失敗するので、
    # その場合は「送信したフリ」をコンソール出力するだけのモードで動作する。
    HARDWARE_AVAILABLE = False


# テスト用のダミー波形データ (実際のエアコンの信号ではないプレースホルダー)
# [mark_us, space_us, mark_us, space_us, ...]
_DUMMY_AC_ON_PULSES = [
    3400, 1700,
    420, 420, 420, 420, 420, 1300, 420, 420,
    420, 1300, 420, 1300, 420, 420, 420, 1300,
    420, 420, 420, 420, 420, 1300, 420, 420,
    420, 25000,
]


class IRController:
    """pigpioのwaveform機能を使い、搬送波(config.IR_CARRIER_FREQ_HZ)で
    変調した赤外線パルス列を送信する。今回は送信専用。
    """

    def __init__(self, gpio_pin=None, carrier_freq=None, duty_cycle=None):
        self.gpio_pin = gpio_pin if gpio_pin is not None else config.IR_TX_GPIO_PIN
        self.carrier_freq = carrier_freq if carrier_freq is not None else config.IR_CARRIER_FREQ_HZ
        self.carrier_duty_cycle = (
            duty_cycle if duty_cycle is not None else config.IR_CARRIER_DUTY_CYCLE
        )
        self._pi = None

        if HARDWARE_AVAILABLE:
            try:
                pi = pigpio.pi()
                if pi.connected:
                    pi.set_mode(self.gpio_pin, pigpio.OUTPUT)
                    self._pi = pi
                else:
                    # pigpiod未起動など -> フォールバック(送信したフリ)扱いにする
                    pi.stop()
            except Exception:
                self._pi = None

    def _build_carrier_wave(self, pulses):
        """マーク区間を搬送波のON/OFFパルス列に展開し、スペース区間はLowのまま
        出力するpigpio.pulse()のリストを組み立てる。
        """
        cycle_us = 1_000_000.0 / self.carrier_freq
        on_us = cycle_us * self.carrier_duty_cycle
        off_us = cycle_us - on_us
        gpio_bit = 1 << self.gpio_pin

        wave = []
        for i, duration_us in enumerate(pulses):
            is_mark = (i % 2 == 0)
            if not is_mark:
                wave.append(pigpio.pulse(0, gpio_bit, int(duration_us)))
                continue

            remaining = float(duration_us)
            while remaining > 0:
                this_on = min(on_us, remaining)
                wave.append(pigpio.pulse(gpio_bit, 0, max(1, int(this_on))))
                remaining -= this_on
                if remaining <= 0:
                    break
                this_off = min(off_us, remaining)
                wave.append(pigpio.pulse(0, gpio_bit, max(1, int(this_off))))
                remaining -= this_off
        return wave

    def send(self, pulses, name=""):
        """pulsesを送信する。ハードウェア未接続時はコンソールに「送信したフリ」を出力する。"""
        if not pulses:
            return

        if self._pi is None:
            print(f"[IR] (送信したフリ) {name or '(無名)'}: {len(pulses)}区間")
            return

        try:
            wave = self._build_carrier_wave(pulses)
            self._pi.wave_clear()
            self._pi.wave_add_generic(wave)
            wave_id = self._pi.wave_create()
            self._pi.wave_send_once(wave_id)
            while self._pi.wave_tx_busy():
                time.sleep(0.01)
            self._pi.wave_delete(wave_id)
            print(f"[IR] 送信完了: {name or '(無名)'}")
        except Exception as e:
            print(f"[IR] 送信失敗: {name or '(無名)'} ({e})")

    def send_named(self, name):
        """ir_receiver.pyで学習してir_codes.jsonに保存済みの信号を、
        名前を指定して送信する。未登録ならFalseを返す。
        """
        pulses = ir_codes.load(name)
        if pulses is None:
            print(f"[IR] 未登録の信号: {name} (ir_receiver.py で学習する)")
            return False
        self.send(pulses, name=name)
        return True

    def send_dummy_ac_on(self):
        """動作確認用: ダミーの波形データを送信する。"""
        self.send(_DUMMY_AC_ON_PULSES, name="dummy_ac_on")

    def close(self):
        if self._pi is not None:
            try:
                self._pi.wave_clear()
                self._pi.stop()
            except Exception:
                pass
            self._pi = None


if __name__ == "__main__":
    # 単体テスト用:
    #   python3 ir_control.py            -> ダミー波形を送信(配線の確認用)
    #   python3 ir_control.py 冷房26度    -> ir_receiver.pyで学習済みの信号を送信
    import sys

    ir = IRController()
    try:
        if len(sys.argv) > 1:
            ir.send_named(sys.argv[1])
        else:
            print("学習済み:", ", ".join(ir_codes.names()) or "(まだ無い)")
            ir.send_dummy_ac_on()
    finally:
        ir.close()
