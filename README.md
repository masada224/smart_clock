# スマートデスククロック (Raspberry Pi Zero 2W + Pygame)

5インチ 800x480 タッチパネル向けのデスククロックです。
時計・日付に加えて、横スクロールするカード帯に天気予報・室温湿度・
再生中の曲・エアコン操作・デスク照明の状態を表示します。

物理的な操作系として、ロータリーエンコーダー(PCの音量調整)、
タクトスイッチ(曲送り/曲戻し)、人感センサー(照明の自動点灯)、
赤外線送受信(エアコンのリモコン学習と送信)を備えています。

```
smart_clock/
├── main.py                  # エントリーポイント。各データソースと入力を起動し描画ループを回す
├── config.py                # 設定を集約(ピン番号・レイアウト・色・カード順序)
├── config_local.example.py  # 環境ごとの設定の雛形(緯度経度など)
│
├── widgets.py               # 各パネルの描画
├── card_strip.py            # カードの横スクロールとタッチ操作
│
├── weather_openmeteo.py     # Open-Meteo APIから天気予報を取得(複数モデルを平均)
├── sensor_dht11.py          # DHT11から室温・湿度を取得
│
├── media_usb.py             # USB接続PCからシリアル経由で再生中メタデータを取得(既定)
├── media_bluetooth.py       # BlueZのD-Bus経由でBluetooth再生メタデータを取得(代替)
│
├── ir_receiver.py           # 赤外線リモコンの信号を学習(CLIも兼ねる)
├── ir_codes.py              # 学習した波形をJSONで保存/読み出し
├── ir_control.py            # 赤外線を送信
├── aircon.py                # エアコンの操作状態を保持
│
├── sensor_pir.py            # 人感センサー。検知結果に応じて照明を制御
├── light_control.py         # MOSFET経由でUSB給電のLEDライトをON/OFF
│
├── input_rotary.py          # ロータリーエンコーダー(音量/ミュート)
├── input_buttons.py         # タクトスイッチ(曲送り/曲戻し)
│
├── systemd/smart-clock.service
├── usb_media_bridge/
│   ├── pc_sender/win_media_sender.py   # Windows PC側: 送信スクリプト
│   └── pi_receiver/README.md           # Pi側: USBガジェット設定手順
└── assets/fonts/            # 日本語フォント(Noto Sans JP / Shippori Mincho)
```

## 設計上のポイント

**ハードウェアが無くても動く。**
GPIO・センサー・pigpioに依存するモジュールはすべて import を `try/except ImportError` で
包み、`HARDWARE_AVAILABLE` フラグでフォールバック動作に切り替わります。
そのためプロジェクト全体が普通のPC上でそのまま起動でき、画面のレイアウトや
カードのスクロール挙動をラズパイ無しで開発・確認できます。
pigpio系のモジュールは、importに成功しても `pigpiod` が起動していない場合
(`pi.connected` が False)も同様に退避します。

**データソースは共通の形をしている。**
天気・室温・メディア・人感センサーはいずれも「デーモンスレッドを持ち、
内部状態を `threading.Lock` で守り、`get()` でプレーンな辞書のスナップショットを返す」
という同じ構造です。描画ループは `get()` を呼ぶだけでよく、I/Oでブロックしません。

**再生元は実行時に差し替えられる。**
`USBMedia` と `BluetoothMedia` は同一のインターフェースを持つため、
`config.MEDIA_SOURCE` を変えるだけで `main.py` も `widgets.py` も変更不要です。
USB経由ではアルバムアートとPCの音量を扱えますが、AVRCPには該当する機能が
無いため、Bluetooth側は `artwork` 無し・`volume: None` を返し、
描画側がそれを見てプレースホルダー表示や音量バッジの非表示に切り替えます。

**赤外線は一方通行であることを画面に反映している。**
IRは送信しかできず、エアコンの実際の状態を読み取る手段がありません。
そのため `aircon.py` が保持しているのは「最後に送った内容」でしかなく、
カードの表示も「最後に送信: 冷房26度」という書き方に統一しています。

**文字の位置合わせはフォントボックスではなく字面(インク)基準。**
コロンの点や漢字はフォントボックス内で下寄りに描かれるため、
`get_height()/2` で中央に揃えると見た目がずれます。
`get_bounding_rect()` で実際に描画されるピクセルの範囲を測って揃えており、
計算結果は分単位・日単位でキャッシュしています。

**ロータリーエンコーダーはグレイコードで復号している。**
片方の相だけを見る実装では接点のバタつきで誤カウントするため、
A相B相2bitの状態遷移表で判定し、不正な遷移(2bit同時変化)は破棄します。
EC11のデテント1クリック=4遷移を1ステップにまとめています。

**メモリ使用量(実測)**

| 段階 | RSS |
|---|---|
| pygame初期化 + 画面確保 | 31.8 MB |
| フォント9個の読み込み | +2.1 MB |
| 定常動作時(アルバムアート表示中) | **52.6 MB** |

6300フレーム連続描画(曲の切り替えとスワイプを混ぜた状態)での増加は
+0.32MB で、キャッシュ類も件数が増えないことを確認しています。
Raspberry Pi Zero 2W 実機ではAdafruit Blinkaの読み込み分が加わり、
80〜110MB 程度になる見込みです。RAM 512MB のうちCMAを除いた実質440MBに対して
**Raspberry Pi OS Lite** であれば十分な余裕があります。

## 1. 事前準備 (OS)

Raspberry Pi OS **Lite** (Bookworm推奨) をセットアップしてください。
Desktop版でも動きますが、デスクトップ環境が200〜300MB使うため余裕がなくなります。

`raspi-config` で以下を確認します。

- Interface Options > SSH (リモート作業用、任意)
- 画面出力先の設定(5インチHDMI/DSIパネルのドライバ設定は購入したパネルの
  資料に従ってください。多くの800x480汎用HDMIパネルは `config.txt` に
  `hdmi_cvt=800 480 60 6 0 0 0` 等の追記が必要です)

## 2. インストール

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv python3-dbus python3-gi \
    libgpiod2 fonts-noto-cjk bluez bluez-alsa-utils \
    git pigpio python3-pigpio

git clone https://github.com/masada224/smart_clock.git ~/smart_clock
cd ~/smart_clock
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements.txt
```

`--system-site-packages` を付けるのは、aptで入れた `python3-dbus` と
`python3-pigpio` をvenv内から使うためです。

### pigpiod の起動とリモートソケットの無効化

GPIO・赤外線・照明・エンコーダー・スイッチはすべて pigpio を使います。

```bash
sudo systemctl enable --now pigpiod
```

**既定のままでは pigpiod がTCP 8888番を全インターフェースで待ち受け、
認証なしで誰でもGPIOを操作できてしまいます。**
このプロジェクトはlocalhost接続しか使わないので、リモートソケットは無効化してください。

```bash
sudo systemctl edit pigpiod
```

開いたファイルに以下を記述して保存します。

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/pigpiod -l
```

```bash
sudo systemctl restart pigpiod
ss -lntp | grep 8888    # 127.0.0.1:8888 のみになっていることを確認
```

## 3. 環境ごとの設定 (config_local.py)

緯度経度のようなリポジトリに残したくない値や、開発PCとラズパイで異なる値は
`config_local.py` に分離します。このファイルは `.gitignore` に入っています。

```bash
cp config_local.example.py config_local.py
nano config_local.py
```

```python
LATITUDE = 35.xxxx      # 天気予報を取得したい地点
LONGITUDE = 136.xxxx
```

`config.py` の末尾でこのファイルを読み込み、そこまでの定数を上書きします。
ファイルが無い場合は既定値のまま起動するため、cloneした直後でも動きます
(ただし緯度経度は東京駅のプレースホルダーになっています)。

開発用PCでは以下のように上書きすると便利です。

```python
FULLSCREEN = False              # ウィンドウ表示(Escで終了)
USB_MEDIA_SERIAL_PORT = "COM5"  # Windowsのポート名
```

## 4. 配線

GPIOはすべてBCM番号です。変更したい場合は `config.py` の該当する定数を編集します。

| GPIO | 物理ピン | 用途 |
|---|---|---|
| 4 | 7 | DHT11 データ |
| 5 | 29 | タクトスイッチ(曲戻し) |
| 6 | 31 | タクトスイッチ(曲送り) |
| 17 | 11 | 赤外線 送信 |
| 18 | 12 | 照明 MOSFETゲート |
| 22 | 15 | 赤外線 受信 |
| 23 / 24 | 16 / 18 | ロータリーエンコーダー A相 / B相 |
| 25 | 22 | ロータリーエンコーダー 押しスイッチ |
| 27 | 13 | 人感センサー 出力 |

電源は用途ごとに分けます。**人感センサーと赤外線LEDのみ5V**、
IR受信モジュールとエンコーダーは**必ず3.3V**から取ってください
(5Vだと出力が3.3Vを超えてGPIOを傷めます)。

### DHT11

```
VCC  -> 3.3V
GND  -> GND
DATA -> GPIO4
```

素子単体の場合はDATA-VCC間に4.7k〜10kΩのプルアップ抵抗が必要です
(基板付きモジュールは内蔵済み)。

### タクトスイッチ

片側をGPIOへ、もう片側をGNDへ繋ぎます。内蔵プルアップを使うため抵抗は不要です。

足が4本あるタイプは、**同じ側から出ている2本が内部で繋がっています**。
その2本を使うとGPIOがGNDに直結され「押しっぱなし」と同じ状態になり反応しません。
向かい合う側から1本ずつ(対角)選んでください。
ブレッドボードでは中央の溝をまたぐ向きに挿せば自動的に正しくなります。

`python3 input_buttons.py` を実行すると、押す前に各ピンのレベルを表示して
この配線ミスを指摘します。

### 赤外線 送信

IR LEDをGPIOに直結してはいけません(GPIOが出せるのは16mA程度で飛距離が出ず、
無理に流すとGPIOが壊れます)。トランジスタで5Vから駆動します。

```
5V ── IR LED ──[33Ω]── コレクタ
GPIO17 ──[330Ω]── ベース    (2N2222 / S8050 等のNPN)
GND ─────────────  エミッタ
```

### 照明 (USB給電のLEDライト)

NチャンネルMOSFETによるローサイドスイッチでGND側を切ります。

- MOSFETは**ロジックレベル品**を使うこと(`AO3400` / `IRLML2502` など)。
  よく売られている `IRF520` モジュールはロジックレベルではなく、
  3.3Vのゲート電圧では完全にONにならず発熱します。
- ゲートに**10kΩのプルダウンが必須**です。Piの起動中GPIOは不定になるため、
  無いと電源投入のたびにライトが点灯します。
- ライトはPiの5Vからではなく**独立したUSB充電器**から給電してください。
  PiはUSBシリアルガジェットでPCと繋がっておりGNDが共通なので、
  ライトをPCのUSBポートに挿すとGNDがPC経由で回り込み、MOSFETで切れなくなります。

色温度を変えられるライトなど、内部にコントローラーを持つ製品はPWM調光すると
誤動作します。その場合は `config.LIGHT_FADE_SEC = 0` にしてON/OFFのみで使ってください。

## 5. 再生中メタデータの取得設定

`config.py` の `MEDIA_SOURCE` で切り替えます
(`"usb"` = USB接続したPCから取得 / `"bluetooth"` = Bluetooth AVRCPから取得)。

### 5-1. USB接続PCから取得する場合 (既定)

WindowsのSMTC (System Media Transport Controls) から再生中の曲情報を読み、
USBシリアル経由でPiへ送ります。**アルバムアートとPCの音量も取得できます。**
Pi側をUSBシリアルガジェットとして動かす設定は
`usb_media_bridge/pi_receiver/README.md` を参照してください。

PC側:

```bash
cd usb_media_bridge/pc_sender
pip install -r requirements.txt
python win_media_sender.py
```

`pycaw` が入っていれば音量の取得と設定ができ、Piの画面にも音量が表示されます。
未インストールの場合は仮想キー送出にフォールバックし、操作はできますが
音量の数値は表示されません。

通信プロトコルは改行区切りのJSONです(詳細は `media_usb.py` のdocstring)。
Pi側からは `{"type": "control", "action": ...}` を送り返して
再生操作と音量調整を行います。

Pi側の単体テスト:

```bash
python3 media_usb.py
```

### 5-2. Bluetoothから取得する場合

```bash
sudo systemctl enable --now bluetooth
bluetoothctl
  power on
  agent on
  default-agent
  discoverable on
  pairable on
  # スマートフォン側からPiを選んでペアリング
  pair <スマホのMACアドレス>
  trust <スマホのMACアドレス>
  connect <スマホのMACアドレス>
```

**制限:** AVRCP標準にはジャケット画像が含まれないため、アルバムアートは
プレースホルダー表示になります。音量制御も対象がPi自身の出力になってしまうため
無効にしてあります。

## 6. エアコンのリモコン学習

エアコンのリモコンは、テレビと違って「温度+1」のような差分ではなく
**電源・運転モード・設定温度・風量をまとめた1フレーム**(100〜300bit超)を
毎回送信します。そのため「温度アップ」だけを学習することはできず、
使いたい状態ごとに1つずつ学習して名前を付けて保存します。

```bash
python3 ir_receiver.py 冷房26度      # 受信部にリモコンを向けてボタンを押す
python3 ir_receiver.py 冷房26度 -n   # 保存せず波形の解析結果だけ表示
python3 ir_receiver.py --list
python3 ir_receiver.py --delete 冷房26度
```

保存した信号は `ir_codes.json` に入り、エアコンカードのボタンとして並びます。
コマンドラインからも送信できます。

```bash
python3 ir_control.py 冷房26度
```

`-n` を付けたときに表示される推定bit数とビット列を見ると、そのリモコンが
どういう構造で信号を送っているか(温度がどのビットに対応しているか等)を
調べることができます。

## 7. 動作確認

各モジュールは単体で実行できます。ハードウェアを1つ繋ぐごとに確認するのが確実です。

```bash
python3 input_buttons.py         # スイッチ。押すと1回ずつ表示。配線ミスも検出する
python3 input_rotary.py          # エンコーダー。回転と押し込みを表示
python3 ir_receiver.py テスト -n  # 赤外線受信。ビット列が出れば正常
python3 sensor_pir.py            # 人感センサー(起動後1分は誤検知するので待つ)
python3 light_control.py         # 照明の点灯/消灯
python3 sensor_dht11.py          # 室温・湿度
python3 weather_openmeteo.py     # 天気予報の取得
python3 media_usb.py             # PCからの再生情報の受信
```

すべて確認できたら本体を起動します。

```bash
source venv/bin/activate
python3 main.py
```

カードは左右のスワイプで切り替わり、エアコンカードのボタンはタップで反応します。
`config.CARD_ORDER` で表示するカードと順序を変更できます。

## 8. 自動起動設定 (systemd)

```bash
sudo cp systemd/smart-clock.service /etc/systemd/system/
sudo nano /etc/systemd/system/smart-clock.service   # User/WorkingDirectoryを実環境に合わせる
sudo systemctl daemon-reload
sudo systemctl enable --now smart-clock.service
```

GPIO操作はpigpiodを経由するため、**このサービスをrootで動かす必要はありません。**
一般ユーザーのまま実行してください。

コンソールのみ(X無し)の環境では `SDL_VIDEODRIVER=kmsdrm` で直接描画します。
映らない場合は `SDL_VIDEODRIVER=fbcon` + `SDL_FBDEV=/dev/fb0` に切り替えてください
(サービスファイルに両方コメントで用意してあります)。

## 既知の制約・今後の改善ポイント

- **エアコンの状態は取得できません。** 赤外線は一方通行のため、リモコン本体で
  直接操作された場合は画面の表示とずれます。
- 天気アイコンは WMO weather_code を4種類(晴れ/曇り/雨/晴れ時々曇り)に
  単純化しています。雪の区別が必要であれば `_WMO_ICON_MAP` に追加してください。
- DHT11は精度・応答速度の低いセンサーです。BME280やSHT31に差し替える場合は
  `sensor_dht11.py` と同じ `get()` インターフェースで作れば `main.py` の変更は不要です。
- USB連携はシリアル1本の簡易プロトコルのため、大きいアートワークは転送に
  時間がかかります(PC側の `ARTWORK_MAX_BYTES` で上限を設定)。
- タッチ操作はSDL2がタッチをマウスイベントとして通知することを利用しています。
  そのため開発PCのマウスでも実機のタッチパネルでも同じコードで動作します。
