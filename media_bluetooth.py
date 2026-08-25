# -*- coding: utf-8 -*-
"""
ペアリング済みのスマートフォン等から、AVRCP経由で送られてくる再生中の
曲情報(タイトル/アーティスト/アルバム/再生位置)をBlueZのD-Bus API
(org.bluez.MediaPlayer1)から取得するモジュール。

前提:
    - Raspberry Pi をBluetoothスピーカー(A2DPシンク)として動作させ、
      スマートフォン側から音声出力先として接続していること。
    - bluealsa等でA2DP自体の音声再生も別途セットアップしていること
      (本モジュールはメタデータ取得のみを担当し、音声のルーティングは行わない)。

制限事項:
    - AVRCPの標準仕様にアルバムアート(ジャケット画像)は含まれないため、
      本実装ではタイトル/アーティスト/アルバム名のみを表示し、
      アルバムアートはプレースホルダー表示になる。
    - 接続機種やOSによってはTrack情報の項目名が異なる/一部欠落することがある。

必要パッケージ (pipではなくaptを推奨):
    sudo apt install python3-dbus
"""
import threading
import time

import config

try:
    import dbus

    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False

BLUEZ_SERVICE = "org.bluez"
MEDIA_PLAYER_IFACE = "org.bluez.MediaPlayer1"
OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"


class BluetoothMedia:
    def __init__(self):
        self.title = ""
        self.artist = ""
        self.album = ""
        self.status = "stopped"  # playing / paused / stopped / (未接続時は空)
        self.position_ms = 0
        self.duration_ms = 0
        self.connected = False
        self._lock = threading.Lock()
        self._running = False
        self._bus = None
        self._player_path = None

        if DBUS_AVAILABLE:
            try:
                self._bus = dbus.SystemBus()
            except Exception:
                self._bus = None

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _find_player_path(self):
        """BlueZのオブジェクトツリーからMediaPlayer1を実装しているパスを探す。
        端末がAVRCPで接続されるとBlueZが自動的に生成する。
        """
        if self._bus is None:
            return None
        try:
            manager = dbus.Interface(
                self._bus.get_object(BLUEZ_SERVICE, "/"), OBJECT_MANAGER_IFACE
            )
            objects = manager.GetManagedObjects()
            for path, interfaces in objects.items():
                if MEDIA_PLAYER_IFACE in interfaces:
                    return path
        except Exception:
            pass
        return None

    def _loop(self):
        while self._running:
            if self._bus is not None:
                if self._player_path is None:
                    self._player_path = self._find_player_path()

                if self._player_path is not None:
                    try:
                        props = dbus.Interface(
                            self._bus.get_object(BLUEZ_SERVICE, self._player_path),
                            PROPERTIES_IFACE,
                        )
                        track = props.Get(MEDIA_PLAYER_IFACE, "Track")
                        status = props.Get(MEDIA_PLAYER_IFACE, "Status")
                        position = props.Get(MEDIA_PLAYER_IFACE, "Position")
                        with self._lock:
                            self.title = str(track.get("Title", ""))
                            self.artist = str(track.get("Artist", ""))
                            self.album = str(track.get("Album", ""))
                            self.duration_ms = int(track.get("Duration", 0))
                            self.position_ms = int(position)
                            self.status = str(status).lower()
                            self.connected = True
                    except Exception:
                        # 端末が切断された等 -> 再探索させる
                        self._player_path = None
                        with self._lock:
                            self.status = "stopped"
                            self.connected = False
                else:
                    with self._lock:
                        self.connected = False
            time.sleep(config.BT_UPDATE_INTERVAL_SEC)

    def get(self):
        with self._lock:
            return {
                "title": self.title,
                "artist": self.artist,
                "album": self.album,
                "status": self.status,
                "position_ms": self.position_ms,
                "duration_ms": self.duration_ms,
                "connected": self.connected,
                # USBMediaと同じ形を返すためのキー。Bluetooth側では音量を
                # 扱わないため常に未対応(None)扱いにする。
                "volume": None,
                "muted": False,
            }

    def _control(self, method_name):
        if self._bus is None or self._player_path is None:
            return
        try:
            player = dbus.Interface(
                self._bus.get_object(BLUEZ_SERVICE, self._player_path),
                MEDIA_PLAYER_IFACE,
            )
            getattr(player, method_name)()
        except Exception:
            pass

    def play_pause(self):
        if self.status == "playing":
            self._control("Pause")
        else:
            self._control("Play")

    def next_track(self):
        self._control("Next")

    def previous_track(self):
        self._control("Previous")

    # ---- 音量 ----
    # USBMediaとインターフェースを揃えるために用意しているが、こちらは
    # 「Piがスピーカー側」ではなく「相手のスマホが再生元」という関係のため、
    # AVRCPの音量制御はPi側の出力音量にしか効かず意味が薄い。そのため
    # 何もしない。main.py/widgets.pyはどちらのソースでも同じコードで動く。
    def volume_up(self, steps=1):
        pass

    def volume_down(self, steps=1):
        pass

    def toggle_mute(self):
        pass

    def adjust_volume(self, delta):
        pass


if __name__ == "__main__":
    m = BluetoothMedia()
    m.start()
    for _ in range(10):
        time.sleep(1)
        print(m.get())
