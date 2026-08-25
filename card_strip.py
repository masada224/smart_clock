# -*- coding: utf-8 -*-
"""
時計の下のカードを横一列に並べ、スワイプでスクロールできるようにするモジュール。

見せ方:
    カードを帯状に並べ、指でなぞると連続的に動く。指を離すと一番近いカードの
    位置にスナップする。素早く払う(フリック)と隣のカードへ送られる。
    帯の下に、今どのあたりを見ているかを示すドットを表示する。

タッチ操作について:
    SDL2はタッチパネルの操作をマウスイベントとしても通知するため、この
    モジュールはマウスイベント(MOUSEBUTTONDOWN/MOUSEMOTION/MOUSEBUTTONUP)
    だけを扱う。こうすると開発PCのマウスでも実機のタッチパネルでも同じ
    コードで動き、FINGER系イベントとの二重処理も起きない。

タップとスワイプの区別:
    指を離した時点で、押してからの移動量と経過時間が config の閾値未満なら
    「タップ」とみなし、その位置のカードに処理を渡す(エアコンのボタン等)。
    それ以外はスクロール操作として扱う。
"""
import math
import time

import pygame

import config

# フリックの速度を求める窓。指を離す直前この秒数ぶんの移動から速度を出す。
# 直前2イベントの瞬間速度だと、指の震えやイベントの粗さで値が暴れるため。
_VELOCITY_WINDOW_SEC = 0.1

# 経過時間の計測には time.monotonic() ではなく perf_counter() を使う。
# monotonic()はWindowsで分解能が約15.6msしかなく、タッチやマウスの
# 連続イベントの間隔を測ると0になってしまい、速度が求められないため。
_now = time.perf_counter


class Card:
    """帯に並べる1枚のカード。

    draw   : draw(screen, fonts, rect) — 与えられた矩形に自分を描く
    on_tap : on_tap(local_pos) — カード内がタップされた時に呼ばれる。
             local_posはカード左上を原点とした座標。処理したらTrueを返す。
             不要ならNoneでよい。
    """

    def __init__(self, key, draw, on_tap=None):
        self.key = key
        self.draw = draw
        self.on_tap = on_tap


class CardStrip:
    def __init__(self, cards, viewport, card_width=None, gap=None):
        self.cards = list(cards)
        self.viewport = viewport
        self.card_width = card_width if card_width is not None else config.CARD_WIDTH
        self.gap = gap if gap is not None else config.CARD_GAP

        self.scroll = 0.0          # 帯の左端から見て、今どれだけ左にずらしているか
        self._target_scroll = 0.0

        self._dragging = False
        self._drag_start_x = 0
        self._drag_start_scroll = 0.0
        self._drag_start_at = 0.0
        self._drag_moved = 0        # 押してからの移動量の最大値
        self._samples = []          # 直近の指の位置 [(時刻, x), ...]

    # ---- レイアウト計算 ----
    @property
    def _step(self):
        return self.card_width + self.gap

    @property
    def _max_scroll(self):
        if not self.cards:
            return 0.0
        total = len(self.cards) * self._step - self.gap
        return max(0.0, total - self.viewport.width)

    def _clamp(self, value):
        return max(0.0, min(self._max_scroll, value))

    def card_rect(self, index):
        """index番目のカードの、画面上での矩形を返す。"""
        x = self.viewport.x + index * self._step - self.scroll
        return pygame.Rect(round(x), self.viewport.y, self.card_width, self.viewport.height)

    def snap_positions(self):
        """スナップで実際に止まれるスクロール位置の一覧。

        カードは2枚並んで見えるため、末尾のカードほど「そこを左端にする」
        ことができない(右端で頭打ちになる)。同じ位置に潰れる分は1つに
        まとめるので、ドットの数 = 実際に切り替えられるページ数になる。
        """
        positions = []
        for i in range(len(self.cards)):
            p = self._clamp(i * self._step)
            if not positions or p > positions[-1] + 0.5:
                positions.append(p)
        return positions

    def _active_page(self):
        """今どのスナップ位置に一番近いかを返す(ドットの点灯位置)。"""
        positions = self.snap_positions()
        if not positions:
            return 0
        return min(range(len(positions)), key=lambda i: abs(positions[i] - self.scroll))

    def _snap_to(self, index):
        index = max(0, min(len(self.cards) - 1, index))
        self._target_scroll = self._clamp(index * self._step)

    # ---- 入力 ----
    def handle_event(self, event):
        """イベントを処理したらTrueを返す。"""
        if not self.cards:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self.viewport.collidepoint(event.pos):
                return False
            self._dragging = True
            self._drag_start_x = event.pos[0]
            self._drag_start_scroll = self.scroll
            self._drag_start_at = _now()
            self._drag_moved = 0
            self._samples = [(self._drag_start_at, event.pos[0])]
            return True

        if event.type == pygame.MOUSEMOTION and self._dragging:
            dx = event.pos[0] - self._drag_start_x
            self._drag_moved = max(self._drag_moved, abs(dx))
            # 指の動きにそのまま追従させる(左に払うと右のカードが出てくる)
            self.scroll = self._clamp(self._drag_start_scroll - dx)
            self._target_scroll = self.scroll
            self._record_sample(event.pos[0])
            return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._dragging:
            self._dragging = False
            held_sec = _now() - self._drag_start_at

            # ほとんど動いていなければタップとして扱う
            if self._drag_moved <= config.CARD_TAP_MAX_MOVE_PX and held_sec <= config.CARD_TAP_MAX_SEC:
                self._handle_tap(event.pos)
                return True

            velocity = self._flick_velocity()
            pos_in_cards = self.scroll / self._step
            if velocity <= -config.CARD_FLICK_MIN_SPEED:
                # 左に払った -> 次のカードへ送る
                self._snap_to(math.floor(pos_in_cards) + 1)
            elif velocity >= config.CARD_FLICK_MIN_SPEED:
                # 右に払った -> 前のカードへ戻す
                self._snap_to(math.ceil(pos_in_cards) - 1)
            else:
                # ゆっくり離した -> 一番近いカードにスナップ
                self._snap_to(round(pos_in_cards))
            return True

        return False

    def _record_sample(self, x):
        now = _now()
        self._samples.append((now, x))
        # 窓から外れた古いサンプルは捨てる(最低2点は残す)
        cutoff = now - _VELOCITY_WINDOW_SEC
        while len(self._samples) > 2 and self._samples[1][0] < cutoff:
            self._samples.pop(0)

    def _flick_velocity(self):
        """指を離す直前の水平方向の速度(px/秒)。左向きが負。

        窓の中に動きが無ければ0を返すので、指を止めてから離した場合は
        フリック扱いにならず、その場で一番近いカードにスナップする。
        """
        if len(self._samples) < 2:
            return 0.0
        cutoff = _now() - _VELOCITY_WINDOW_SEC
        recent = [s for s in self._samples if s[0] >= cutoff]
        if len(recent) < 2:
            return 0.0
        (t0, x0), (t1, x1) = recent[0], recent[-1]
        span = t1 - t0
        return (x1 - x0) / span if span > 0 else 0.0

    def _handle_tap(self, pos):
        for i, card in enumerate(self.cards):
            rect = self.card_rect(i)
            if card.on_tap is not None and rect.collidepoint(pos):
                card.on_tap((pos[0] - rect.x, pos[1] - rect.y))
                return

    # ---- 更新/描画 ----
    def update(self, dt):
        """スナップアニメーションを進める。main.pyから毎フレーム呼ぶ。"""
        if self._dragging:
            return
        diff = self._target_scroll - self.scroll
        if abs(diff) < 0.5:
            self.scroll = self._target_scroll
            return
        # 目標に指数的に近づける(dtに依存しない減衰)
        self.scroll += diff * min(1.0, dt * config.CARD_SNAP_SPEED)

    def draw(self, screen, fonts):
        prev_clip = screen.get_clip()
        screen.set_clip(self.viewport)
        for i, card in enumerate(self.cards):
            rect = self.card_rect(i)
            # 画面外のカードは描かない(Pi Zero 2Wでの無駄な描画を避ける)
            if rect.right < self.viewport.left or rect.left > self.viewport.right:
                continue
            card.draw(screen, fonts, rect)
        screen.set_clip(prev_clip)
        self._draw_dots(screen)

    def _draw_dots(self, screen):
        """今どのあたりを見ているかを示すドットを帯の下に描く。"""
        n = len(self.snap_positions())
        if n <= 1:
            return
        active = self._active_page()
        spacing = 14
        # カードを縮めずに済むよう、画面下端のマージンの中に描く
        cy = self.viewport.bottom + config.MARGIN // 2
        start_x = config.SCREEN_WIDTH // 2 - (n - 1) * spacing // 2
        for i in range(n):
            cx = start_x + i * spacing
            if i == active:
                pygame.draw.circle(screen, config.ACCENT, (cx, cy), 4)
            else:
                pygame.draw.circle(screen, config.CARD_BORDER, (cx, cy), 3)
