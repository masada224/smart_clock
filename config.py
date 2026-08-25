# -*- coding: utf-8 -*-
"""
スマートデスククロック 設定ファイル
実機の環境(GPIOピン番号、Bluetoothの状況など)に合わせてここを編集する。
"""
import os

# ----------------------------------------------------------------
# ディスプレイ設定 (5インチ 800x480 想定)
# ----------------------------------------------------------------
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480
FPS = 30

# Raspberry Pi実機でフルスクリーン起動する場合はTrue。
# PC上で開発・デバッグする場合はFalseにするとウィンドウ表示になる。
FULLSCREEN = True

# ----------------------------------------------------------------
# 色定義 (R, G, B)
# ダーク・プレミアム系: 純黒背景の上に、暗めのグレーで「浮いている」
# カードを置き、差し色(ACCENT)を1色だけ使うテーマ。
# 設置予定のデスク(木目+黒+赤色LEDライトバー、置き換え対象の時計も赤色LED)
# に馴染むよう、カードは寒色のスレートではなく暖色系の焦げ茶に寄せ、
# アクセントはメディアカードの再生済みバーと同系統の赤にしている。
# ----------------------------------------------------------------
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
CARD_BG = (40, 34, 30)        # カード本体(黒背景より少し明るい焦げ茶)
CARD_BG_ALT = (54, 46, 40)    # カード内の入れ子チップ(プレースホルダー等)用に少し明るく
CARD_BORDER = (86, 72, 60)    # カード縁の細い縁取り(黒背景の上で「浮いて」見えるように)
ACCENT = (216, 168, 92)       # 差し色(時計のコロン、降水確率グラフなど)
TEXT_PRIMARY = (238, 232, 226)   # カード上の主要テキスト(暖色寄りの白)
TEXT_SECONDARY = (166, 155, 145)  # カード上の補助テキスト(暖色寄りのグレー)
GRAPH_BG = (54, 46, 40)       # 降水確率グラフの背景パネル
BLUE = (35, 100, 225)
ORANGE = (235, 150, 35)
ICON_GRAY = (170, 170, 170)
# 天気アイコンは白い角丸ボックスの上に描くため、雪に白は使えない。
# 白地でも見える水色にする。
SNOW = (95, 165, 220)
LIGHTNING = (245, 180, 35)
THUNDER_CLOUD = (120, 120, 128)   # 雷雲は通常の雲より暗くする
TODAY_HIGHLIGHT = (245, 245, 245)

# ----------------------------------------------------------------
# フォント
# assets/fontsに配置したNoto Sans JPのウェイト違いを使い分ける
# (Google Fonts: https://fonts.google.com/noto/specimen/Noto+Sans+JP)。
# 「数字は太く、ラベルは細く」で階調を付けるとおしゃれに見えるため、
# 用途ごとにウェイトを分けている。
# ----------------------------------------------------------------
_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
FONT_THIN = os.path.join(_FONT_DIR, "NotoSansJP-Thin.ttf")
FONT_LIGHT = os.path.join(_FONT_DIR, "NotoSansJP-Light.ttf")
FONT_REGULAR = os.path.join(_FONT_DIR, "NotoSansJP-Regular.ttf")
FONT_MEDIUM = os.path.join(_FONT_DIR, "NotoSansJP-Medium.ttf")
FONT_SEMIBOLD = os.path.join(_FONT_DIR, "NotoSansJP-SemiBold.ttf")
FONT_BOLD = os.path.join(_FONT_DIR, "NotoSansJP-Bold.ttf")

# 上品なミニマル・明朝系の差し色フォント。時計の数字など、大きく目立つ
# 「主役」の要素だけに使う(小さい文字に明朝を使うと低解像度パネルでは
# 潰れて読みにくくなるため、本文/ラベルは引き続きNoto Sans JPを使う)。
FONT_SERIF_REGULAR = os.path.join(_FONT_DIR, "ShipporiMincho-Regular.ttf")
FONT_SERIF_MEDIUM = os.path.join(_FONT_DIR, "ShipporiMincho-Medium.ttf")
FONT_SERIF_SEMIBOLD = os.path.join(_FONT_DIR, "ShipporiMincho-SemiBold.ttf")
FONT_SERIF_BOLD = os.path.join(_FONT_DIR, "ShipporiMincho-Bold.ttf")
FONT_SERIF_EXTRABOLD = os.path.join(_FONT_DIR, "ShipporiMincho-ExtraBold.ttf")
FONT_BLACK = os.path.join(_FONT_DIR, "NotoSansJP-Black.ttf")
# ----------------------------------------------------------------
# 天気予報 (Open-Meteo API)
# https://open-meteo.com/en/docs
# APIキー不要。models=jma_seamless で気象庁の高解像度モデルを使用する。
# ----------------------------------------------------------------
# ここに書いてあるのは「設定されていないことが分かる」ための既定値(東京駅)。
# 実際の場所は config_local.py に書いて上書きする(このファイル末尾を参照)。
LATITUDE = 35.6812
LONGITUDE = 139.7671
WEATHER_UPDATE_INTERVAL_SEC = 30 * 60  # 30分ごとに再取得
WEATHER_SLOT_STEP_HOURS = 3            # 降水確率コマの間隔(1なら1時間おき、3なら3時間おき)

# 複数モデルの平均を取ることで、単一モデルの偏り(特に猛暑日等の極端な気温で
# 数値予報モデルが実況と数℃ずれること)を緩和する。
# 各モデルの特徴:
#   jma_seamless  - 気象庁の高解像度モデル(日本域に強い)
#   ecmwf_ifs025  - ECMWF(欧州中期予報センター)。世界的に精度評価が高い
#   gfs_seamless  - NOAA(米国)のGFSモデル。日本域では高温バイアスの傾向がある
# 1つだけにしたい場合はリストの要素を1つにすればよい。
WEATHER_MODELS = ["jma_seamless", "ecmwf_ifs025", "gfs_seamless"]

# ----------------------------------------------------------------
# DHT11 (室温・湿度センサー)
# ----------------------------------------------------------------
DHT11_GPIO_PIN = 4               # BCM番号。配線に合わせて変更すること
SENSOR_UPDATE_INTERVAL_SEC = 10  # DHT11は連続読み取りに弱いため間隔を空ける

# ----------------------------------------------------------------
# Bluetooth (MPRIS/BlueZ経由で他デバイスの再生情報を取得)
# ----------------------------------------------------------------
BT_UPDATE_INTERVAL_SEC = 1

# ----------------------------------------------------------------
# メディア(再生中の曲)情報の取得元
#   "usb"       -> USB接続したPCからシリアル経由で取得 (media_usb.py)
#   "bluetooth" -> Bluetooth(AVRCP)経由で取得 (media_bluetooth.py)
# ----------------------------------------------------------------
MEDIA_SOURCE = "usb"

# USBメディア連携 (media_usb.py)
# Raspberry Pi側がUSB CDC-ACMガジェット(g_serial)として動作している場合は
# 通常 /dev/ttyGS0。FTDI等の一般的なUSBシリアル変換の場合は /dev/ttyUSB0 等になる。
USB_MEDIA_SERIAL_PORT = "/dev/ttyGS0"
USB_MEDIA_BAUDRATE = 115200

# ----------------------------------------------------------------
# 赤外線(IR)送受信 (エアコン等のリモコン制御)
# ----------------------------------------------------------------
IR_TX_GPIO_PIN = 17          # 赤外線LED接続ピン(BCM番号)。配線に合わせて変更すること
IR_CARRIER_FREQ_HZ = 38000   # 家電リモコンで一般的な搬送波周波数
IR_CARRIER_DUTY_CYCLE = 0.33  # 搬送波のデューティ比

# IR受信 (VS1838B / TSOP38238等の受信モジュール。ir_receiver.pyで使用)
IR_RX_GPIO_PIN = 22            # 受信モジュールのOUT接続ピン(BCM番号)
IR_RX_GLITCH_FILTER_US = 100   # これより短いパルスはノイズとして無視する
# 最後のエッジからこの時間だけ変化が無ければ「1フレーム終了」とみなす。
# エアコンは同じフレームを2回繰り返して送る機種があり、そのままでは1回目
# しか取れない。学習した信号で反応しない場合はここを30000程度まで広げて
# 繰り返し分もまとめて取り込むと動くことがある。
IR_CAPTURE_GAP_US = 10000
IR_CAPTURE_TIMEOUT_SEC = 10    # この秒数だけリモコンの信号を待つ
IR_CAPTURE_MAX_EDGES = 2000    # 暴走防止の上限(エアコンは600程度まで使う)

# 学習した波形データの保存先 (ir_codes.pyが読み書きする)
IR_CODES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ir_codes.json")

# ----------------------------------------------------------------
# PIR人感センサー (HC-SR501等)
# ----------------------------------------------------------------
PIR_GPIO_PIN = 27                  # BCM番号。配線に合わせて変更すること
PIR_POLL_INTERVAL_SEC = 0.2        # 反応性を優先し短めの間隔でポーリングする
PIR_LIGHT_OFF_DELAY_SEC = 5 * 60   # 最終検知からこの秒数反応が無ければ消灯する

# ----------------------------------------------------------------
# デスク照明 (USB給電のLEDライトを、NチャンネルMOSFETでまとめてON/OFF)
#
# 接続している照明:
#   ・ダブルLED PCモニターライト (DC5V 650mA / 3.25W)
#   ・ダイソー ウォームホワイトのテープライト × 2
#   合計でおよそ1.5Aを見込み、Piではなく独立したUSB充電器から給電する。
# ----------------------------------------------------------------
LIGHT_GPIO_PIN = 18            # MOSFETのゲート接続ピン(BCM番号)
LIGHT_PWM_FREQ_HZ = 800        # ちらつきが見えない程度に高くする
LIGHT_BRIGHTNESS = 1.0         # 点灯時の明るさ (0.0〜1.0)

# モニターライトは色温度(3100K〜5000K)を変えられるタイプで、暖色/寒色2系統の
# LEDを駆動するコントローラーを内蔵している。電源をPWMで刻むと内蔵コントローラー
# 自身のPWMと干渉してちらついたり、低いデューティ比でマイコンがブラウンアウト
# したりするため、調光はせずON/OFFのみで使う。
# テープライトだけを別系統にすれば調光できるが、今は1系統にまとめている。
LIGHT_FADE_SEC = 0             # 0 = フェードなし(即座に切り替わる)

# ----------------------------------------------------------------
# ロータリーエンコーダー (EC11等) — PCの音量調整/ミュート
# 回した量・押した操作はUSBシリアル経由でPC側に送る (media_usb.py)
# ----------------------------------------------------------------
ROTARY_A_GPIO_PIN = 23        # エンコーダーのA相(CLK)
ROTARY_B_GPIO_PIN = 24        # エンコーダーのB相(DT)
ROTARY_SW_GPIO_PIN = 25       # 押し込みスイッチ(SW)。ミュート切り替えに使う
ROTARY_GLITCH_FILTER_US = 300  # 接点のチャタリング除去
# EC11系は1クリック(デテント)あたり4回状態が変化する。取りこぼしを感じる
# 場合や、1クリックで2段階動いてしまう場合はここを2や1に変える。
ROTARY_STEPS_PER_DETENT = 4

# ----------------------------------------------------------------
# 物理スイッチ — PCの曲送り/曲戻し
# ----------------------------------------------------------------
BUTTON_PREV_GPIO_PIN = 5      # 曲戻し
BUTTON_NEXT_GPIO_PIN = 6      # 曲送り
BUTTON_GLITCH_FILTER_US = 5000  # チャタリング除去(5ms)
BUTTON_REPEAT_LOCKOUT_SEC = 0.25  # 連打の誤検知を防ぐ最小間隔

# ----------------------------------------------------------------
# レイアウト
# ----------------------------------------------------------------
MARGIN = 16
TOP_HEIGHT = 200
CARD_TOP_Y = TOP_HEIGHT + MARGIN
CARD_GAP = 16
CARD_WIDTH = (SCREEN_WIDTH - MARGIN * 2 - CARD_GAP) // 2
CARD_RADIUS = 22
# カードの高さは画面下端までのマージンを残した分。ページ位置を示すドットは
# カードを縮めずに、この下マージンの余白へ重ねて描く(card_strip.py)。
CARD_HEIGHT = SCREEN_HEIGHT - CARD_TOP_Y - MARGIN

# ----------------------------------------------------------------
# カードの横スクロール(タッチ/スワイプ操作)
# ----------------------------------------------------------------
# 画面に並べるカードの順序。card_strip.pyが左からこの順に並べる。
# 使わないカードは行ごと消せばよい。
CARD_ORDER = ["weather", "media", "aircon", "light"]

# タップとスワイプの区別。指がこれ以上動いたらスワイプとみなし、
# カード内のボタンは反応させない(スクロール中の誤操作を防ぐ)。
CARD_TAP_MAX_MOVE_PX = 12
CARD_TAP_MAX_SEC = 0.6
# 指を離したあと、この速度(px/秒)以上ならフリックとして次のカードへ送る
CARD_FLICK_MIN_SPEED = 260
CARD_SNAP_SPEED = 12.0   # スナップアニメーションの追従の速さ(大きいほど速い)

# エアコンカードに並べるプリセットボタンの最大数
AIRCON_CARD_MAX_BUTTONS = 6

# ----------------------------------------------------------------
# ローカル設定の読み込み (このファイルの一番最後に置くこと)
#
# 同じフォルダに config_local.py があれば、その中身でここまでの値を上書きする。
# config_local.py は .gitignore に入れてあるためリポジトリに含まれない。
#
# 用途:
#   ・リポジトリに残したくない値      -> LATITUDE / LONGITUDE
#   ・PCとRaspberry Piで異なる値      -> FULLSCREEN, USB_MEDIA_SERIAL_PORT など
#
# 雛形は config_local.example.py。これをコピーして使う:
#   cp config_local.example.py config_local.py
#
# 注意: 他の値から計算している定数(CARD_WIDTH, CARD_HEIGHT, FONT_* など)は、
# 元になる値をここで上書きしても再計算されない。計算済みの定数そのものを
# 上書きするか、このファイルを直接編集すること。
# ----------------------------------------------------------------
try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    # config_local.py が無い場合は、ここまでの既定値をそのまま使う
    pass
