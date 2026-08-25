# Raspberry Pi側: USBシリアルガジェット(CDC-ACM)セットアップ

Raspberry Pi Zero 2WのUSB(OTG)ポートをPCから見て「シリアルポート(COMポート)」
として認識させるための設定。これで電源供給と通信を1本のUSBケーブルで兼用できる。

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

Raspberry Pi Zero 2Wには micro USBポートが2つある。**"USB"とだけ
印字されている方(電源専用ではない方、OTG対応ポート)** をPCと繋ぐこと。
`PWR IN` の方に挿しても給電だけでガジェットは有効にならない。

## 3. 再起動して確認

```bash
sudo reboot
```

再起動後、以下のデバイスファイルがあればOK。

```bash
ls -l /dev/ttyGS0
```

`config.py` の `USB_MEDIA_SERIAL_PORT` は `/dev/ttyGS0` が既定値。

## 4. パーミッション

実行ユーザーを dialout グループに入れておくと、sudoなしで `/dev/ttyGS0` に
アクセスできる。

```bash
sudo usermod -aG dialout pi
```
(再ログインまたは再起動が必要)

## 5. Windows側の確認

設定後にUSBケーブルをWindows PCへ挿すと、普通は標準ドライバ(usbser.sys)で
自動的にCOMポートとして認識される。
「デバイスマネージャー」→「ポート(COMとLPT)」に
`USB Serial Device (COMxx)` のように出るはず。
そのCOM番号を `pc_sender/win_media_sender.py` の `SERIAL_PORT` に設定する。

認識されないときは、Piを一度再起動してから挿し直す、別のUSBケーブル
(データ通信対応のもの。充電専用ケーブルは不可)を試す、あたりを疑う。

## 6. 動作テスト

Pi側:
```bash
cd ~/smart_clock
source venv/bin/activate
python3 media_usb.py
```

PC側(先に `pip install winsdk pyserial` 済みであること):
```powershell
cd usb_media_bridge\pc_sender
pip install -r requirements.txt
python win_media_sender.py
```

PC側で何か音楽(Spotify等)を再生した状態で、Pi側のターミナルに
曲名・アーティスト・アルバム・アートワーク有無が出れば成功。

## 参考: USB Gadgetのもう一つの選択肢 (g_ether)

シリアルの代わりにUSBネットワークガジェット(`g_ether`)を使い、
PCとPiの間にUSB経由のプライベートIPネットワークを作ってHTTP/WebSocketで
通信する方法もある。大きな画像データのやり取りや、将来Web管理画面を
追加したい場合はそちらが有利。ただしWindows側でRNDIS/NCMドライバの
認識問題が起きることがあるので、今回は環境依存の少ない
CDC-ACM(シリアル)方式にした。`g_ether`にしたい場合は
`dtoverlay=dwc2` はそのままに `modules-load=dwc2,g_ether` へ変え、
Pi側で `usb0` インターフェースに静的IPを振る。
