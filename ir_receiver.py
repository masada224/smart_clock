# -*- coding: utf-8 -*-
"""
赤外線(IR)受信モジュールでリモコンの信号を読み取り、波形データとして
学習・保存するモジュール。

配線 (BCM番号):
    IR受信モジュール (VS1838B / TSOP38238 等)
        VCC -> 3.3V
        GND -> GND
        OUT -> config.IR_RX_GPIO_PIN (デフォルト GPIO22)

    ※ この手の受信モジュールの出力は「アクティブLow」(赤外線を受けている間がLow)。
       内部で38kHzの搬送波は復調済みなので、Low/Highの継続時間だけを見ればよい。

波形データの形式:
    ir_control.IRController.send() にそのまま渡せる、マイクロ秒単位の
    [mark, space, mark, space, ...] のリスト (先頭は必ずmark)。

pigpioデーモン (Raspberry Pi実機側の前提):
    sudo systemctl enable --now pigpiod

使い方:
    python3 ir_receiver.py 冷房26度      # リモコンを向けてボタンを押す -> 学習して保存
    python3 ir_receiver.py 冷房26度 -n   # 保存せず波形の解析結果だけ表示する
    python3 ir_receiver.py --list        # 学習済みの一覧
    python3 ir_receiver.py --delete 冷房26度
"""
import time

import config
import ir_codes

try:
    import pigpio

    HARDWARE_AVAILABLE = True
except ImportError:
    # Raspberry Pi以外(開発PC)ではimportに失敗するので、
    # その場合は「受信できない」ことを伝えるだけのモードで動作する。
    HARDWARE_AVAILABLE = False


class IRReceiver:
    """pigpioのコールバックでOUTピンのエッジを記録し、1フレーム分の
    マーク/スペースの継続時間の並びとして取り出す。今回は受信専用。
    """

    def __init__(self, gpio_pin=None, glitch_filter_us=None):
        self.gpio_pin = gpio_pin if gpio_pin is not None else config.IR_RX_GPIO_PIN
        self.glitch_filter_us = (
            glitch_filter_us
            if glitch_filter_us is not None
            else config.IR_RX_GLITCH_FILTER_US
        )
        self._pi = None
        self._callback = None
        self._edges = []      # [(tick, level), ...] levelは変化後のレベル
        self._recording = False

        if HARDWARE_AVAILABLE:
            try:
                pi = pigpio.pi()
                if pi.connected:
                    pi.set_mode(self.gpio_pin, pigpio.INPUT)
                    pi.set_pull_up_down(self.gpio_pin, pigpio.PUD_UP)
                    # 搬送波の取りこぼしやチャタリングをノイズとして落とす。
                    # 家電リモコンの最短パルスは400us程度なので100usなら安全。
                    pi.set_glitch_filter(self.gpio_pin, self.glitch_filter_us)
                    self._pi = pi
                else:
                    # pigpiod未起動など
                    pi.stop()
            except Exception:
                self._pi = None

    def _on_edge(self, gpio, level, tick):
        # pigpioのコールバックスレッドから呼ばれる。
        # level 0/1 が実際の変化、2はウォッチドッグなので無視する。
        if not self._recording or level > 1:
            return
        if len(self._edges) < config.IR_CAPTURE_MAX_EDGES:
            self._edges.append((tick, level))

    def capture(self, timeout_sec=None, gap_us=None):
        """リモコンのボタンが1回押されるのを待ち、その波形を返す。
        何も受信できずタイムアウトした場合はNoneを返す。
        """
        timeout_sec = timeout_sec if timeout_sec is not None else config.IR_CAPTURE_TIMEOUT_SEC
        gap_us = gap_us if gap_us is not None else config.IR_CAPTURE_GAP_US

        if self._pi is None:
            print("[IR-RX] 受信できない(pigpioが使えないか、pigpiodが未起動)")
            return None

        self._edges = []
        self._recording = True
        self._callback = self._pi.callback(self.gpio_pin, pigpio.EITHER_EDGE, self._on_edge)

        try:
            deadline = time.monotonic() + timeout_sec
            while time.monotonic() < deadline:
                time.sleep(0.01)
                if not self._edges:
                    continue
                # 最後のエッジからgap_us以上変化が無ければ1フレーム終了とみなす
                last_tick = self._edges[-1][0]
                if pigpio.tickDiff(last_tick, self._pi.get_current_tick()) >= gap_us:
                    break
                if len(self._edges) >= config.IR_CAPTURE_MAX_EDGES:
                    break
        finally:
            self._recording = False
            self._callback.cancel()
            self._callback = None

        if not self._edges:
            return None
        return self._edges_to_pulses(self._edges)

    @staticmethod
    def _edges_to_pulses(edges):
        """記録したエッジを [mark, space, mark, ...] の継続時間リストに変換する。
        受信モジュールはアクティブLowなので、Lowへの変化(立ち下がり)がマークの開始。
        """
        # 最初の立ち下がりまで読み飛ばし、必ずマークから始まるようにする
        start = 0
        while start < len(edges) and edges[start][1] != 0:
            start += 1
        edges = edges[start:]
        if len(edges) < 2:
            return []

        # tickは32bitでラップするため、差分はtickDiffで求める
        return [
            pigpio.tickDiff(t0, t1) for (t0, _), (t1, _) in zip(edges, edges[1:])
        ]

    def close(self):
        if self._callback is not None:
            try:
                self._callback.cancel()
            except Exception:
                pass
            self._callback = None
        if self._pi is not None:
            try:
                self._pi.set_glitch_filter(self.gpio_pin, 0)
                self._pi.stop()
            except Exception:
                pass
            self._pi = None


def summarize(pulses):
    """受信した波形の構造をざっくり解析して表示する。
    エアコンの信号をどう扱うか(丸ごと再生で済ませるか、プロトコルを実装するか)を
    判断するための材料として使う。
    """
    if not pulses:
        print("  (波形が空)")
        return

    total_ms = sum(pulses) / 1000.0
    print(f"  区間数    : {len(pulses)}")
    print(f"  全体の長さ: {total_ms:.1f} ms")
    print(f"  リーダー部: mark {pulses[0]}us / space {pulses[1] if len(pulses) > 1 else '-'}us")

    # リーダー部(先頭2区間)を除いた、(mark, space)のペアが1bitに対応する想定。
    body = pulses[2:]
    spaces = body[1::2]
    if len(spaces) < 8:
        print("  ビット列  : (短すぎて判定できない)")
        return

    lo, hi = min(spaces), max(spaces)
    threshold = (lo + hi) / 2
    bits = "".join("1" if s > threshold else "0" for s in spaces)
    print(f"  推定bit数 : {len(bits)}")
    print(f"  space長   : 短 {lo}us / 長 {hi}us (判定しきい値 {threshold:.0f}us)")
    print("  ビット列  :")
    for i in range(0, len(bits), 64):
        print(f"    {bits[i:i + 64]}")

    if len(bits) > 64:
        print("  -> bit数が多いので、エアコンのように「状態まるごと」を送るタイプ。")
        print("     温度やモードごとに1つずつ学習して保存する運用が現実的。")


def _learn(name, save=True):
    rx = IRReceiver()
    try:
        print(f"[IR-RX] GPIO{rx.gpio_pin} で待機中。")
        print(f"        受信モジュールにリモコンを向けて「{name}」のボタンを押す")
        print(f"        ({config.IR_CAPTURE_TIMEOUT_SEC}秒でタイムアウト)")
        pulses = rx.capture()
    finally:
        rx.close()

    if not pulses:
        print("[IR-RX] 受信できなかった。配線・電源・pigpiod・向きを確認する。")
        return 1

    print(f"\n[IR-RX] 受信しました: {name}")
    summarize(pulses)

    if save:
        ir_codes.save(name, pulses)
        print(f"\n[IR-RX] {config.IR_CODES_FILE} に保存しました。")
    else:
        print("\n[IR-RX] -n が指定されたので保存していない。")
    return 0


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="赤外線リモコンの信号を学習してir_codes.jsonに保存する"
    )
    parser.add_argument("name", nargs="?", help="学習する信号の名前 (例: 冷房26度)")
    parser.add_argument("-n", "--no-save", action="store_true", help="保存せず解析結果だけ表示する")
    parser.add_argument("--list", action="store_true", help="学習済みの一覧を表示する")
    parser.add_argument("--delete", metavar="NAME", help="学習済みの信号を削除する")
    args = parser.parse_args()

    if args.list:
        described = ir_codes.describe()
        if not described:
            print("学習済みの信号はまだ無い。")
        for n, (count, at) in described.items():
            print(f"{n}: {count}区間 (学習日時: {at})")
        sys.exit(0)

    if args.delete:
        print(f"削除した: {args.delete}" if ir_codes.delete(args.delete) else f"見つからない: {args.delete}")
        sys.exit(0)

    if not args.name:
        parser.print_help()
        sys.exit(1)

    sys.exit(_learn(args.name, save=not args.no_save))
