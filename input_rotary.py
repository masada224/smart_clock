# -*- coding: utf-8 -*-
"""
ロータリーエンコーダー(EC11等)を読み取り、回転量と押し込みをコールバックで
通知するモジュール。main.pyがこれをPCの音量調整/ミュートに繋ぐ。

配線 (BCM番号):
    エンコーダー   Pi
      A (CLK)  -> config.ROTARY_A_GPIO_PIN  (デフォルト GPIO23)
      B (DT)   -> config.ROTARY_B_GPIO_PIN  (デフォルト GPIO24)
      SW       -> config.ROTARY_SW_GPIO_PIN (デフォルト GPIO25)
      GND      -> GND
      + (VCC)  -> 3.3V ※モジュール基板の場合。素の部品なら不要

    3本ともPi内蔵のプルアップを有効にするので、外付け抵抗は不要
    (エンコーダーのコモンをGNDに落とす一般的な配線を想定)。

回転の読み取り方:
    A相とB相は90度ずれた矩形波(直交信号)を出す。片方だけを見ると
    チャタリングで誤カウントするため、A/B 2bitの状態遷移を表で判定する
    「グレイコードデコード」を使う。EC11系はデテント1クリックにつき
    4回状態が変化するので、config.ROTARY_STEPS_PER_DETENT 回分を
    まとめて1ステップとして通知する。

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
    # その場合は何も検知しないダミーモードで動作する。
    HARDWARE_AVAILABLE = False


# 直交信号の状態遷移テーブル。
# キーは (前回のAB, 今回のAB) を 4bit にまとめた値、値は +1(時計回り)/-1(反時計回り)。
# 表に無い遷移(2bit同時変化 = ノイズや取りこぼし)は0として無視する。
_TRANSITIONS = {
    0b0001: +1, 0b0111: +1, 0b1110: +1, 0b1000: +1,
    0b0010: -1, 0b1011: -1, 0b1101: -1, 0b0100: -1,
}


class RotaryEncoder:
    """回転すると on_rotate(delta) を、押すと on_press() を呼ぶ。
    deltaは +1 が時計回り、-1 が反時計回り(1デテントあたり±1)。
    コールバックはpigpioのコールバックスレッドから呼ばれるため、
    重い処理はしないこと(シリアル送信程度なら問題ない)。
    """

    def __init__(self, on_rotate=None, on_press=None,
                 a_pin=None, b_pin=None, sw_pin=None):
        self.a_pin = a_pin if a_pin is not None else config.ROTARY_A_GPIO_PIN
        self.b_pin = b_pin if b_pin is not None else config.ROTARY_B_GPIO_PIN
        self.sw_pin = sw_pin if sw_pin is not None else config.ROTARY_SW_GPIO_PIN
        self.on_rotate = on_rotate
        self.on_press = on_press

        self.position = 0          # 起動時からの累積ステップ数(デバッグ/表示用)
        self._lock = threading.Lock()
        self._last_state = 0       # 直前のAB 2bit
        self._sub_steps = 0        # デテント未満の端数
        self._last_press_at = 0.0
        self._pi = None
        self._callbacks = []

        if HARDWARE_AVAILABLE:
            try:
                pi = pigpio.pi()
                if pi.connected:
                    for pin in (self.a_pin, self.b_pin, self.sw_pin):
                        pi.set_mode(pin, pigpio.INPUT)
                        pi.set_pull_up_down(pin, pigpio.PUD_UP)
                    pi.set_glitch_filter(self.a_pin, config.ROTARY_GLITCH_FILTER_US)
                    pi.set_glitch_filter(self.b_pin, config.ROTARY_GLITCH_FILTER_US)
                    # 押しボタンは接点が暴れやすいので長めに除去する
                    pi.set_glitch_filter(self.sw_pin, config.BUTTON_GLITCH_FILTER_US)
                    self._pi = pi
                    self._last_state = self._read_state()
                else:
                    # pigpiod未起動など
                    pi.stop()
            except Exception:
                self._pi = None

    def _read_state(self):
        """A/B相の現在値を 2bit にまとめて返す。"""
        return (self._pi.read(self.a_pin) << 1) | self._pi.read(self.b_pin)

    def start(self):
        if self._pi is None:
            return
        self._callbacks = [
            self._pi.callback(self.a_pin, pigpio.EITHER_EDGE, self._on_ab_edge),
            self._pi.callback(self.b_pin, pigpio.EITHER_EDGE, self._on_ab_edge),
            # プルアップしているので、押した瞬間 = 立ち下がり
            self._pi.callback(self.sw_pin, pigpio.FALLING_EDGE, self._on_switch_edge),
        ]

    def _on_ab_edge(self, gpio, level, tick):
        if level > 1:  # ウォッチドッグ
            return
        state = self._read_state()
        with self._lock:
            direction = _TRANSITIONS.get((self._last_state << 2) | state, 0)
            self._last_state = state
            if direction == 0:
                return
            self._sub_steps += direction

            # デテント1クリック分たまったら通知する
            per_detent = max(1, config.ROTARY_STEPS_PER_DETENT)
            if abs(self._sub_steps) < per_detent:
                return
            delta = int(self._sub_steps / per_detent)
            self._sub_steps -= delta * per_detent
            self.position += delta

        if self.on_rotate is not None:
            self.on_rotate(delta)

    def _on_switch_edge(self, gpio, level, tick):
        now = time.monotonic()
        with self._lock:
            if now - self._last_press_at < config.BUTTON_REPEAT_LOCKOUT_SEC:
                return
            self._last_press_at = now
        if self.on_press is not None:
            self.on_press()

    def get(self):
        with self._lock:
            return {"position": self.position, "available": self._pi is not None}

    def stop(self):
        for cb in self._callbacks:
            try:
                cb.cancel()
            except Exception:
                pass
        self._callbacks = []
        if self._pi is not None:
            try:
                for pin in (self.a_pin, self.b_pin, self.sw_pin):
                    self._pi.set_glitch_filter(pin, 0)
                self._pi.stop()
            except Exception:
                pass
            self._pi = None


if __name__ == "__main__":
    # 単体テスト用: python3 input_rotary.py
    enc = RotaryEncoder(
        on_rotate=lambda d: print(f"回転: {'右' if d > 0 else '左'} ({d:+d})"),
        on_press=lambda: print("押された"),
    )
    enc.start()
    if not enc.get()["available"]:
        print("ハードウェアが使えない(pigpioが無いか、pigpiodが未起動)")
    else:
        print(f"GPIO{enc.a_pin}/{enc.b_pin}/{enc.sw_pin} で待機中。30秒間、回したり押したりしてみて。")
    try:
        for _ in range(30):
            time.sleep(1)
    finally:
        enc.stop()
