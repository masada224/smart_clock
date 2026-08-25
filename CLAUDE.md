# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A desk clock application for a Raspberry Pi Zero 2W driving a 5" 800x480 touchscreen via Pygame. It shows a clock plus a horizontally swipeable strip of cards: weather forecast (Open-Meteo), room temperature/humidity (DHT11), "now playing" metadata from a source PC (over USB serial) or a Bluetooth-paired phone (BlueZ D-Bus/AVRCP), air-conditioner IR control, and desk lighting. Physical controls (a rotary encoder for PC volume/mute, two buttons for track skip) and a PIR sensor that switches on a USB LED light bar round it out. All in-repo comments and the README are written in Japanese.

There is no build step, package manager config, linter, or test suite in this repo — it's a small collection of standalone Python scripts run directly with `python3`.

## Commands

Setup (on the Pi):
```bash
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements.txt
```
`--system-site-packages` is required so the venv can see `python3-dbus`/`python3-gi`, which must be installed via `apt` (not pip) — see `requirements.txt` comments.

Run the app:
```bash
python3 main.py
```
Set `config.FULLSCREEN = False` to run windowed for development on a PC; press `Esc` to quit.

Each data-source module is runnable standalone as a manual smoke test (each has an `if __name__ == "__main__":` block that prints what it reads, no assertions — there is no automated test runner):
```bash
python3 sensor_dht11.py          # prints temp/humidity every 3s (dummy values 26/30 off-Pi)
python3 weather_openmeteo.py     # one-shot fetch + pprint of parsed forecast
python3 media_usb.py             # reads from the configured serial port for 60s
python3 media_bluetooth.py       # polls BlueZ MediaPlayer1 for 10s
python3 sensor_pir.py            # prints motion state for 30s
python3 light_control.py         # fades the light up, to 50%, then off
python3 input_rotary.py          # prints rotation/press for 30s
python3 input_buttons.py         # prints button presses for 30s
python3 ir_control.py            # sends the dummy placeholder waveform
python3 ir_control.py 冷房26度   # sends a learned code by name
python3 aircon.py                # lists learned presets and current state
```

Learning IR remote codes (`ir_receiver.py` doubles as a CLI, not just a smoke test):
```bash
python3 ir_receiver.py 冷房26度      # point remote at receiver, press button -> saves to ir_codes.json
python3 ir_receiver.py 冷房26度 -n   # analyze the waveform without saving
python3 ir_receiver.py --list
python3 ir_receiver.py --delete 冷房26度
```
`pigpiod` must be running for every pigpio-based module (`ir_control`, `ir_receiver`, `light_control`, `input_rotary`, `input_buttons`): `sudo systemctl enable --now pigpiod`.

Deploy as a systemd service: copy `systemd/smart-clock.service` to `/etc/systemd/system/`, fix `User`/`WorkingDirectory` for the real environment, then `systemctl daemon-reload && systemctl enable --now smart-clock.service`.

## Architecture

**Entry point and main loop** (`main.py`): initializes Pygame, loads fonts via `widgets.load_fonts()`, starts the background-thread data sources (`WeatherOpenMeteo`, `DHT11Sensor`, `PIRSensor`, and a media source) plus the physical inputs (`RotaryEncoder`, `Buttons`), builds the card strip in `_create_card_strip()`, then runs a `pygame.time.Clock`-throttled loop (`config.FPS`) that forwards events to the strip, advances its snap animation with `update(dt)`, and draws the clock panel + the strip. Each card's draw closure calls its source's `get()` every frame, so the render loop never blocks on I/O.

**Background source pattern**: every data-source class (`WeatherOpenMeteo`, `DHT11Sensor`, `USBMedia`, `BluetoothMedia`) follows the same shape — a daemon thread started by `start()`/stopped by `stop()`, internal state guarded by a `threading.Lock`, and a `get()` method that returns a plain-dict snapshot for the render loop to read without blocking. Widgets never touch the sources' internals directly, only `get()`.

**Media source is swappable at runtime** via `config.MEDIA_SOURCE` (`"usb"` or `"bluetooth"`), selected in `main.py:_create_media_source()`. `USBMedia` (`media_usb.py`) and `BluetoothMedia` (`media_bluetooth.py`) deliberately expose the identical interface (`get()`, `play_pause()`, `next_track()`, `previous_track()`, `volume_up()`, `volume_down()`, `toggle_mute()`, `adjust_volume()`) so `main.py`/`widgets.py` don't branch on which one is active — keep any new method in sync across both. The playback/volume methods are wired to the physical buttons and rotary encoder in `main.py`. Key differences: USB carries album artwork (base64 PNG over serial) and PC volume; Bluetooth/AVRCP carries neither (`get()` returns `artwork` absent and `volume: None`, and `widgets.py` falls back to a placeholder icon / hides the volume badge accordingly). `BluetoothMedia`'s volume methods are deliberate no-ops — AVRCP would only change the Pi's own output level, which isn't meaningful here.

**USB media transport**: the Pi runs as a USB CDC-ACM serial gadget (`/dev/ttyGS0`, set up via `dtoverlay=dwc2` + `g_serial`, documented in `usb_media_bridge/pi_receiver/README.md`). The Windows-side counterpart is `usb_media_bridge/pc_sender/win_media_sender.py`, which reads now-playing info via the Windows.Media.Control API (SMTC) and sends newline-delimited JSON (`{"type": "track", ...}` / `{"type": "status", ...}`) over the serial link; `media_usb.py` parses these and sends `{"type": "control", "action": ..., "steps": n}` back for playback and volume control. **Changing this protocol requires updating both sides** — the full message shapes are documented in `media_usb.py`'s module docstring.

SMTC has no volume API, so `win_media_sender.VolumeControl` handles volume separately: it uses `pycaw` when installed (can both set *and read* the level, so the Pi can display it) and otherwise falls back to sending `VK_VOLUME_*` virtual keys (set-only; `volume` is then omitted from status messages and `media_usb.py` keeps `volume = None`, which `widgets.py` treats as "unsupported" and hides the badge). pycaw's API changed across versions — `VolumeControl._open_endpoint()` tries the modern `AudioDevice.EndpointVolume` first, then the older `Activate(IAudioEndpointVolume...)` route.

**Weather**: `weather_openmeteo.py` (`WeatherOpenMeteo`) queries Open-Meteo with multiple forecast models (`config.WEATHER_MODELS`, default `jma_seamless` + `ecmwf_ifs025` + `gfs_seamless`) and averages temperature/precipitation-probability across them to reduce single-model bias; the weather *icon* per slot is instead taken from the first model in the list that has data (codes can't meaningfully be averaged), via `_pick_icon_code`.

**Card strip and touch input** (`card_strip.py`): the cards below the clock live in a horizontally swipeable strip. `CardStrip` owns the scroll state and hit-testing; `Card` is a thin holder for a `draw(screen, fonts, rect)` closure plus an optional `on_tap(local_pos)`. Card order comes from `config.CARD_ORDER`. Notes for anyone touching this:
- It handles **mouse events only**. SDL2 also reports touchscreen input as mouse events, so this works identically with a mouse on a dev PC and with the panel on the Pi, and avoids double-handling `FINGER*` events.
- Tap vs. swipe is decided on release from total movement + hold time (`config.CARD_TAP_MAX_MOVE_PX` / `CARD_TAP_MAX_SEC`), so scrolling never fires a card's buttons.
- Flick velocity is measured over a ~100 ms window of recent positions, using `time.perf_counter()` — **not** `time.monotonic()`, whose ~15.6 ms resolution on Windows makes consecutive-event deltas collapse to zero.
- Because two cards are visible at once, the last cards can't be scrolled to the left edge; `snap_positions()` collapses the duplicate end positions so the dot count equals the number of pages you can actually reach.
- Cards keep their full height and the page dots are drawn into the bottom screen margin — shrinking `config.CARD_HEIGHT` to make room clips the weather card's hour labels.

**Rendering**: `widgets.py` draws directly onto the Pygame `screen` each frame (no dirty-rect optimization) and holds no state beyond a few caches. It is a library of drawing functions; layout state belongs in `card_strip.py`/`main.py`. Weather icons are vector-drawn with `pygame.draw.*` (no image assets for icons); only album artwork and CJK fonts are loaded from `assets/`. Card geometry comes from `config.py` layout constants rather than being hardcoded. Buttons that need hit-testing expose a shared geometry helper used by *both* the draw function and the tap handler (`widgets.aircon_button_rects()`) so the two can't drift apart.

Clock glyph alignment is done on **ink extents, not font boxes** (`draw_clock_panel`, `_ink_block_center_dy`): a colon's dots and CJK glyphs sit lower inside their font box than digits do, so aligning on `get_height()/2` looks visibly off. Both offsets are measured with `get_bounding_rect()` and cached (per minute / per day).

**IR: learn then replay** (`ir_receiver.py` -> `ir_codes.py` -> `ir_control.py`). `IRReceiver` decodes edge timings from a VS1838B-style receiver (active-low, so a falling edge starts a mark) into `[mark, space, ...]` microsecond lists, using `pigpio.tickDiff` because pigpio ticks wrap every ~72 minutes. `ir_codes.py` stores those under a name in `ir_codes.json` (written via a temp file + `os.replace` so a power cut can't corrupt it), and `IRController.send_named()` replays them. `ir_receiver.summarize()` prints the decoded bit pattern to help decide how to handle a given remote.

**Aircon state is one-way** (`aircon.py`): IR can only transmit, so `AirconController` knows only *what it last sent*, never the unit's real state — the card is labelled "最後に送信" for that reason. Don't add UI that implies the state was read back. Buttons on the card come from whatever presets exist in `ir_codes.json`.

**PIR drives the light through injection**: `PIRSensor` owns the on/off *timing* policy (immediate on, off after `config.PIR_LIGHT_OFF_DELAY_SEC`) but not the actuator — pass a `LightController` as `light=`; omit it and it falls back to console prints for testing without hardware. `LightController` (`light_control.py`) does DMA-timed PWM through pigpio with a threaded fade that cancels cleanly when a new command arrives.

**Physical inputs** (`input_rotary.py`, `input_buttons.py`) are pigpio-callback based and call straight into the media source. The rotary decoder uses a gray-code transition table (`_TRANSITIONS`) rather than watching a single phase, so contact bounce and dropped edges can't miscount; `config.ROTARY_STEPS_PER_DETENT` folds the 4 transitions per detent of an EC11 into one step.

**Configuration** (`config.py`) is the single place for hardware pins, display size/fullscreen toggle, colors, font paths, weather location/models, card order, and the USB/Bluetooth media switch. There are no environment-variable or CLI-flag overrides; editing the file is the intended workflow.

The one exception is `config_local.py`, star-imported at the very **end** of `config.py` (inside a `try/except ImportError`, so its absence is fine). It is gitignored — `config_local.example.py` is the committed template — and holds two kinds of values: ones that shouldn't live in the repo (`LATITUDE`/`LONGITUDE`; `config.py`'s checked-in coordinates are a deliberately-obvious Tokyo Station placeholder) and ones that differ between the dev PC and the Pi (`FULLSCREEN`, `USB_MEDIA_SERIAL_PORT`). Two rules when adding to it: the import must stay last so it wins, and **derived constants don't recompute** — overriding `SCREEN_WIDTH` there won't change the already-computed `CARD_WIDTH`, so override the derived constant itself.

GPIO assignments (BCM), all distinct — check this table before adding hardware:

| Pin | Use | Pin | Use |
|-----|-----|-----|-----|
| 4 | DHT11 data | 18 | Light MOSFET gate (PWM) |
| 5 | Button: previous track | 22 | IR receive |
| 6 | Button: next track | 23 / 24 | Rotary A / B |
| 17 | IR transmit | 25 | Rotary push switch |
| | | 27 | PIR out |

**Platform-conditional imports**: every hardware module wraps its hardware-specific import in `try/except ImportError` and sets a `HARDWARE_AVAILABLE` flag, falling back to a no-hardware mode so the whole app stays importable and runnable on a regular PC — `sensor_dht11.py` (Adafruit `board`/`adafruit_dht`, dummy values), `media_bluetooth.py` (`dbus`, permanently disconnected), and `ir_control.py` / `ir_receiver.py` / `light_control.py` / `input_rotary.py` / `input_buttons.py` (`pigpio`, console output instead of GPIO). Preserve this pattern in new hardware modules; note the pigpio ones also degrade gracefully when the import succeeds but `pigpiod` isn't running (`pi.connected` is False).
