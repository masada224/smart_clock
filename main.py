# -*- coding: utf-8 -*-
"""
スマートデスククロック メインエントリーポイント

実行方法:
    python3 main.py

Raspberry Pi実機(コンソールのみ/X無し)で動かす場合は、SDLのビデオ
ドライバをKMS/DRMに向けると良い(環境変数は起動シェルスクリプト側で設定):
    export SDL_VIDEODRIVER=kmsdrm
"""
import sys
from datetime import datetime

import pygame

import config
import widgets
from aircon import AirconController
from card_strip import Card, CardStrip
from weather_openmeteo import WeatherOpenMeteo
from sensor_dht11 import DHT11Sensor
from sensor_pir import PIRSensor
from ir_control import IRController
from input_buttons import Buttons
from input_rotary import RotaryEncoder
from light_control import LightController


def _create_media_source():
    """config.MEDIA_SOURCEに応じてUSB(PC連携)/Bluetoothのどちらを使うか選択する。"""
    if config.MEDIA_SOURCE == "usb":
        from media_usb import USBMedia
        return USBMedia()
    else:
        from media_bluetooth import BluetoothMedia
        return BluetoothMedia()


def main():
    pygame.init()
    pygame.mouse.set_visible(False)

    #flags = pygame.FULLSCREEN if config.FULLSCREEN else 0
    flags = 0
    screen = pygame.display.set_mode((config.SCREEN_WIDTH, config.SCREEN_HEIGHT), flags)
    pygame.display.set_caption("Smart Desk Clock")
    clock = pygame.time.Clock()

    fonts = widgets.load_fonts()

    weather = WeatherOpenMeteo()
    weather.start()
    # 起動直後から表示できるよう、最初の1回だけ同期的に取得しておく
    try:
        weather._fetch_and_parse()
    except Exception:
        pass

    sensor = DHT11Sensor()
    sensor.start()

    # 人を検知したらデスク照明を点灯させる(消灯までの時間はconfig側で調整)
    light = LightController()
    pir = PIRSensor(light=light)
    pir.start()

    ir = IRController()
    aircon = AirconController(ir)

    media = _create_media_source()
    media.start()

    # 物理スイッチ: 曲送り/曲戻し
    buttons = Buttons({
        config.BUTTON_PREV_GPIO_PIN: media.previous_track,
        config.BUTTON_NEXT_GPIO_PIN: media.next_track,
    })
    buttons.start()

    # ロータリーエンコーダー: 回すと音量、押すとミュート
    encoder = RotaryEncoder(
        on_rotate=media.adjust_volume,
        on_press=media.toggle_mute,
    )
    encoder.start()

    strip = _create_card_strip(weather, sensor, media, pir, aircon)

    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                else:
                    strip.handle_event(event)

            now = datetime.now()
            dt = clock.get_time() / 1000.0   # 前フレームからの経過秒
            strip.update(dt)

            screen.fill(config.BLACK)
            widgets.draw_clock_panel(screen, fonts, now)
            strip.draw(screen, fonts)

            pygame.display.flip()
            clock.tick(config.FPS)
    finally:
        encoder.stop()
        buttons.stop()
        weather.stop()
        sensor.stop()
        pir.stop()
        light.close()   # 終了時は必ず消灯しておく
        ir.close()
        media.stop()
        pygame.quit()


def _create_card_strip(weather, sensor, media, pir, aircon):
    """config.CARD_ORDERの順にカードを並べた、横スクロールできる帯を作る。

    各カードの描画関数は「その時点の最新のスナップショット」を毎フレーム
    get()で取り直す。データソース側は別スレッドで動いているため、
    描画側はブロックせずに最新の値を読める。
    """
    # タップしたボタンを1フレームだけ押下表示にするための保持場所
    pressed = {"name": None, "until": 0.0}

    def draw_aircon(screen, fonts, rect):
        name = pressed["name"] if pygame.time.get_ticks() < pressed["until"] else None
        widgets.draw_aircon_panel(screen, fonts, rect, aircon.get(), pressed_name=name)

    def tap_aircon(local_pos):
        # aircon_button_rectsは画面座標で矩形を返すため、原点を合わせて呼ぶ
        base = pygame.Rect(0, 0, config.CARD_WIDTH, config.CARD_HEIGHT)
        for name, btn in widgets.aircon_button_rects(base, aircon.get()["presets"]):
            if btn.collidepoint(local_pos):
                aircon.send(name)
                pressed["name"] = name
                pressed["until"] = pygame.time.get_ticks() + 250
                return True
        return False

    builders = {
        "weather": lambda: Card(
            "weather",
            lambda screen, fonts, rect: widgets.draw_weather_panel(
                screen, fonts, rect, weather.get(), sensor.get()
            ),
        ),
        "media": lambda: Card(
            "media",
            lambda screen, fonts, rect: widgets.draw_media_panel(
                screen, fonts, rect, media.get()
            ),
        ),
        "aircon": lambda: Card("aircon", draw_aircon, on_tap=tap_aircon),
        "light": lambda: Card(
            "light",
            lambda screen, fonts, rect: widgets.draw_light_panel(screen, fonts, rect, pir.get()),
        ),
    }

    cards = [builders[key]() for key in config.CARD_ORDER if key in builders]
    viewport = pygame.Rect(
        config.MARGIN,
        config.CARD_TOP_Y,
        config.SCREEN_WIDTH - config.MARGIN * 2,
        config.CARD_HEIGHT,
    )
    return CardStrip(cards, viewport)


if __name__ == "__main__":
    main()
    sys.exit(0)
