# -*- coding: utf-8 -*-
"""
各パネルの描画を行うモジュール。main.pyから呼び出される。
"""
import math
import os

import pygame

import config
from weather_openmeteo import (
    ICON_SUNNY, ICON_CLOUDY, ICON_RAIN, ICON_SUN_CLOUD,
    ICON_SNOW, ICON_THUNDER, ICON_SLEET,
)

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


# ----------------------------------------------------------------
# フォント読み込み
# ----------------------------------------------------------------
def _load_font(path, fallback_name, size):
    if os.path.isfile(path):
        return pygame.font.Font(path, size)
    # 日本語TTFが未配置の場合はシステムフォントにフォールバック
    # (日本語が文字化け(豆腐)する可能性があるため、極力TTFの配置を推奨)
    return pygame.font.SysFont(fallback_name, size)


def load_fonts():
    # 明朝(Shippori Mincho)は時計の数字と日付/曜日だけに使う。℃などの
    # 記号を収録しておらず、文字幅も広いため、データがぎっしり並ぶ
    # ラベル類(降水確率のパーセントや時刻など)に使うと記号が豆腐に
    # なったり文字同士が衝突したりするため、そちらはNoto Sans JPのまま。
    return {
        "time": _load_font(config.FONT_SERIF_EXTRABOLD, "serif", 160)
        if os.path.isfile(config.FONT_SERIF_EXTRABOLD)
        else _load_font(config.FONT_SERIF_EXTRABOLD, "serif", 140),
        "date": _load_font(config.FONT_SERIF_REGULAR, "serif", 60),
        "label": _load_font(config.FONT_LIGHT, "sans-serif", 20),
        "value_lg": _load_font(config.FONT_SEMIBOLD, "sans-serif", 30),
        "small": _load_font(config.FONT_REGULAR, "sans-serif", 18),
        "pop": _load_font(config.FONT_MEDIUM, "sans-serif", 18),
        "title": _load_font(config.FONT_SEMIBOLD, "sans-serif", 16),
        "subtitle": _load_font(config.FONT_LIGHT, "sans-serif", 13),
        "tiny": _load_font(config.FONT_REGULAR, "sans-serif", 14),
    }


def _text(surface, font, text, color, topleft=None, center=None, midright=None, midtop=None, topright=None):
    img = font.render(text, True, color)
    rect = img.get_rect()
    if topleft is not None:
        rect.topleft = topleft
    elif center is not None:
        rect.center = center
    elif midright is not None:
        rect.midright = midright
    elif midtop is not None:
        rect.midtop = midtop
    elif topright is not None:
        rect.topright = topright
    surface.blit(img, rect)
    return rect


def _text_row_right_aligned(surface, segments, right_x, y, gap=6):
    """segments: [(text, font, color), ...] を実際の描画幅から詰めて並べ、
    全体をright_xに右揃えする(固定座標の指定によるラベル同士の重なりを防ぐ)。
    """
    rendered = [font.render(text, True, color) for text, font, color in segments]
    total_w = sum(img.get_width() for img in rendered) + gap * (len(rendered) - 1)
    x = right_x - total_w
    for img in rendered:
        rect = img.get_rect(midleft=(x, y))
        surface.blit(img, rect)
        x += img.get_width() + gap


def _ink_block_center_dy(font, lines):
    """midleft基準で各行を(text, y)の高さに並べたときの、
    「指定したy(=フォントボックスの中心)で測ったブロック中心」と
    「実際に描画されたピクセルで測ったブロック中心」との差を返す。
    明朝の漢字はボックス内でやや下寄りに描かれるため、この差を引いてから
    配置すると字面の中心で揃う。全行を同じ量ずらすので行間は変わらない。
    """
    tops, bottoms = [], []
    for text, line_y in lines:
        img = font.render(text, True, (255, 255, 255))
        ink = img.get_bounding_rect()
        box_top = line_y - img.get_height() / 2
        tops.append(box_top + ink.top)
        bottoms.append(box_top + ink.bottom)
    anchor_center = (min(y for _, y in lines) + max(y for _, y in lines)) / 2
    return (min(tops) + max(bottoms)) / 2 - anchor_center


def _make_glow_surface(img, alpha=90, shrink=6, pad=16):
    """imgを縮小->拡大することで安価にぼかし、じんわり光るグロー画像を作る
    (_make_blurred_backdropと同じ考え方)。縁がはみ出す分だけpadを足して
    おき、呼び出し側は(元の位置 - pad)にこのSurfaceを重ねればよい。
    """
    base = pygame.Surface((img.get_width() + pad * 2, img.get_height() + pad * 2), pygame.SRCALPHA)
    base.blit(img, (pad, pad))
    w, h = base.get_size()
    small = pygame.transform.smoothscale(base, (max(1, w // shrink), max(1, h // shrink)))
    glow = pygame.transform.smoothscale(small, (w, h))
    glow.set_alpha(alpha)
    return glow, pad


# ----------------------------------------------------------------
# 上部: 時計 + 日付パネル
# ----------------------------------------------------------------
_clock_glow_cache = {"key": None, "hh": None, "colon": None, "mm": None, "colon_dy": 0}
_clock_date_dy_cache = {"key": None, "dy": 0}


def draw_clock_panel(screen, fonts, now):
    # コロンだけ差し色(ACCENT)にするため、時/分と分けて幅を測りながら並べる。
    hh = now.strftime("%H")
    mm = now.strftime("%M")
    time_font = fonts["time"]
    x, y = 30, -10

    hh_img = time_font.render(hh, True, config.WHITE)
    colon_img = time_font.render(":", True, config.ACCENT)
    mm_img = time_font.render(mm, True, config.WHITE)

    # デスクのLEDバーの光に呼応するような、うっすらした暖色のグローを
    # 数字の下に敷く。分が変わるまで(=文字列が変わるまで)は毎フレーム
    # 作り直さずキャッシュを使い回す。
    cache_key = (hh, mm)
    if _clock_glow_cache["key"] != cache_key:
        _clock_glow_cache["hh"] = _make_glow_surface(hh_img, alpha=60)
        _clock_glow_cache["colon"] = _make_glow_surface(colon_img, alpha=130)
        _clock_glow_cache["mm"] = _make_glow_surface(mm_img, alpha=60)
        # 同じyに置くとベースラインは揃うが、数字がベースライン〜数字高さまで
        # 伸びるのに対しコロンの点はx-height付近までしか無いため、見た目の中心は
        # コロンの方が下にずれる。実際に描画されたピクセルの範囲を測り、
        # インクの中心同士が揃うようにコロンをずらす量を求める。
        _clock_glow_cache["colon_dy"] = (
            hh_img.get_bounding_rect().centery - colon_img.get_bounding_rect().centery
        )
        _clock_glow_cache["key"] = cache_key

    hh_glow, hh_pad = _clock_glow_cache["hh"]
    screen.blit(hh_glow, (x - hh_pad, y - hh_pad))
    screen.blit(hh_img, (x, y))
    x += hh_img.get_width()

    colon_glow, colon_pad = _clock_glow_cache["colon"]
    colon_y = y + _clock_glow_cache["colon_dy"]
    screen.blit(colon_glow, (x - colon_pad, colon_y - colon_pad))
    screen.blit(colon_img, (x, colon_y))
    x += colon_img.get_width()

    mm_glow, mm_pad = _clock_glow_cache["mm"]
    screen.blit(mm_glow, (x - mm_pad, y - mm_pad))
    screen.blit(mm_img, (x, y))

    month_day = f"{now.month}月{now.day}日"
    weekday = f"{WEEKDAY_JP[now.weekday()]}曜日"

    # 日付/曜日の2行ブロックの中心を、時計の数字の中心の高さに揃える。
    # コロンと同様、フォントボックスではなく実際に描画されるピクセル(字面)の
    # 中心同士を合わせる。日付は1日に1回しか変わらないのでズレ量はキャッシュする。
    date_font = fonts["date"]
    clock_center_y = y + hh_img.get_bounding_rect().centery
    line_center_gap = date_font.get_height()  # 2行の中心同士の間隔
    line1_y = clock_center_y - line_center_gap / 2
    line2_y = clock_center_y + line_center_gap / 2

    date_cache_key = (month_day, weekday)
    if _clock_date_dy_cache["key"] != date_cache_key:
        _clock_date_dy_cache["dy"] = _ink_block_center_dy(
            date_font, [(month_day, line1_y), (weekday, line2_y)]
        )
        _clock_date_dy_cache["key"] = date_cache_key
    line1_y -= _clock_date_dy_cache["dy"]
    line2_y -= _clock_date_dy_cache["dy"]

    # 1文字ずつ描画してわずかに字間を空け(トラッキング)、上品さを出す。
    right_x = config.SCREEN_WIDTH - 30
    _text_row_right_aligned(
        screen, [(ch, fonts["date"], config.WHITE) for ch in month_day],
        right_x, line1_y, gap=4,
    )
    _text_row_right_aligned(
        screen, [(ch, fonts["date"], config.TEXT_SECONDARY) for ch in weekday],
        right_x, line2_y, gap=4,
    )

    # 時計エリアとカードエリアの間の余白が間延びして見えないよう、
    # 細い区切り線を1本だけ引く。
    divider_y = config.CARD_TOP_Y - config.MARGIN // 2
    pygame.draw.line(
        screen, config.CARD_BORDER,
        (config.MARGIN, divider_y), (config.SCREEN_WIDTH - config.MARGIN, divider_y), 1,
    )


# ----------------------------------------------------------------
# 天気アイコン (画像を使わずベクター描画)
# ----------------------------------------------------------------
def _draw_cloud(surface, cx, cy, scale, color):
    """雲。(cx, cy)を中心として左右対称に描く。
    以前は右側に寄った非対称な形で、scale=1.6のとき幅が90px以上になり
    78pxのアイコンボックスからはみ出していたため、大きさも見直してある。
    """
    r = int(11 * scale)
    pygame.draw.circle(surface, color, (cx - int(r * 1.15), cy + r // 3), r)
    pygame.draw.circle(surface, color, (cx, cy - int(r * 0.45)), int(r * 1.25))
    pygame.draw.circle(surface, color, (cx + int(r * 1.15), cy + r // 3), int(r * 0.95))
    body = pygame.Rect(cx - int(r * 1.6), cy, int(r * 3.2), int(r * 1.05))
    pygame.draw.rect(surface, color, body, border_radius=int(r * 0.5))


def _draw_sun(surface, cx, cy, scale, color):
    r = int(12 * scale)
    pygame.draw.circle(surface, color, (cx, cy), r)
    for i in range(8):
        ang = i * (math.pi / 4)
        x1 = cx + math.cos(ang) * (r + 4)
        y1 = cy + math.sin(ang) * (r + 4)
        x2 = cx + math.cos(ang) * (r + 10)
        y2 = cy + math.sin(ang) * (r + 10)
        pygame.draw.line(surface, color, (x1, y1), (x2, y2), max(2, int(scale)))


# 雲の下に落ちる粒(雨・雪)を並べるときの、粒どうしの間隔
def _precip_spacing(scale):
    return int(11 * scale)


def _draw_raindrop(surface, x, y, scale, color):
    """雨粒1つ。右上から左下へ流れる線として描く。"""
    pygame.draw.line(
        surface, color,
        (x + int(2 * scale), y),
        (x - int(2 * scale), y + int(9 * scale)),
        max(2, int(1.8 * scale)),
    )


def _draw_snowflake(surface, x, y, scale, color):
    """雪の結晶1つ。3本の線を60度ずつ回して6方向の腕にする。"""
    r = max(3, int(4.5 * scale))
    w = max(2, int(1.4 * scale))
    for k in range(3):
        ang = math.pi * k / 3
        dx, dy = math.cos(ang) * r, math.sin(ang) * r
        pygame.draw.line(surface, color, (x - dx, y - dy), (x + dx, y + dy), w)


def _draw_raindrops(surface, cx, cy, scale, color):
    """雨粒を3つ横に並べる。
    以前はここで scale を 12 で割っていたため、scale=1.6 のとき3粒の間隔が
    1pxほどになり、1つの塊にしか見えていなかった。
    """
    s = _precip_spacing(scale)
    for i in (-1, 0, 1):
        _draw_raindrop(surface, cx + i * s, cy, scale, color)


def _draw_snowflakes(surface, cx, cy, scale, color):
    """雪の結晶を3つ。中央だけ少し下げて単調な横一列にしない。"""
    s = _precip_spacing(scale)
    for i, drop in ((-1, 0), (0, int(4 * scale)), (1, 0)):
        _draw_snowflake(surface, cx + i * s, cy + int(4 * scale) + drop, scale, color)


def _draw_sleet(surface, cx, cy, scale):
    """霙。雨粒と雪の結晶を交互に並べて「混じっている」ことを示す。"""
    s = _precip_spacing(scale)
    _draw_raindrop(surface, cx - s, cy, scale, config.BLUE)
    _draw_snowflake(surface, cx, cy + int(4 * scale), scale, config.SNOW)
    _draw_raindrop(surface, cx + s, cy, scale, config.BLUE)


def _draw_lightning(surface, cx, cy, scale, color):
    """稲妻。上から下へ折れ曲がる多角形1つで描く。"""
    pts = [(4, -13), (-6, 2), (-1, 2), (-4, 13), (7, -2), (2, -2)]
    pygame.draw.polygon(
        surface, color,
        [(int(cx + px * scale), int(cy + py * scale)) for px, py in pts],
    )


def draw_weather_icon(surface, icon_type, center, scale=1.0):
    cx, cy = center
    if icon_type == ICON_SUNNY:
        _draw_sun(surface, cx, cy, scale, config.ORANGE)
    elif icon_type == ICON_SUN_CLOUD:
        _draw_sun(surface, cx - int(6 * scale), cy - int(4 * scale), scale * 0.8, config.ORANGE)
        _draw_cloud(surface, cx + int(4 * scale), cy + int(6 * scale), scale * 0.8, config.ICON_GRAY)
    elif icon_type == ICON_RAIN:
        _draw_cloud(surface, cx, cy - int(8 * scale), scale * 0.85, config.ICON_GRAY)
        _draw_raindrops(surface, cx, cy + int(9 * scale), scale, config.BLUE)
    elif icon_type == ICON_SNOW:
        _draw_cloud(surface, cx, cy - int(8 * scale), scale * 0.85, config.ICON_GRAY)
        _draw_snowflakes(surface, cx, cy + int(9 * scale), scale, config.SNOW)
    elif icon_type == ICON_SLEET:
        _draw_cloud(surface, cx, cy - int(8 * scale), scale * 0.85, config.ICON_GRAY)
        _draw_sleet(surface, cx, cy + int(9 * scale), scale)
    elif icon_type == ICON_THUNDER:
        # 雷雲は暗くして、稲妻は雲の下端に少し食い込ませる
        # (雲から伸びているように見せるため)
        _draw_cloud(surface, cx, cy - int(8 * scale), scale * 0.85, config.THUNDER_CLOUD)
        _draw_lightning(surface, cx, cy + int(11 * scale), scale * 0.9, config.LIGHTNING)
    else:  # ICON_CLOUDY
        _draw_cloud(surface, cx, cy, scale * 0.9, (150, 150, 150))


def _draw_card_bg(screen, rect):
    """ダークカードの背景と、黒い画面の上で「浮いて」見えるよう
    細い縁取りを描く。両方のカードで共通して使う。
    """
    pygame.draw.rect(screen, config.CARD_BG, rect, border_radius=config.CARD_RADIUS)
    pygame.draw.rect(screen, config.CARD_BORDER, rect, width=1, border_radius=config.CARD_RADIUS)


# ----------------------------------------------------------------
# 天気/室温カード
# ----------------------------------------------------------------
def draw_weather_panel(screen, fonts, rect, weather_data, sensor_data):
    _draw_card_bg(screen, rect)

    pad = 20
    x0, y0 = rect.x + pad, rect.y + pad

    # 左上: 大きい天気アイコン (現在の代表アイコンとして最初のスロットを使用)
    slots = weather_data.get("slots", [])
    icon_box = pygame.Rect(x0, y0, 78, 78)
    pygame.draw.rect(screen, config.WHITE, icon_box, border_radius=16)
    if slots:
        draw_weather_icon(screen, slots[0]["icon"], icon_box.center, scale=1.6)
    else:
        draw_weather_icon(screen, ICON_CLOUDY, icon_box.center, scale=1.6)

    # 気温ラベル&値
    label_x = icon_box.right + 16
    _text(screen, fonts["label"], "気温", config.TEXT_PRIMARY, topleft=(label_x, y0))
    _text(screen, fonts["small"], "℃", config.TEXT_PRIMARY, topleft=(label_x + 40, y0))

    tcurrent = weather_data.get("temp_current")
    tmax = weather_data.get("temp_max")
    temp_str = f"{tcurrent if tcurrent is not None else '--'}/{tmax if tmax is not None else '--'}"
    _text(screen, fonts["value_lg"], temp_str, config.TEXT_PRIMARY, topleft=(label_x, y0 + 22))

    # 右上: 室温/湿度 (文字幅を測って詰めて並べ、固定座標による重なりを防ぐ)
    right_x = rect.right - pad
    _text_row_right_aligned(
        screen,
        [
            ("室温", fonts["label"], config.TEXT_PRIMARY),
            ("℃", fonts["small"], config.TEXT_PRIMARY),
            ("湿度", fonts["label"], config.TEXT_PRIMARY),
            ("%", fonts["small"], config.TEXT_PRIMARY),
        ],
        right_x, y0 + 10, gap=6,
    )

    room_temp = sensor_data.get("temperature")
    humidity = sensor_data.get("humidity")
    room_str = f"{room_temp if room_temp is not None else '--'}/{humidity if humidity is not None else '--'}"
    _text(screen, fonts["value_lg"], room_str, config.TEXT_PRIMARY, midright=(right_x, y0 + 45))

    # 降水確率 セクション
    section_y = y0 + 100
    _text(screen, fonts["label"], "降水確率", config.TEXT_PRIMARY, topleft=(x0, section_y-10))

    if not slots:
        _text(screen, fonts["small"], "データ取得中...", config.TEXT_SECONDARY, topleft=(x0, section_y + 30))
        return

    n = len(slots)
    row_y = section_y + 30
    col_w = (rect.width - pad * 2) / n
    col_centers = [int(x0 + col_w * (i + 0.5)) for i in range(n)]

    # パーセント表示
    for cx, slot in zip(col_centers, slots):
        _text(screen, fonts["pop"], f"{slot['pop']}%", config.ACCENT, center=(cx, row_y))

    # 簡易グラフ (折れ線)
    graph_top = row_y + 20
    graph_h = 40
    graph_rect = pygame.Rect(x0, graph_top, rect.width - pad * 2, graph_h)
    pygame.draw.rect(screen, config.GRAPH_BG, graph_rect, border_radius=6)

    # 0%/100%がボックスの縁ギリギリ(実質枠外)にならないよう、内側に余白を設ける
    graph_pad = 6
    usable_h = graph_h - graph_pad * 2
    points = []
    for cx, slot in zip(col_centers, slots):
        py = graph_top + graph_pad + usable_h - int(usable_h * slot["pop"] / 100)
        points.append((cx, py))
    if len(points) >= 2:
        pygame.draw.lines(screen, config.ACCENT, False, points, 3)
    # 降水確率が横並びで同じ値になりがちなため、線だけだと折れ線グラフに
    # 見えないことがある。各データ点にマーカーを打ってグラフだと分かりやすくする。
    for px, py in points:
        pygame.draw.circle(screen, config.ACCENT, (px, py), 4)

    # 時刻ラベル
    hour_y = graph_top + graph_h + 14
    for cx, slot in zip(col_centers, slots):
        t = slot["time"]
        _text(screen, fonts["tiny"], t.strftime("%-H:00") if os.name != "nt" else t.strftime("%H:00"),
              config.TEXT_SECONDARY, center=(cx, hour_y))


# ----------------------------------------------------------------
# メディア(音楽)カード
# ----------------------------------------------------------------
def _format_ms(ms):
    total_sec = max(0, ms // 1000)
    m, s = divmod(total_sec, 60)
    return f"{m}:{s:02d}"


def _draw_marquee_text(surface, font, text, color, rect, gap=50, speed=45):
    """rect幅に収まらない場合、右方向へループしながら流れるマーキー表示にする。
    pygame.time.get_ticks()から現在位置を計算するだけなので、呼び出し側で
    状態(スクロール量など)を保持する必要はない。
    """
    img = font.render(text, True, color)
    text_w = img.get_width()
    y = rect.centery - img.get_height() // 2

    if text_w <= rect.width:
        surface.blit(img, (rect.x, y))
        return

    period = text_w + gap
    offset = (pygame.time.get_ticks() / 1000.0 * speed) % period
    x = rect.x - text_w + offset

    prev_clip = surface.get_clip()
    surface.set_clip(rect)
    surface.blit(img, (x, y))
    surface.blit(img, (x + period, y))
    surface.set_clip(prev_clip)


def _draw_music_note_placeholder(surface, rect):
    pygame.draw.rect(surface, config.CARD_BG_ALT, rect, border_radius=10)
    cx, cy = rect.center
    note_color = config.TEXT_SECONDARY
    pygame.draw.circle(surface, note_color, (cx - 14, cy + 18), 10)
    pygame.draw.circle(surface, note_color, (cx + 18, cy + 12), 10)
    pygame.draw.line(surface, note_color, (cx - 4, cy + 18), (cx - 4, cy - 26), 4)
    pygame.draw.line(surface, note_color, (cx + 28, cy + 12), (cx + 28, cy - 32), 4)
    pygame.draw.line(surface, note_color, (cx - 4, cy - 26), (cx + 28, cy - 32), 4)


def _blit_art_fit(surface, image, rect, valign="center"):
    """imageをアスペクト比を保ったまま、クロップ無しでrectに収まる
    最大サイズまで拡大縮小して配置する(CSSのobject-fit: containと同様)。
    rectとアスペクト比が異なる場合、余った部分は下地(呼び出し側で
    rectをあらかじめ塗っておいた背景色)がそのまま余白として見える。
    valign="top"にすると縦方向はrect上端に詰めて配置する
    (メディアカードでは下部に進捗バー等を重ねるため、余白を下側だけに
    集める狙い)。横方向は常に中央揃え。
    """
    img_w, img_h = image.get_size()
    if img_w == 0 or img_h == 0:
        return
    scale = min(rect.width / img_w, rect.height / img_h)
    new_size = (max(1, round(img_w * scale)), max(1, round(img_h * scale)))
    scaled = pygame.transform.smoothscale(image, new_size)
    dest_rect = scaled.get_rect()
    dest_rect.centerx = rect.centerx
    if valign == "top":
        dest_rect.top = rect.top
    else:
        dest_rect.centery = rect.centery
    surface.blit(scaled, dest_rect.topleft)


def _make_blurred_backdrop(image, size):
    """imageをsize全体を覆うように拡大縮小してクロップし(コアラップ)、
    縮小->拡大を経由することでぼかしをかけた背景を作る
    (ガウスぼかしの代わりに使う安価な近似)。文字を乗せても読める
    よう、少し暗くしておく。
    """
    w, h = size
    img_w, img_h = image.get_size()
    canvas = pygame.Surface(size)
    canvas.fill(config.CARD_BG)
    if img_w > 0 and img_h > 0:
        cover_scale = max(w / img_w, h / img_h)
        cov_size = (max(1, round(img_w * cover_scale)), max(1, round(img_h * cover_scale)))
        covered = pygame.transform.smoothscale(image, cov_size)
        cov_rect = covered.get_rect(center=(w // 2, h // 2))
        canvas.blit(covered, cov_rect.topleft)

    small_size = (max(1, w // 8), max(1, h // 8))
    small = pygame.transform.smoothscale(canvas, small_size)
    blurred = pygame.transform.smoothscale(small, size)

    dark = pygame.Surface(size, pygame.SRCALPHA)
    dark.fill((0, 0, 0, 90))
    blurred.blit(dark, (0, 0))
    return blurred


_blur_cache = {"key": None, "surface": None}


def _get_blurred_backdrop(image, size):
    """曲が変わらない限り毎フレーム作り直さないよう、直近1件だけ
    キャッシュする(ぼかし処理は多少コストがあるため)。
    """
    key = (id(image), size)
    if _blur_cache["key"] != key:
        _blur_cache["surface"] = _make_blurred_backdrop(image, size)
        _blur_cache["key"] = key
    return _blur_cache["surface"]


_rounded_mask_cache = {}


def _rounded_mask(size, radius):
    """sizeの角丸矩形アルファマスクを作って使い回す(毎フレーム生成すると
    無駄なため、カードサイズは固定なのでキャッシュする)。
    BLEND_RGBA_MULTで乗算すると、角丸の外側だけ透明にできる。
    """
    key = (size, radius)
    mask = _rounded_mask_cache.get(key)
    if mask is None:
        mask = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
        _rounded_mask_cache[key] = mask
    return mask


def draw_media_panel(screen, fonts, rect, media_data):
    w, h = rect.size
    # アルバムアートをカード全体の背景として描き、その上に文字/進捗バーを
    # 重ねる。角丸はcard(オフスクリーンSurface)を最後に角丸マスクで
    # 乗算して透明化することで実現する(pygame.draw.rectのborder_radius
    # は単色塗り用で、画像のクロップには使えないため)。
    card = pygame.Surface((w, h), pygame.SRCALPHA)

    artwork = media_data.get("artwork")
    has_art = artwork is not None
    if has_art:
        # _blit_art_fitはアスペクト比によって余白ができる場合があるため、
        # 余白が単色べた塗りで「切れている」ように見えないよう、同じ
        # アートワークをぼかして拡大した背景を先に敷いてから、その上に
        # くっきりした本体を重ねる(Spotify等でよくある手法)。
        backdrop = _get_blurred_backdrop(artwork, (w, h))
        card.blit(backdrop, (0, 0))
        # 上端に詰めて配置し、余白(ぼかし部分)は下側だけに出るようにする。
        # ちょうど下部に進捗バー等を重ねるので、見た目にも都合が良い。
        _blit_art_fit(card, artwork, card.get_rect(), valign="top")
    else:
        card.fill(config.CARD_BG)

    pad = 18
    x0 = pad
    right_x = w - pad
    bottom_y = h - pad
    content_w = right_x - x0

    # 経過時間/総時間 + 進捗バー (カード下部、全幅)
    time_h = fonts["tiny"].get_height()
    time_y = bottom_y - time_h
    bar_h = 5
    bar_rect = pygame.Rect(x0, time_y - bar_h - 4, content_w, bar_h)

    # 曲名 / アーティスト名 / アルバム名
    title_h = fonts["title"].get_height()
    subtitle_h = fonts["subtitle"].get_height()
    title_y = bar_rect.top - 6 - subtitle_h - 2 - title_h

    # カードはダークテーマなので、アートワーク有無にかかわらず明るい文字色で
    # 統一できる(以前は「アート無し=明るいカード」だったため文字色を
    # 出し分けていたが、今は不要)。
    text_color = config.WHITE
    subtitle_color = config.TEXT_SECONDARY
    time_color = config.TEXT_SECONDARY
    bar_bg_color = (210, 210, 210)

    if has_art:
        # アートワークの上に文字を置くと視認性が落ちるため、下側だけ
        # 半透明の黒パネルを敷いて文字/進捗バー/コントロールの背景にする。
        # (グラデーションではなくベタ塗り1枚なのは、毎フレーム描画しても
        #  軽く済ませるため)
        overlay_top = max(0, title_y - 10)
        overlay = pygame.Surface((w, h - overlay_top), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        card.blit(overlay, (0, overlay_top))
    else:
        # アートワークが無い場合は音符アイコンを控えめなサイズで上部に表示する。
        icon_area_h = max(0, (title_y - 10) - pad)
        icon_side = int(min(w, icon_area_h) * 0.55)
        if icon_side > 0:
            placeholder_rect = pygame.Rect(0, 0, icon_side, icon_side)
            placeholder_rect.center = (w // 2, pad + icon_area_h // 2)
            _draw_music_note_placeholder(card, placeholder_rect)

    title = media_data.get("title") or "再生中の曲なし"
    artist = media_data.get("artist") or ""
    album = media_data.get("album") or ""

    # アーティスト名とアルバム名を「アーティスト — アルバム」の形で併記する。
    # どちらか一方しか無い場合はそのまま表示し、両方無ければ何も表示しない。
    if artist and album:
        subtitle_line = f"{artist} — {album}"
    else:
        subtitle_line = artist or album

    # カードの幅に収まらない長い曲名は、右方向へ流れるループアニメーション
    # (マーキー)で表示する(折り返しはしない)。
    title_rect = pygame.Rect(x0, title_y, content_w, title_h)
    _draw_marquee_text(card, fonts["title"], title, text_color, title_rect)

    subtitle_rect = pygame.Rect(x0, title_rect.bottom + 2, content_w, subtitle_h)
    if subtitle_line:
        _draw_marquee_text(card, fonts["subtitle"], subtitle_line, subtitle_color, subtitle_rect)

    # 進捗バー (YouTube風: 再生済み=赤の直線、未再生=グレーの直線)
    duration = media_data.get("duration_ms") or 0
    position = media_data.get("position_ms") or 0
    progress = min(1.0, position / duration) if duration > 0 else 0.0
    played_color = (224, 30, 30)

    pygame.draw.rect(card, bar_bg_color, bar_rect, border_radius=bar_h // 2)
    played_w = int(content_w * progress)
    if played_w > 0:
        played_rect = pygame.Rect(bar_rect.x, bar_rect.y, played_w, bar_rect.height)
        pygame.draw.rect(card, played_color, played_rect, border_radius=bar_h // 2)
    dot_x = bar_rect.x + played_w
    pygame.draw.circle(card, played_color, (dot_x, bar_rect.centery), 6)

    _text(card, fonts["tiny"], _format_ms(position), time_color, topleft=(x0, time_y))
    # topleftの現在位置表示と上端を揃える(midrightだと縦中央基準になり、
    # 高さがずれて上の進捗バーと被って見えていたため)
    _text(card, fonts["tiny"], _format_ms(duration), time_color, topright=(right_x, time_y))

    mask = _rounded_mask((w, h), config.CARD_RADIUS)
    card.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    screen.blit(card, rect.topleft)
    # 天気カードと同じ縁取りを重ねて、黒背景の上で「浮いている」見た目を揃える。
    pygame.draw.rect(screen, config.CARD_BORDER, rect, width=1, border_radius=config.CARD_RADIUS)

    # 音量 (PC側でpycawが使える場合のみ送られてくる)
    volume = media_data.get("volume")
    if volume is not None:
        _draw_volume_badge(screen, fonts, rect, volume, media_data.get("muted", False))


def _draw_volume_badge(screen, fonts, rect, volume, muted):
    """カード右上に、PCの音量を小さく重ねて表示する。
    ロータリーエンコーダーを回した結果がその場で見えるようにするためのもの。
    """
    pad = 10
    label = "ミュート" if muted else f"{volume:.0%}"
    img = fonts["tiny"].render(label, True, config.TEXT_SECONDARY if muted else config.TEXT_PRIMARY)

    box_w = img.get_width() + 26
    box_h = img.get_height() + 8
    box = pygame.Rect(rect.right - pad - box_w, rect.y + pad, box_w, box_h)

    chip = pygame.Surface(box.size, pygame.SRCALPHA)
    chip.fill((0, 0, 0, 130))
    screen.blit(chip, box.topleft)
    pygame.draw.rect(screen, config.CARD_BORDER, box, width=1, border_radius=box_h // 2)

    # スピーカーのアイコン(小さな三角形)
    icon_color = config.TEXT_SECONDARY if muted else config.ACCENT
    ix, iy = box.x + 9, box.centery
    pygame.draw.polygon(screen, icon_color,
                        [(ix - 3, iy - 3), (ix, iy - 3), (ix + 4, iy - 7),
                         (ix + 4, iy + 7), (ix, iy + 3), (ix - 3, iy + 3)])
    if muted:
        pygame.draw.line(screen, icon_color, (ix - 4, iy + 6), (ix + 6, iy - 6), 2)

    screen.blit(img, (box.x + 20, box.centery - img.get_height() // 2))


# ----------------------------------------------------------------
# エアコンカード (タッチ操作)
# ----------------------------------------------------------------
def aircon_button_rects(rect, presets):
    """エアコンカード内のプリセットボタンの矩形を返す。
    描画とタップ判定の両方でこの関数を使い、ズレが起きないようにする。
    戻り値: [(プリセット名, pygame.Rect), ...]
    """
    if not presets:
        return []

    pad = 18
    top = rect.y + 84          # 見出しと「最後に送った操作」の下から始める
    bottom = rect.bottom - pad
    cols = 2
    rows = max(1, -(-len(presets) // cols))   # 切り上げ

    gap = 8
    cell_w = (rect.width - pad * 2 - gap * (cols - 1)) / cols
    cell_h = max(28, (bottom - top - gap * (rows - 1)) / rows)

    out = []
    for i, name in enumerate(presets):
        r, c = divmod(i, cols)
        x = rect.x + pad + c * (cell_w + gap)
        y = top + r * (cell_h + gap)
        out.append((name, pygame.Rect(round(x), round(y), round(cell_w), round(cell_h))))
    return out


def draw_aircon_panel(screen, fonts, rect, aircon_data, pressed_name=None):
    """pressed_nameを渡すと、そのボタンを押下中の見た目にする(タップの手応え用)。"""
    _draw_card_bg(screen, rect)

    pad = 18
    x0, y0 = rect.x + pad, rect.y + pad
    _text(screen, fonts["label"], "エアコン", config.TEXT_PRIMARY, topleft=(x0, y0))

    # 赤外線は一方通行でエアコンの状態を読み取れないため、あくまで
    # 「最後に送った操作」であることが分かる書き方にする。
    last = aircon_data.get("last_command")
    sent_at = aircon_data.get("last_sent_at")
    if last:
        status_line = f"最後に送信: {last}"
        if sent_at is not None:
            status_line += f"  {sent_at.strftime('%H:%M')}"
    else:
        status_line = "まだ操作していない"
    _text(screen, fonts["tiny"], status_line, config.TEXT_SECONDARY, topleft=(x0, y0 + 26))

    presets = aircon_data.get("presets") or []
    if not presets:
        _text(screen, fonts["tiny"], "リモコンの信号が未学習",
              config.TEXT_SECONDARY, topleft=(x0, y0 + 62))
        _text(screen, fonts["tiny"], "ir_receiver.py で学習する",
              config.TEXT_SECONDARY, topleft=(x0, y0 + 80))
        return

    for name, btn in aircon_button_rects(rect, presets):
        is_pressed = (name == pressed_name)
        is_last = (name == last)
        if is_pressed:
            bg, fg = config.ACCENT, config.BLACK
        elif is_last:
            bg, fg = config.CARD_BG_ALT, config.ACCENT
        else:
            bg, fg = config.CARD_BG_ALT, config.TEXT_PRIMARY

        pygame.draw.rect(screen, bg, btn, border_radius=10)
        pygame.draw.rect(screen, config.CARD_BORDER, btn, width=1, border_radius=10)
        _text(screen, fonts["tiny"], name, fg, center=btn.center)


# ----------------------------------------------------------------
# 照明カード
# ----------------------------------------------------------------
def draw_light_panel(screen, fonts, rect, pir_data):
    _draw_card_bg(screen, rect)

    pad = 18
    x0, y0 = rect.x + pad, rect.y + pad
    _text(screen, fonts["label"], "デスク照明", config.TEXT_PRIMARY, topleft=(x0, y0))

    brightness = pir_data.get("brightness", 0.0)
    is_on = pir_data.get("light_on", False)

    # 大きく状態を出す
    _text(screen, fonts["value_lg"], "点灯中" if is_on else "消灯中",
          config.ACCENT if is_on else config.TEXT_SECONDARY, topleft=(x0, y0 + 26))

    # 明るさバー
    bar_y = y0 + 74
    bar_rect = pygame.Rect(x0, bar_y, rect.width - pad * 2, 8)
    pygame.draw.rect(screen, config.GRAPH_BG, bar_rect, border_radius=4)
    filled_w = int(bar_rect.width * max(0.0, min(1.0, brightness)))
    if filled_w > 0:
        pygame.draw.rect(screen, config.ACCENT,
                         pygame.Rect(bar_rect.x, bar_rect.y, filled_w, bar_rect.height),
                         border_radius=4)
    _text(screen, fonts["tiny"], f"明るさ {brightness:.0%}", config.TEXT_SECONDARY,
          topleft=(x0, bar_y + 16))

    # 人感センサーの状態
    detected = pir_data.get("motion_detected", False)
    last_at = pir_data.get("last_detected_at")
    _text(screen, fonts["tiny"], "人感センサー", config.TEXT_PRIMARY, topleft=(x0, bar_y + 46))
    if detected:
        detect_line = "検知中"
    elif last_at is not None:
        detect_line = f"最終検知 {last_at.strftime('%H:%M')}"
    else:
        detect_line = "未検知"
    _text(screen, fonts["tiny"], detect_line,
          config.ACCENT if detected else config.TEXT_SECONDARY, topleft=(x0, bar_y + 64))
