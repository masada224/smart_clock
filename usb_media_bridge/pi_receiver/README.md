# Raspberry Pi側: USBシリアルガジェット(CDC-ACM)セットアップ

Raspberry Pi Zero 2WのUSB(OTG)ポートをPCから見て「シリアルポート(COMポート)」
として認識させるための設定です。これにより、電源供給と通信を1本のUSBケーブルで
兼用できます。

## 1. dwc2オーバーレイとg_serialモジュールを有効化

`/boot/firmware/config.txt` (Bookwormより前は `/boot/config.txt`) の末尾に追記:

```
dtoverlay=dwc2
```

`/boot/firmware/cmdline.txt` (同上、古い場合は `/boot/cmdline.txt`) を編集し、
`rootwait` の直後に以下を追記(1行のまま、改行しないこと):

```
modules-load=dwc2,g_serial
```

例:
```
console=serial0,115200 console=tty1 root=PARTUUID=xxxx-xx rootfstype=ext4 fsck.repair=yes rootwait modules-load=dwc2,g_serial
```

## 2. USBケーブルの接続先を確認

Raspberry Pi Zero 2Wには micro USBポートが2つありますが、**"USB"とだけ
印字されている方(電源専用ではない方、OTG対応ポート)** をPCと接続してください。
`PWR IN` と印字されている方に挿しても給電のみでガジェットは有効になりません。

## 3. 再起動して確認

```bash
sudo reboot
```

再起動後、以下のデバイスファイルが存在すればOKです。

```bash
ls -l /dev/ttyGS0
```

`config.py` の `USB_MEDIA_SERIAL_PORT` は `/dev/ttyGS0` を既定値にしています。

## 4. パーミッション

pi (または実行ユーザー) を dialout グループに入れておくと、
sudoなしで `/dev/ttyGS0` にアクセスできます。

```bash
sudo usermod -aG dialout pi
```
(再ログインまたは再起動が必要)

## 5. Windows側の確認

上記設定後にUSBケーブルをWindows PCへ接続すると、通常は標準ドライバ
(usbser.sys)で自動的にCOMポートとして認識されます。
「デバイスマネージャー」→「ポート(COMとLPT)」に
`USB Serial Device (COMxx)` のように表示されるはずです。
そのCOM番号を `pc_sender/win_media_sender.py` の `SERIAL_PORT` に設定してください。

もし認識されない場合は、Piを一度再起動してから接続し直す、
別のUSBケーブル(データ通信対応のもの、充電専用ケーブルは不可)を試す、
などを確認してください。

## 6. 動作テスト

Pi側:
```bash
cd ~/smart_clock
source venv/bin/activate
python3 media_usb.py
```

PC側(別途 `pip install winsdk pyserial` 済みであること):
```powershell
cd usb_media_bridge\pc_sender
pip install -r requirements.txt
python win_media_sender.py
```

PC側で何か音楽(Spotify等)を再生した状態で、Pi側のターミナルに
曲名・アーティスト・アルバム・アートワーク有無が出力されれば成功です。

## 参考: USB Gadgetのもう一つの選択肢 (g_ether)

シリアルの代わりにUSBネットワークガジェット(`g_ether`)を使い、
PCとPiの間にUSB経由のプライベートIPネットワークを作ってHTTP/WebSocketで
通信する方法もあります。この方法は大きな画像データのやり取りや、
将来的にWeb管理画面を追加したい場合に有利ですが、Windows側に
RNDIS/NCMドライバの認識問題が起きることがあり、今回は環境依存の少ない
CDC-ACM(シリアル)方式を採用しています。`g_ether`化したい場合は
`dtoverlay=dwc2` はそのままに、`modules-load=dwc2,g_ether` へ変更し、
Pi側で `usb0` インターフェースに静的IPを振ってください。
