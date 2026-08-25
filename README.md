# スマートデスククロック (Raspberry Pi Zero 2W + Pygame)

5インチ 800x480 ディスプレイ向けの、時計・天気予報(Open-Meteo)・
DHT11室温湿度・再生中メタデータ(USB連携 or Bluetooth)を表示するデスククロックです。

```
smart_clock/
├── main.py                # エントリーポイント(config.MEDIA_SOURCEで再生元を切替)
├── config.py               # 各種設定(ここを一番よく編集する)
├── weather_openmeteo.py    # Open-Meteo APIから天気予報を取得
├── sensor_dht11.py          # DHT11から室温・湿度を取得
├── media_usb.py             # USB接続PCからシリアル経由で再生中メタデータを取得(既定)
├── media_bluetooth.py       # BlueZのD-Bus経由でBluetooth再生メタデータを取得(代替)
├── widgets.py                # 画面描画
├── requirements.txt
├── systemd/smart-clock.service
├── usb_media_bridge/
│   ├── pc_sender/win_media_sender.py   # Windows PC側: 送信スクリプト
│   └── pi_receiver/README.md           # Pi側: USBガジェット設定手順
└── assets/fonts/             # 日本語フォントを置く場所(要ダウンロード)
```

再生中メタデータの取得元は `config.py` の `MEDIA_SOURCE` で切り替えます
(`"usb"` = USB接続したPCから取得 / `"bluetooth"` = Bluetooth AVRCPから取得)。

## 1. 事前準備 (OS)

Raspberry Pi OS (Bookworm推奨、Lite/Desktopどちらでも可) をセットアップし、
`raspi-config` で以下を有効化してください。

- Interface Options > SSH (リモート作業用、任意)
- 画面出力先が正しいか (5インチHDMI/DSIパネルのドライバ設定は購入したパネルの
  資料に従ってください。多くの800x480汎用HDMIパネルはconfig.txtの
  `hdmi_cvt=800 480 60 6 0 0 0` 等の追記が必要です)

## 2. パッケージインストール

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv python3-dbus python3-gi \
    libgpiod2 fonts-noto-cjk bluez bluez-alsa-utils

cd ~
git clone <このプロジェクトを転送した場所> smart_clock   # あるいはscp/USBで転送
cd smart_clock
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements.txt
```

`--system-site-packages` を付けるのは `python3-dbus` をaptで入れたものを
venv内から使うためです。

## 3. 日本語フォントの配置

`assets/fonts/` に以下のいずれかの方法でフォントを置いてください。

- 簡単な方法: 上記で `fonts-noto-cjk` をaptで入れているので、
  `config.py` の `FONT_REGULAR` 等を以下のシステムパスに直接書き換えてもOKです。
  ```
  /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
  ```
- 推奨: [Noto Sans JP](https://fonts.google.com/noto/specimen/Noto+Sans+JP) の
  Regular / Bold / Black を `assets/fonts/NotoSansJP-Regular.ttf` などの
  ファイル名でダウンロードして配置(可変フォントより静的(static)版が確実)。
  未配置の場合は自動でシステムフォントにフォールバックしますが、
  日本語が文字化けする可能性があります。

## 4. DHT11の配線

```
DHT11        Raspberry Pi Zero 2W
VCC   ------ 3.3V (モジュール基板に3.3V対応と明記されているもの)
GND   ------ GND
DATA  ------ GPIO4 (config.py の DHT11_GPIO_PIN で変更可)
```

基板なしの素子単体を使う場合はDATA-VCC間に4.7k〜10kΩのプルアップ抵抗が必要です。
基板付きモジュールは大抵内蔵済みです。

単体テスト:
```bash
python3 sensor_dht11.py
```

## 5. 再生中メタデータの取得設定 (USB連携 / Bluetooth)

### 5-1. USB接続PCから取得する場合 (既定: `config.MEDIA_SOURCE = "usb"`)

Windows PCとUSBケーブルで接続し、PC側の常駐スクリプトが再生中の曲情報を
Pi側へ送信する方式です。セットアップ手順は
`usb_media_bridge/pi_receiver/README.md` を参照してください
(Pi側をUSBシリアルガジェットとして動かす設定と、
Windows側の `win_media_sender.py` の使い方を説明しています)。

単体テスト(PC側で `win_media_sender.py` を起動しながら):
```bash
python3 media_usb.py
```

この方式はタイトル・アーティスト・アルバムに加えて、**アルバムアート画像も
取得できます**(Windows.Media.Control APIがサムネイルを提供するアプリの場合)。

### 5-2. Bluetoothから取得する場合 (`config.MEDIA_SOURCE = "bluetooth"`)

スマートフォン等からPiに音声出力(A2DP)しつつ、AVRCPで再生中の曲情報を
受け取れるようにペアリングします。

```bash
sudo systemctl enable --now bluetooth
bluetoothctl
  power on
  agent on
  default-agent
  discoverable on
  pairable on
  # ここでスマートフォン側からPiのBluetooth名を選んでペアリング要求を送る
  # (Piの画面にペアリングコードが出ないので、スマホ側の確認だけで進む場合が多い)
  # 接続要求が来たら:
  pair <スマホのMACアドレス>
  trust <スマホのMACアドレス>
  connect <スマホのMACアドレス>
```

`trust` しておくと次回以降は自動で再接続されます。A2DPの音声そのものを
Piのスピーカーから鳴らしたい場合は `bluez-alsa-utils` (先ほどインストール済み)の
`bluealsa` / `bluealsa-aplay` を有効化してください(音声出力が不要で
再生メタデータの表示だけで良い場合はこの手順は省略可能です)。

単体テスト(スマホ側で何か再生しながら):
```bash
python3 media_bluetooth.py
```
**制限事項:** AVRCP標準にはジャケット画像(アルバムアート)が含まれないため、
Bluetooth経由の場合はアルバムアートはプレースホルダー表示になります
(アートワークが必要な場合は5-1のUSB連携を使ってください)。

## 6. 天気予報 (Open-Meteo API) について

`config.py` の `LATITUDE` / `LONGITUDE` は現在「名古屋」向けに設定済みです。
他地域で使う場合は緯度経度を書き換えてください。

`WeatherOpenMeteo` は `models=jma_seamless`(気象庁の高解像度モデル)を指定して
[Open-Meteo API](https://open-meteo.com/en/docs) から取得しています。
APIキーは不要です。天気アイコンはOpen-MeteoのWMO weather_codeから
簡易マッピングしているため、より細かく調整したい場合は
`weather_openmeteo.py` の `_WMO_ICON_MAP` を編集してください。

動作確認:
```bash
python3 weather_openmeteo.py
```

## 7. 動作確認

```bash
source venv/bin/activate
python3 main.py
```

開発中(PCモニタ等)は `config.py` の `FULLSCREEN = False` にすると
ウィンドウ表示になります。`Esc`キーで終了できます。

## 8. 自動起動設定 (systemd)

```bash
sudo cp systemd/smart-clock.service /etc/systemd/system/
sudo nano /etc/systemd/system/smart-clock.service   # User/WorkingDirectoryのパスを実環境に合わせる
sudo systemctl daemon-reload
sudo systemctl enable --now smart-clock.service
```

コンソールのみ(X無し)のRaspberry Pi OS Liteでは `SDL_VIDEODRIVER=kmsdrm` で
直接フレームバッファに描画します。うまく映らない場合は
`SDL_VIDEODRIVER=fbcon` + `SDL_FBDEV=/dev/fb0` に切り替えてください
(サービスファイル内にコメントで両方用意してあります)。

タッチパネル対応の5インチディスプレイなら、再生/前へ/次への3つの
ボタンをタップで操作できます(`main.py` が `FINGERDOWN` イベントに対応済み)。

## 既知の制約・今後の改善ポイント

- 天気アイコンのマッピング(`weather_openmeteo.py`の`_WMO_ICON_MAP`)は
  WMOコードを4種類のアイコン(晴れ/曇り/雨/晴れ時々曇り)に単純化した
  簡易実装です。雪の視覚的な区別が必要であれば専用の雪アイコンを追加してください。
- DHT11は精度・応答速度が低いセンサーです。より高精度にしたい場合は
  BME280やSHT31への差し替えを推奨します(`sensor_dht11.py`を参考に
  同じインターフェース(`get()`メソッド)で作り替えれば`main.py`側の
  変更は最小限で済みます)。
- USB連携(`media_usb.py`)はシリアル回線1本での簡易プロトコルのため、
  極端に大きいアートワーク画像は送信に時間がかかります
  (`win_media_sender.py`側の`ARTWORK_MAX_BYTES`で上限を設定済み)。
- Bluetooth経由(`media_bluetooth.py`)はAVRCP標準の制約上、
  アルバムアートを取得できません。
