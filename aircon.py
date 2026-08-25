# -*- coding: utf-8 -*-
"""
エアコンの操作状態を保持するモジュール。

重要な前提 — 赤外線は一方通行:
    リモコンからエアコンへ信号を送ることはできるが、エアコンの現在の状態を
    読み取る手段は無い。したがってこのモジュールが持っているのは
    「エアコンの実際の状態」ではなく「Piが最後に送った内容」でしかない。
    リモコン本体で直接操作された場合はズレるため、画面表示も
    「最後に送った操作」として見せること。

信号そのものは ir_receiver.py で実機リモコンから学習し、名前を付けて
ir_codes.json に保存しておく (例: 「冷房26度」「暖房22度」「切」)。
このモジュールはその名前を指定して ir_control.IRController に送らせる。
"""
import threading
from datetime import datetime

import config
import ir_codes


# 「電源を切る」操作とみなす名前。これが送られたら停止中と表示する。
_OFF_KEYWORDS = ("切", "停止", "オフ", "off", "OFF")


class AirconController:
    def __init__(self, ir=None):
        self.ir = ir
        self.last_command = None      # 最後に送ったプリセット名
        self.last_sent_at = None      # 最後に送った時刻
        self._lock = threading.Lock()

    def presets(self):
        """ir_codes.jsonに学習済みのプリセット名を返す(カードのボタンになる)。"""
        return ir_codes.names()

    def send(self, name):
        """プリセット名を指定して赤外線を送信する。送れたらTrueを返す。"""
        if self.ir is None:
            print(f"[AIRCON] IRコントローラーが無いので送信できない: {name}")
            return False
        if not self.ir.send_named(name):
            return False
        with self._lock:
            self.last_command = name
            self.last_sent_at = datetime.now()
        return True

    def get(self):
        with self._lock:
            last_command = self.last_command
            last_sent_at = self.last_sent_at
        # 「切」系の操作を最後に送っていれば停止中とみなす。
        # 一度も送っていない場合は不明(None)。
        if last_command is None:
            is_on = None
        else:
            is_on = not any(k in last_command for k in _OFF_KEYWORDS)
        return {
            "last_command": last_command,
            "last_sent_at": last_sent_at,
            "is_on": is_on,
            "presets": self.presets()[: config.AIRCON_CARD_MAX_BUTTONS],
        }


if __name__ == "__main__":
    # 単体テスト用: python3 aircon.py
    from ir_control import IRController

    ir = IRController()
    ac = AirconController(ir)
    print("学習済みプリセット:", ac.presets() or "(まだ無い。ir_receiver.py で学習する)")
    print("状態:", ac.get())
    ir.close()
