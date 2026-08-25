# -*- coding: utf-8 -*-
"""
USB接続されたPC(Windows等)から送られてくる「現在再生中の楽曲情報」を
シリアル通信で受信するモジュール。

対になるPC側スクリプト:
    usb_media_bridge/pc_sender/win_media_sender.py

通信プロトコル (改行区切りJSON、1行 = 1メッセージ, UTF-8):
    PC -> Pi
        曲が変わった時:
            {"type": "track", "title": "...", "artist": "...", "album": "...",
             "duration_ms": 123456, "artwork_b64": "<base64 PNGバイト列>"}
        再生位置/状態の軽量な更新 (毎秒程度):
            {"type": "status", "status": "playing", "position_ms": 12345,
             "volume": 0.42, "muted": false}
            ※ volume/mutedはPC側でpycawが使える場合のみ付く(省略可)
    Pi -> PC
        {"type": "control", "action": "play_pause" | "next" | "previous"
                                      | "volume_up" | "volume_down" | "toggle_mute",
         "steps": 1}
        ※ stepsはvolume_up/volume_downでのみ使い、ロータリーエンコーダーを
          一気に回した分をまとめて送るためのもの(省略時は1)

Raspberry Pi側の前提:
    USBケーブルでPCと直結し、Pi側をUSB CDC-ACM(シリアル)ガジェットとして
    動作させる(dwc2 + g_serial)。セットアップ手順は
    usb_media_bridge/pi_receiver/README.md を参照。
    通常 /dev/ttyGS0 として認識される
    (FTDI等の一般的なUSBシリアル変換ケーブルを使う場合は /dev/ttyUSB0 等)。
"""
import base64
import io
import json
import threading
import time

import pygame
import serial

import config

# 1行(=1メッセージ)として読み込む最大バイト数。
# pyserialのtimeoutはバイト単位で効くため、区切りの改行が来ないまま
# データが流れ続けると1行が無制限に伸びてメモリを圧迫する。
# アートワークはPC側で150KBに制限されており、base64化しても約200KBなので
# 512KBあれば通常のメッセージが切れることはない。
# 上限を超えた場合は途中で打ち切られ、JSONとして壊れるため破棄される。
# 次の改行から自動的に復帰する。
MAX_LINE_BYTES = 512 * 1024


class USBMedia:
    """widgets.draw_media_panel() が期待する辞書構造を get() で返す。
    play_pause() / next_track() / previous_track() は
    media_bluetooth.BluetoothMedia と同じインターフェースを持つため、
    main.py 側はどちらのクラスを使っても同じコードで動く。
    """

    def __init__(self, port=None, baudrate=None):
        self.port = port or config.USB_MEDIA_SERIAL_PORT
        self.baudrate = baudrate or config.USB_MEDIA_BAUDRATE

        self.title = ""
        self.artist = ""
        self.album = ""
        self.status = "stopped"
        self.position_ms = 0
        self.duration_ms = 0
        self.artwork = None  # pygame.Surface または None
        self.connected = False
        # PC側の音量。pycawが無い環境では送られてこないのでNoneのままになる
        self.volume = None
        self.muted = False

        self._lock = threading.Lock()
        self._running = False
        self._ser = None

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass

    def _ensure_connected(self):
        if self._ser is not None:
            return True
        try:
            self._ser = serial.Serial(self.port, self.baudrate, timeout=1)
            with self._lock:
                self.connected = True
            return True
        except Exception:
            self._ser = None
            with self._lock:
                self.connected = False
            return False

    def _loop(self):
        while self._running:
            if not self._ensure_connected():
                # PCがまだ繋がっていない/ケーブル未接続の場合は少し待って再試行
                time.sleep(2)
                continue
            try:
                line = self._ser.readline(MAX_LINE_BYTES)
                if not line:
                    continue
                self._handle_line(line)
            except (serial.SerialException, OSError):
                # ケーブルが抜けた等 -> 再接続を試みる
                self._close_serial()
                time.sleep(2)
            except Exception:
                pass

    def _close_serial(self):
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None
        with self._lock:
            self.connected = False

    def _handle_line(self, raw_line):
        try:
            text = raw_line.decode("utf-8", errors="ignore").strip()
            if not text:
                return
            msg = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return

        msg_type = msg.get("type")
        if msg_type == "track":
            with self._lock:
                self.title = msg.get("title", "")
                self.artist = msg.get("artist", "")
                self.album = msg.get("album", "")
                self.duration_ms = int(msg.get("duration_ms", 0) or 0)
                self.position_ms = 0
                self.connected = True

            artwork_b64 = msg.get("artwork_b64")
            surface = self._decode_artwork(artwork_b64) if artwork_b64 else None
            with self._lock:
                self.artwork = surface

        elif msg_type == "status":
            with self._lock:
                self.status = msg.get("status", self.status)
                self.position_ms = int(msg.get("position_ms", self.position_ms) or 0)
                # volume/mutedはPC側の対応状況によっては送られてこないため、
                # キーが無い場合は現在値を保つ(0.0と「未対応」を区別する)
                if "volume" in msg and msg["volume"] is not None:
                    self.volume = float(msg["volume"])
                if "muted" in msg:
                    self.muted = bool(msg["muted"])
                self.connected = True

    def _decode_artwork(self, b64_str):
        try:
            raw = base64.b64decode(b64_str)
            surface = pygame.image.load(io.BytesIO(raw))
            if surface.get_alpha() is not None:
                return surface.convert_alpha()
            return surface.convert()
        except Exception:
            return None

    def get(self):
        with self._lock:
            return {
                "title": self.title,
                "artist": self.artist,
                "album": self.album,
                "status": self.status,
                "position_ms": self.position_ms,
                "duration_ms": self.duration_ms,
                "artwork": self.artwork,
                "connected": self.connected,
                "volume": self.volume,
                "muted": self.muted,
            }

    # ---- 再生コントロール ----
    # 物理スイッチ(input_buttons.py)、ロータリーエンコーダー(input_rotary.py)、
    # 画面のタッチ操作から呼ばれ、シリアル経由でPC側の再生/音量を制御する。
    def _send_command(self, action, **extra):
        if self._ser is None:
            return
        try:
            msg = {"type": "control", "action": action}
            msg.update(extra)
            line = json.dumps(msg) + "\n"
            self._ser.write(line.encode("utf-8"))
        except Exception:
            pass

    def play_pause(self):
        self._send_command("play_pause")

    def next_track(self):
        self._send_command("next")

    def previous_track(self):
        self._send_command("previous")

    def volume_up(self, steps=1):
        self._send_command("volume_up", steps=max(1, int(steps)))

    def volume_down(self, steps=1):
        self._send_command("volume_down", steps=max(1, int(steps)))

    def toggle_mute(self):
        self._send_command("toggle_mute")

    def adjust_volume(self, delta):
        """ロータリーエンコーダーの回転量(+1/-1)をそのまま渡すための入口。"""
        if delta > 0:
            self.volume_up(delta)
        elif delta < 0:
            self.volume_down(-delta)


if __name__ == "__main__":
    # 単体テスト用: python3 media_usb.py
    pygame.init()  # pygame.image.load()の利用に必要
    m = USBMedia()
    m.start()
    try:
        for _ in range(60):
            time.sleep(1)
            d = m.get()
            print(
                {k: v for k, v in d.items() if k != "artwork"},
                "artwork=" + ("あり" if d["artwork"] else "なし"),
            )
    finally:
        m.stop()
