# -*- coding: utf-8 -*-
"""
win_media_sender.py

Windows PC上で現在再生中のメディア(Spotify, ブラウザのYouTube, ローカルの
メディアプレイヤー等 -- Windowsの「メディアコントロール」に対応しているアプリ全般)
の情報を取得し、USBシリアル経由でRaspberry Piへ送信する常駐スクリプト。

対応OS: Windows 10 (1809以降) / Windows 11
        (Windows.Media.Control API = SMTC: System Media Transport Controls を使用)

必要パッケージ:
    pip install winsdk pyserial
    pip install pycaw comtypes   # 任意。入れると音量の取得/設定が正確になる
                                 # (未インストールでも仮想キーで音量操作は可能)

前提:
    - RaspberryPiとUSBケーブルで接続し、Pi側がUSB CDC-ACM(シリアル)ガジェットとして
      動作していること(セットアップ手順は pi_receiver/README.md 参照)。
    - デバイスマネージャーで「ポート(COMとLPT)」に表示される
      COMポート番号を SERIAL_PORT に設定する。

実行方法:
    python win_media_sender.py
"""
import asyncio
import base64
import ctypes
import json
import sys
import time
from datetime import datetime, timezone

import serial
from winsdk.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as MediaManager,
)
from winsdk.windows.storage.streams import Buffer, InputStreamOptions

try:
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    PYCAW_AVAILABLE = True
except ImportError:
    # pycaw未インストールでも動くようにする(音量の「取得」だけができなくなり、
    # 操作は仮想キー送出で代替する)。
    PYCAW_AVAILABLE = False

# ------------------------------------------------------------------
# 設定 (環境に合わせて変更する)
# ------------------------------------------------------------------
SERIAL_PORT = "COM5"      # デバイスマネージャーで確認して書き換える
BAUD_RATE = 115200
POLL_INTERVAL_SEC = 1.0
ARTWORK_MAX_BYTES = 150_000  # あまり大きい画像はシリアル転送が重くなるため上限を設ける
VOLUME_STEP = 0.02        # ロータリーエンコーダー1クリックあたりの音量変化(pycaw使用時)
# 1メッセージで受け付ける音量ステップの上限。
# Piは1クリックにつき1通送ってくるので、通常stepsは1〜数程度にしかならない。
# 壊れたメッセージやノイズで巨大な値が入ったときに、キー送出を延々と
# 繰り返してPCが固まるのを防ぐための歯止め。
MAX_VOLUME_STEPS = 20

_PLAYBACK_STATUS_MAP = {
    0: "closed",
    1: "opened",
    2: "changing",
    3: "stopped",
    4: "playing",
    5: "paused",
}


# ------------------------------------------------------------------
# 音量制御
#   Windows.Media.Control(SMTC)は再生操作専用で音量を扱えないため、別経路が必要。
#   pycawがあればスピーカーの音量を直接読み書きし(現在の音量をPiの画面に
#   表示できる)、無ければキーボードの音量キーを送って代替する。
# ------------------------------------------------------------------
_VK_VOLUME_MUTE = 0xAD
_VK_VOLUME_DOWN = 0xAE
_VK_VOLUME_UP = 0xAF
_KEYEVENTF_KEYUP = 0x0002


def _tap_key(vk_code, times=1):
    for _ in range(max(1, times)):
        ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk_code, 0, _KEYEVENTF_KEYUP, 0)


class VolumeControl:
    """既定の再生デバイスの音量を操作する。pycawが無い環境では
    仮想キー送出にフォールバックし、取得(get)はNoneを返す。
    """

    def __init__(self):
        self._endpoint = None
        if PYCAW_AVAILABLE:
            self._endpoint = self._open_endpoint()

    @staticmethod
    def _open_endpoint():
        """既定の再生デバイスのIAudioEndpointVolumeを取得する。
        pycawはバージョンによってAPIが違うため、両方の作法を順に試す。
        """
        try:
            speakers = AudioUtilities.GetSpeakers()
        except Exception:
            return None

        # 新しいpycaw (2024年以降): AudioDevice.EndpointVolume で直接取れる
        try:
            endpoint = speakers.EndpointVolume
            if endpoint is not None:
                return endpoint
        except AttributeError:
            pass

        # 従来のpycaw: 生のIMMDeviceからActivateする
        try:
            interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return interface.QueryInterface(IAudioEndpointVolume)
        except Exception:
            return None

    @property
    def available(self):
        return self._endpoint is not None

    def get(self):
        """(音量0.0〜1.0, ミュート中か) を返す。取得できない場合は (None, False)。"""
        if self._endpoint is None:
            return None, False
        try:
            return (
                float(self._endpoint.GetMasterVolumeLevelScalar()),
                bool(self._endpoint.GetMute()),
            )
        except Exception:
            return None, False

    def step(self, direction, steps=1):
        """directionは +1(上げる)/-1(下げる)。"""
        # 呼び出し側でも制限しているが、公開メソッドなのでここでも歯止めをかける
        steps = max(1, min(int(steps), MAX_VOLUME_STEPS))
        if self._endpoint is None:
            _tap_key(_VK_VOLUME_UP if direction > 0 else _VK_VOLUME_DOWN, steps)
            return
        try:
            current = self._endpoint.GetMasterVolumeLevelScalar()
            target = min(1.0, max(0.0, current + direction * VOLUME_STEP * steps))
            self._endpoint.SetMasterVolumeLevelScalar(target, None)
            # 音量を動かしたらミュートは解除しておく(そのほうが直感的)
            if self._endpoint.GetMute():
                self._endpoint.SetMute(0, None)
        except Exception:
            pass

    def toggle_mute(self):
        if self._endpoint is None:
            _tap_key(_VK_VOLUME_MUTE)
            return
        try:
            self._endpoint.SetMute(0 if self._endpoint.GetMute() else 1, None)
        except Exception:
            pass


async def _read_thumbnail_bytes(thumbnail_ref):
    """MediaPropertiesのthumbnail(IRandomAccessStreamReference)を
    バイト列(PNG/JPEG)として読み出す。取得できない場合はNoneを返す。
    """
    if thumbnail_ref is None:
        return None
    try:
        stream = await thumbnail_ref.open_read_async()
        size = stream.size
        if size == 0 or size > ARTWORK_MAX_BYTES:
            return None
        buffer = Buffer(size)
        await stream.read_async(buffer, size, InputStreamOptions.READ_AHEAD)
        # Bufferから素直にbytesへ変換する
        return bytes(bytearray(buffer))
    except Exception:
        return None


async def get_current_media():
    """現在フォーカスされている(≒最も優先度の高い)メディアセッションの
    情報を辞書で返す。再生中セッションが無ければNone。
    """
    manager = await MediaManager.request_async()
    session = manager.get_current_session()
    if session is None:
        return None

    info = await session.try_get_media_properties_async()
    playback_info = session.get_playback_info()
    timeline = session.get_timeline_properties()

    status = _PLAYBACK_STATUS_MAP.get(int(playback_info.playback_status), "stopped")
    artwork_bytes = await _read_thumbnail_bytes(info.thumbnail)

    duration_ms, position_ms = 0, 0
    try:
        duration_ms = int(timeline.end_time.total_seconds() * 1000)
        position_ms = int(timeline.position.total_seconds() * 1000)
        # timeline.positionはSMTCが最後に通知してきた時点のスナップショットで、
        # 再生中でも自動的には進まない(アプリ側がシーク/一時停止など何かを
        # 通知した時しか更新されない)。再生中は最終更新時刻からの経過時間を
        # 足して、実際の再生位置を推定する(YouTube等の見た目の動きに合わせる)。
        if status == "playing":
            elapsed_sec = (datetime.now(timezone.utc) - timeline.last_updated_time).total_seconds()
            rate = playback_info.playback_rate or 1.0
            if elapsed_sec > 0:
                position_ms += int(elapsed_sec * rate * 1000)
            if duration_ms > 0:
                position_ms = min(position_ms, duration_ms)
    except Exception:
        pass

    return {
        "title": info.title or "",
        "artist": info.artist or "",
        "album": info.album_title or "",
        "status": status,
        "duration_ms": duration_ms,
        "position_ms": position_ms,
        "artwork": artwork_bytes,
    }


def _send(ser, msg_dict):
    line = json.dumps(msg_dict, ensure_ascii=False) + "\n"
    ser.write(line.encode("utf-8"))


async def _handle_incoming_commands(ser, session_getter, volume):
    """Pi側(物理ボタン/ロータリーエンコーダー/タッチ操作)から送られてくる
    コントロールコマンドを処理する。
    非ブロッキングにser.in_waitingをポーリングする簡易実装。
    Piは操作のたびに1行送ってくるので、溜まっている分をまとめて捌く。
    """
    while ser.in_waiting > 0:
        raw = ser.readline()
        try:
            msg = json.loads(raw.decode("utf-8", errors="ignore").strip())
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            continue
        if msg.get("type") != "control":
            continue

        action = msg.get("action")
        # stepsは相手から来る値なので、数値でないものが入っていても
        # ここで落ちないようにする(このスクリプト全体が止まってしまうため)
        try:
            steps = int(msg.get("steps", 1) or 1)
        except (TypeError, ValueError):
            steps = 1

        # 音量系はメディアセッションが無くても操作できる
        if action == "volume_up":
            volume.step(+1, steps)
            continue
        if action == "volume_down":
            volume.step(-1, steps)
            continue
        if action == "toggle_mute":
            volume.toggle_mute()
            continue

        session = session_getter()
        if session is None:
            continue
        try:
            if action == "play_pause":
                info = session.get_playback_info()
                if int(info.playback_status) == 4:  # playing
                    await session.try_pause_async()
                else:
                    await session.try_play_async()
            elif action == "next":
                await session.try_skip_next_async()
            elif action == "previous":
                await session.try_skip_previous_async()
        except Exception:
            pass


async def _main_loop(ser):
    manager = await MediaManager.request_async()
    volume = VolumeControl()
    last_track_key = None

    while True:
        session = manager.get_current_session()
        media = await get_current_media()
        vol_level, vol_muted = volume.get()

        if media is not None:
            track_key = (media["title"], media["artist"], media["album"])
            if track_key != last_track_key:
                # 曲が変わった時だけアートワーク付きのtrackメッセージを送る
                msg = {
                    "type": "track",
                    "title": media["title"],
                    "artist": media["artist"],
                    "album": media["album"],
                    "duration_ms": media["duration_ms"],
                }
                if media["artwork"]:
                    msg["artwork_b64"] = base64.b64encode(media["artwork"]).decode("ascii")
                _send(ser, msg)
                last_track_key = track_key
            else:
                # 再生位置/状態だけの軽量な更新
                _send(ser, {
                    "type": "status",
                    "status": media["status"],
                    "position_ms": media["position_ms"],
                    "volume": vol_level,
                    "muted": vol_muted,
                })
        elif vol_level is not None:
            # 再生中の曲が無くても、音量だけは画面に出せるよう送っておく
            _send(ser, {"type": "status", "volume": vol_level, "muted": vol_muted})

        # Pi側からのコントロール要求があれば処理する
        await _handle_incoming_commands(ser, manager.get_current_session, volume)

        await asyncio.sleep(POLL_INTERVAL_SEC)


def main():
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.5)
    except serial.SerialException as e:
        print(f"シリアルポート {SERIAL_PORT} を開けなかった: {e}")
        print("Raspberry PiがUSB CDC-ACMガジェットとして正しく認識されているか、")
        print("COMポート番号が合っているかを確認する。")
        sys.exit(1)

    volume_mode = "pycaw(音量の取得/設定に対応)" if VolumeControl().available else "仮想キー(音量の取得は不可)"
    print(f"{SERIAL_PORT} @ {BAUD_RATE}bps で楽曲情報の送信を開始。Ctrl+Cで終了。")
    print(f"音量制御: {volume_mode}")
    try:
        asyncio.run(_main_loop(ser))
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()


if __name__ == "__main__":
    main()
