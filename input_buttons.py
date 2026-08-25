# -*- coding: utf-8 -*-
"""
タクトスイッチ等の物理ボタンを読み取り、押下をコールバックで通知するモジュール。
main.pyがこれをPCの曲送り/曲戻しに繋ぐ。

配線 (BCM番号):
    ボタンの片側 -> config.BUTTON_PREV_GPIO_PIN (デフォルト GPIO5)
                    config.BUTTON_NEXT_GPIO_PIN (デフォルト GPIO6)
    ボタンのもう片側 -> GND

    Pi内蔵のプルアップを有効にするので外付け抵抗は不要。
    押していない時がHigh、押すとLow(立ち下がり)になる。

    足が4本あるタクトスイッチの場合、同じ側から出ている2本は内部で常に
    繋がっている(押しても離しても導通する)。使うのは向かい合う側から1本ずつで、
    対角の2本を選べば確実。同じ側の2本を使ってしまうとGPIOがGNDに直結され、
    「押しっぱなし」と同じ状態になって一切反応しなくなる。
    このモジュールを単体実行すると、その配線ミスを検出して警告する。

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


class Buttons:
    """{ピン番号: コールバック} を渡すと、押されたときにそれを呼ぶ。

    使用例:
        buttons = Buttons({
            config.BUTTON_PREV_GPIO_PIN: media.previous_track,
            config.BUTTON_NEXT_GPIO_PIN: media.next_track,
        })
        buttons.start()
    """

    def __init__(self, handlers, glitch_filter_us=None, lockout_sec=None):
        self.handlers = dict(handlers)
        self.glitch_filter_us = (
            glitch_filter_us if glitch_filter_us is not None else config.BUTTON_GLITCH_FILTER_US
        )
        self.lockout_sec = (
            lockout_sec if lockout_sec is not None else config.BUTTON_REPEAT_LOCKOUT_SEC
        )

        self.press_counts = {pin: 0 for pin in self.handlers}
        self._last_press_at = {pin: 0.0 for pin in self.handlers}
        self._lock = threading.Lock()
        self._pi = None
        self._callbacks = []

        if HARDWARE_AVAILABLE:
            try:
                pi = pigpio.pi()
                if pi.connected:
                    for pin in self.handlers:
                        pi.set_mode(pin, pigpio.INPUT)
                        pi.set_pull_up_down(pin, pigpio.PUD_UP)
                        pi.set_glitch_filter(pin, self.glitch_filter_us)
                    self._pi = pi
                else:
                    # pigpiod未起動など
                    pi.stop()
            except Exception:
                self._pi = None

    def start(self):
        if self._pi is None:
            return
        for pin in self.handlers:
            # プルアップしているので、押した瞬間 = 立ち下がり
            self._callbacks.append(
                self._pi.callback(pin, pigpio.FALLING_EDGE, self._on_edge)
            )

    def _on_edge(self, gpio, level, tick):
        now = time.monotonic()
        with self._lock:
            # グリッチフィルタをすり抜けた連打・跳ね返りをここでも弾く
            if now - self._last_press_at.get(gpio, 0.0) < self.lockout_sec:
                return
            self._last_press_at[gpio] = now
            self.press_counts[gpio] = self.press_counts.get(gpio, 0) + 1

        handler = self.handlers.get(gpio)
        if handler is not None:
            try:
                handler()
            except Exception as e:
                print(f"[BUTTON] GPIO{gpio} の処理で例外: {e}")

    def read_levels(self):
        """各ピンの今のレベルを {ピン番号: 0または1} で返す(配線確認用)。
        プルアップしているので、押していなければ 1 が正しい。
        押していないのに 0 なら、GPIOがGNDに繋ぎっぱなしになっている
        (タクトスイッチの同じ側の足を2本使っている等)。
        """
        if self._pi is None:
            return {}
        return {pin: self._pi.read(pin) for pin in self.handlers}

    def get(self):
        with self._lock:
            return {
                "press_counts": dict(self.press_counts),
                "available": self._pi is not None,
            }

    def stop(self):
        for cb in self._callbacks:
            try:
                cb.cancel()
            except Exception:
                pass
        self._callbacks = []
        if self._pi is not None:
            try:
                for pin in self.handlers:
                    self._pi.set_glitch_filter(pin, 0)
                self._pi.stop()
            except Exception:
                pass
            self._pi = None


if __name__ == "__main__":
    # 単体テスト用: python3 input_buttons.py
    names = {
        config.BUTTON_PREV_GPIO_PIN: "曲戻し",
        config.BUTTON_NEXT_GPIO_PIN: "曲送り",
    }
    buttons = Buttons({pin: (lambda n=n: print(f"{n}")) for pin, n in names.items()})
    buttons.start()

    if not buttons.get()["available"]:
        print("ハードウェアが使えない(pigpioが無いか、pigpiodが未起動)")
    else:
        # 押していない状態のレベルを見て、配線ミスを先に指摘する
        levels = buttons.read_levels()
        stuck = [pin for pin, level in levels.items() if level == 0]
        for pin, level in sorted(levels.items()):
            state = "OK (押されていない)" if level else "★ Lowのまま"
            print(f"  GPIO{pin} ({names[pin]}): {state}")
        if stuck:
            print()
            print("押していないのにLowになっているピンがある。配線を確認:")
            print("  ・タクトスイッチの同じ側から出ている2本を使っていないか")
            print("    (同じ側の2本は内部で繋がっているので、常に導通する)")
            print("  ・使うのは向かい合う側から1本ずつ。対角の2本を選べば確実")
            print("  ・GPIOとGNDが直接触れていないか")
            print()
        print("待機中。30秒間、押してみて。")

    try:
        for _ in range(30):
            time.sleep(1)
    finally:
        buttons.stop()
