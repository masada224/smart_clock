# -*- coding: utf-8 -*-
"""
学習した赤外線リモコンの波形データを、名前付きでJSONファイルに保存/読み出しする
モジュール。ir_receiver.pyが書き込み、ir_control.pyが読み出して送信する。

保存先: config.IR_CODES_FILE (デフォルト ir_codes.json)

ファイル形式:
    {
      "冷房26度": {
        "pulses": [3400, 1700, 420, 420, ...],
        "captured_at": "2026-08-20T22:30:00"
      },
      ...
    }

pulsesは ir_control.IRController.send() にそのまま渡せる、マイクロ秒単位の
[mark, space, mark, space, ...] のリスト (先頭は必ずmark)。
"""
import json
import os
from datetime import datetime

import config


def _load_all(path=None):
    path = path or config.IR_CODES_FILE
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        # 壊れたファイルで起動できなくなるのは困るので、空扱いにして続行する
        return {}


def _save_all(codes, path=None):
    path = path or config.IR_CODES_FILE
    # 書き込み途中で電源が切れても元のファイルを失わないよう、一時ファイル経由で置換する
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(codes, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def save(name, pulses, path=None):
    """波形データを名前を付けて保存する(同名は上書き)。"""
    codes = _load_all(path)
    codes[name] = {
        "pulses": list(pulses),
        "captured_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_all(codes, path)


def load(name, path=None):
    """名前から波形データ(pulses)を返す。未登録ならNone。"""
    entry = _load_all(path).get(name)
    return entry.get("pulses") if entry else None


def names(path=None):
    """登録済みの名前を一覧で返す。"""
    return sorted(_load_all(path).keys())


def describe(path=None):
    """名前 -> (区間数, 学習日時) の辞書を返す(一覧表示用)。"""
    return {
        name: (len(entry.get("pulses", [])), entry.get("captured_at", "?"))
        for name, entry in _load_all(path).items()
    }


def delete(name, path=None):
    """登録を削除する。削除できたらTrue、元々無ければFalse。"""
    codes = _load_all(path)
    if name not in codes:
        return False
    del codes[name]
    _save_all(codes, path)
    return True


if __name__ == "__main__":
    # 単体テスト用: python3 ir_codes.py
    for name, (count, at) in describe().items():
        print(f"{name}: {count}区間 (学習日時: {at})")
