# ESP32 NFC Detector

This firmware reads MIFARE NFC tags on an ESP32 (MicroPython). It supports the **RC522** (SPI), the **Elechouse PN532** over any of its three interfaces - **HSU/UART**, **I2C** and **SPI** - and the **M5Stack Unit NFC** (ST25R3916 over I2C). In every case it shows status on a plain GPIO LED or an onboard WS2812/Neopixel, runs a captive portal for Wi-Fi/MQTT/webhook provisioning, and publishes events to MQTT or an HTTP(S) webhook.

## Firmware Variants

The firmware ships in three directories under `src/`, with preconfigured board variants for each reader/wiring combination. Pick the file matching your board and reader, and copy it to the device **renamed to `main.py`** (MicroPython boots `main.py` automatically).

### RC522 (SPI) - `src/rc522/`

| File | Board | RC522 SPI pins | Status LED default |
|------|-------|----------------|--------------------|
| `main.py` | Standard/classic ESP32 DevKit (WROOM etc.) | 18 / 23 / 19 / 5 / 22 | Plain LED on GPIO 2 |
| `main_esp32_s3_super_mini.py` | ESP32-S3 Super-Mini | 12 / 11 / 13 / 10 / 9 | Onboard Neopixel on GPIO 48 |
| `main_esp32_s3_zero.py` | ESP32-S3 Zero (Waveshare) | 12 / 11 / 13 / 10 / 9 | Onboard Neopixel on GPIO 21 |

### PN532 - HSU/UART - `src/pn532/` (`main.py` and the two S3 variants)

| File | Board | PN532 TX / RX | Status LED default |
|------|-------|---------------|--------------------|
| `main.py` | Standard/classic ESP32 DevKit (WROOM etc.) | 17 / 16 | Plain LED on GPIO 2 |
| `main_esp32_s3_super_mini.py` | ESP32-S3 Super-Mini | 1 / 2 | Onboard Neopixel on GPIO 48 |
| `main_esp32_s3_zero.py` | ESP32-S3 Zero (Waveshare) | 1 / 2 | Onboard Neopixel on GPIO 21 |

### PN532 - I2C ("IIC") - `src/pn532/` (`main_iic.py` and the S3 variants)

| File | Board | PN532 SCL / SDA | Status LED default |
|------|-------|-----------------|--------------------|
| `main_iic.py` | Standard/classic ESP32 DevKit (WROOM etc.) | 22 / 21 | Plain LED on GPIO 2 |
| `main_esp32_s3_super_mini_iic.py` | ESP32-S3 Super-Mini | 22 / 21 | Onboard Neopixel on GPIO 48 |
| `main_esp32_s3_zero_iic.py` | ESP32-S3 Zero (Waveshare) | 22 / 21 | Onboard Neopixel on GPIO 21 |

### PN532 - SPI - `src/pn532/` (`main_spi.py` and the S3 variants)

| File | Board | PN532 SCK / MOSI / MISO / CS | Status LED default |
|------|-------|------------------------------|--------------------|
| `main_spi.py` | Standard/classic ESP32 DevKit (WROOM etc.) | 18 / 23 / 19 / 5 | Plain LED on GPIO 2 |
| `main_esp32_s3_super_mini_spi.py` | ESP32-S3 Super-Mini | 18 / 23 / 19 / 5 | Onboard Neopixel on GPIO 48 |
| `main_esp32_s3_zero_spi.py` | ESP32-S3 Zero (Waveshare) | 18 / 23 / 19 / 5 | Onboard Neopixel on GPIO 21 |

### M5Stack Unit NFC (ST25R3916 I2C) - `src/m5stack/`

| File | Board | SCL / SDA | Status LED default | Reset Button |
|------|-------|-----------|--------------------|--------------|
| `main.py` | Standard/classic ESP32 DevKit (WROOM etc.) | 22 / 21 | Plain LED on GPIO 2 | GPIO 4 |
| `main_atoms3_lite.py` | M5Stack AtomS3 Lite | 1 / 2 | Onboard Neopixel on GPIO 35 | GPIO 41 (onboard) |
| `main_esp32_s3_super_mini.py` | ESP32-S3 Super-Mini | 2 / 1 | Onboard Neopixel on GPIO 48 | GPIO 4 |
| `main_esp32_s3_zero.py` | ESP32-S3 Zero (Waveshare) | 2 / 1 | Onboard Neopixel on GPIO 21 | GPIO 4 |

Within each combination the variants are identical except for the hardware pin block and the default `NEOPIXEL_PIN` in the config portal. Every variant shares the same firmware: portal, events, LED patterns, MQTT and webhooks behave identically no matter which reader or bus you use - only the hardware block, the driver import and the reader construction differ.

Notes:
- GPIO22/GPIO23 do not exist on the ESP32-S3 (reserved for flash), so the classic-ESP32 RC522 pin map fails there with `ValueError: invalid pin`. Always use an `main_esp32_s3_*.py` variant on S3 boards. (The PN532 I2C/SPI pin maps above are already S3-safe, which is why they are the same on every board.)
- Boards without any onboard LED: you are responsible for wiring your own LED (+ current-limiting resistor) to a free GPIO and setting `STATUS_LED_PIN` in the file (and/or configuring a Neopixel pin in the portal).

## Hardware Connections

### RC522 (SPI)

Standard ESP32 DevKit (`rc522/main.py`):

| RC522 Pin | ESP32 GPIO |
|-----------|------------|
| SCK | 18 |
| MOSI | 23 |
| MISO | 19 |
| SDA/SS | 5 |
| RST | 22 |

ESP32-S3 Super-Mini and Zero (`rc522/main_esp32_s3_*.py`):

| RC522 Pin | ESP32-S3 GPIO |
|-----------|---------------|
| SCK | 12 |
| MOSI | 11 |
| MISO | 13 |
| SDA/SS | 10 |
| RST | 9 |

### PN532 (HSU/UART)

The Elechouse PN532 must be switched to **HSU** mode with its DIP switches, and TX/RX must be wired **crossed**. Power it from **3.3 V** (see the power note below) and share GND with the ESP32.

Standard ESP32 DevKit (`pn532/main.py`):

| PN532 Pin | ESP32 GPIO |
|-----------|------------|
| RXD | TX2 - 17 |
| TXD | RX2 - 16 |
| VCC | 3.3 V |
| GND | GND |

ESP32-S3 Super-Mini and Zero (`pn532/main_esp32_s3_*.py`):

| PN532 Pin | ESP32-S3 GPIO |
|-----------|---------------|
| RXD | 1 |
| TXD | 2 |
| VCC | 3.3 V |
| GND | GND |

These pins are verified working on a Super-Mini: the module reported `PN532 firmware: 32 01 06 07` (reply `D5 03 32 01 06 07`). Both are plain safe pins - no strapping, USB, flash or PSRAM conflict - and both are on the board's front header, labelled `1` and `2`. TX/RX are still **crossed**: the ESP32's TX (GPIO 1) goes to the module's RXD, and the ESP32's RX (GPIO 2) comes from the module's TXD.

The HSU link runs at 115200 baud. The firmware prints the detected firmware version at boot (for example `PN532 firmware: 32 01 06 07`); if it instead prints a "no reply" warning, re-check the DIP switches and the crossed TX/RX wiring. The driver sends the HSU wake pattern and retries the `SAMConfiguration` handshake up to three times, so a module that was left mid-frame by an interrupted run (a reset, or a host tool that closed the port) re-synchronises by itself; only a module whose DIP switches were changed while it was powered needs a physical power-cycle.

> **Power the module from 3.3 V when the host is a 3.3 V board like the ESP32.** Elechouse rates VCC at 3.3-5 V, and the breakout carries an onboard level shifter that puts the I2C/UART pins at "standard 5 V TTL" when the board is fed 5 V. Feeding it 5 V therefore drives 5 V into the ESP32's RX pin, which is **not** 5 V tolerant. At 3.3 V the shifter runs at 3.3 V and the link is safe. (The vendor's Arduino wiring tables all say VCC = 5 V because Arduino Uno/Mega/Due are 5 V boards.)
>
> If the module is completely silent - the PWR LED is lit but it never answers at any baud rate - check these in order:
> 1. **DIP switches** select HSU (on the Elechouse silkscreen: Channel 1 OFF, Channel 2 OFF).
> 2. **Power-cycle the module** after changing the switches (unplug VCC, wait a few seconds, replug). The switches are only read at power-up.
> 3. **Common GND** between the module and the ESP32.
> 4. **TX/RX are crossed**: ESP32 TX to module RXD, ESP32 RX to module TXD.
> 5. The module draws up to **120 mA**; make sure the 3.3 V rail it hangs off can supply that.
>
> If none of that helps, run `src/pn532/pn532_test.py`, which diagnoses the wiring pin by pin even when the module never answers. See [Testing and Diagnostics](#testing-and-diagnostics).

### PN532 (I2C / "IIC")

Switch the module's DIP switches to **I2C** - the silkscreen's `1 0` row (Channel 1 ON, Channel 2 OFF) - then **power-cycle the module**. The switches are latched at power-up, so flipping them on a module that is already powered changes nothing, and the bus stays silent. It answers at address `0x24`. SDA and SCL need pull-up resistors (the Elechouse breakout has them onboard); power from **3.3 V** (see the power note in the HSU section) and share GND.

Standard ESP32 DevKit (`pn532/main_iic.py`):

| PN532 Pin | ESP32 GPIO |
|-----------|------------|
| SCL | 22 |
| SDA | 21 |
| VCC | 3.3 V |
| GND | GND |

ESP32-S3 Super-Mini and Zero (`pn532/main_*_iic.py`):

| PN532 Pin | ESP32-S3 GPIO |
|-----------|---------------|
| SCL | 6 |
| SDA | 7 |
| VCC | 3.3 V |
| GND | GND |

GPIO22 and GPIO23 do not exist on the ESP32-S3, so the classic 22/21 pair raises `ValueError: invalid pin` there - the S3 variants use 1/2 instead. That pair is verified on a Super-Mini: `0x24` ACKs, the handshake reports `PN532 firmware: 32 01 06 07`, and tags read through the normal polling loop.

If the module never answers, run `src/pn532/iic_test.py` (see [Testing and Diagnostics](#testing-and-diagnostics)); it measures the line pull-ups, scans `0x24` with SDA/SCL in both orders, then runs the handshake and a tag poll.

### PN532 (SPI)

Switch the module's DIP switches to **SPI**. Power from **3.3 V** (see the power note in the HSU section) and share GND. The same pins are used on every board (`pn532/main_spi.py` and the `*_spi` S3 variants):

| PN532 Pin | ESP32 / ESP32-S3 GPIO |
|-----------|-----------------------|
| SCK | 18 |
| MOSI | 23 |
| MISO | 19 |
| CS / SS | 5 |
| VCC | 3.3 V |
| GND | GND |

> Note: over SPI the PN532 shifts bits **LSB-first**, unlike most SPI peripherals. The driver handles the bit-reversal, so you do not need to change anything - but it is why the SPI driver is a little more involved than the HSU one.

### M5Stack Unit NFC (ST25R3916 I2C)

The M5Stack Unit NFC (SKU U216) integrates the STMicroelectronics ST25R3916 NFC transceiver over I2C at fixed 7-bit address **`0x50`** (using Grove HY2.0-4P connector). Connect directly to 3.3V power, GND, and the ESP32 I2C pins.

Standard ESP32 DevKit (`m5stack/main.py`):

| Grove Wire | ST25R3916 Pin | ESP32 GPIO |
|------------|---------------|------------|
| Yellow | SCL | 22 |
| White | SDA | 21 |
| Red | VCC | 3.3 V |
| Black | GND | GND |

M5Stack AtomS3 Lite (`m5stack/main_atoms3_lite.py` - direct plug-and-play via onboard HY2.0-4P Grove Port A):

| Grove Wire | ST25R3916 Pin | AtomS3 Lite GPIO |
|------------|---------------|------------------|
| White | SCL | 1 (G1) |
| Yellow | SDA | 2 (G2) |
| Red | VCC | 5 V |
| Black | GND | GND |

ESP32-S3 Super-Mini and Zero (`m5stack/main_esp32_s3_*.py`):

| Grove Wire | ST25R3916 Pin | ESP32-S3 GPIO |
|------------|---------------|---------------|
| Yellow | SCL | 2 |
| White | SDA | 1 |
| Red | VCC | 3.3 V |
| Black | GND | GND |

The driver (`st25r3916.py`) automatically initializes the RF field, performs regulator calibration, applies the silicon overheat protection workaround, and provides non-blocking tag detection and cascade UID reading (supporting both 4-byte and 7-byte UIDs).

### Status LED
- Onboard Neopixel/WS2812: GPIO 48 (Super-Mini variant) or GPIO 21 (Zero variant), set via `NEOPIXEL_PIN` in `config.json` / the config portal.
- Plain LED fallback: GPIO 2 (standard variant), GPIO 48 (Super-Mini variant) or GPIO 8 (Zero variant). Clear the Neopixel Pin in the config portal to use it.
- Boards with no onboard LED: connect your own LED + resistor and set `STATUS_LED_PIN` in your chosen variant.

### Reset/Config Button
- GPIO 4 to GND: force captive portal on boot (or hold during power-up). Internal pull-up is used.

## Files Required on the ESP32

Copy these files to the MicroPython filesystem:
- One `main*.py` variant, **renamed to `main.py`** (see tables above)
- The reader driver from the same directory, matching your reader and bus:
  - RC522: `mfrc522.py`
  - PN532 over HSU/UART: `pn532.py`
  - PN532 over I2C: `pn532_iic.py`
  - PN532 over SPI: `pn532_spi.py`
  - M5Stack Unit NFC: `st25r3916.py`
- `urequests.py` (MicroPython HTTP client) if using the webhook fallback
- `umqtt/simple.py` (MicroPython MQTT client) if using MQTT

The diagnostics in `src/pn532/` (`pn532_test.py`, `loopback_test.py`,
`main_esp32_s3_super_mini_test.py`) and `src/m5stack/` (`m5stack_nfc_test.py`)
are optional and are not needed for normal operation; see [Testing and Diagnostics](#testing-and-diagnostics).

Built-ins provided by MicroPython on ESP32: `usocket`, `network`, `machine`, `json`, `time`.

## First-Time Setup (Captive Portal)

1. Flash MicroPython to your ESP32.
2. Copy the required files to the device, including your chosen variant as `main.py`.
3. Power up the device. If no Wi-Fi is configured or GPIO 4 is pulled to GND at boot, the captive portal starts.
4. Connect to Wi-Fi network `ESP32_NFC_SETUP` (open).
5. A captive portal page will open automatically. If not, browse to `http://192.168.4.1/`.
6. Fill in:
   - Wi-Fi SSID and Password
   - Device ID: identifier stamped inside every event message; leave blank to use the chip-unique default (`esp32-` + MAC hex, shown as the placeholder)
   - MQTT Broker Host/IP and Port (leave blank to use webhook fallback)
   - MQTT Client ID
   - MQTT Topic Base: prefix for all published topics (default `nfc`, giving `nfc/tag/present` etc.); may contain the `{device}` placeholder, expanded to the Device ID (e.g. `nfc/{device}`)
   - HTTPS Webhook URL (used if MQTT is not configured); may also contain `{device}`
   - Webhook Custom Headers (optional): one `Name: value` per line (e.g. `Authorization: Bearer YOUR_TOKEN`)
   - Status Neopixel Pin (GPIO): pre-filled with your board's default (48 Super-Mini, 21 Zero, blank on standard ESP32); clear it to use the plain LED fallback pin
   - Webhook Timeout (ms), MQTT Timeout (ms), MQTT Reconnect Delay (ms)
7. Save. The device reboots and connects to your Wi-Fi.

## LED Behavior

- Portal / Wi-Fi connecting: blue pulse (500 ms on / 500 ms off). Plain LED blinks on/off.
- No NFC tag present (Neopixel): fixed orange. Plain LED: heartbeat pulse every 3 s (60 ms on).
- NFC tag inserted (Neopixel): fixed green. Plain LED: 300 ms burst on insert.
- Tag detached (after retire event sent): yellow blink 500 ms on / 500 ms off for 2 s, then back to fixed orange. Plain LED: same on/off blink for 2 s.
- If a new tag is inserted during the retire confirmation blink, the LED immediately switches to fixed green.

## Events

When a tag is read/removed, both transports share the same JSON message body:

```json
{"device_id": "esp32-a1b2c3d4e5f6", "event": "present", "uid": "04A1B2C3", "timestamp": 1718000000.5, "message": "Tag present"}
```

- `device_id` is the **Device ID** config key, or the chip-unique default when blank, so several devices can be told apart from the message data alone.
- MQTT (if configured): publishes the JSON body to `<base>/tag/present`, `<base>/tag/retired`, `<base>/tag/alert`. The reader status messages on `<base>/reader/status` (retained, also set as LWT) are JSON too: `{"device_id": "...", "status": "online"}` / `"offline"`. The base is the **MQTT Topic Base** config key (default `nfc`); leading/trailing slashes are trimmed, blank falls back to `nfc`, and `{device}` expands to the Device ID.
- Webhook (fallback): `POST` the same JSON body to the configured URL (with `{device}` expanded in the URL) and headers merged (Content-Type defaults to `application/json`). Webhook requests use a configurable timeout and are non-blocking relative to the main loop (errors are caught and logged). The device prints nothing on success, so watch the receiving service; `tools/webhook_example.py` is a ready-made one.
- Note: MQTT payloads are JSON envelopes (device id, event, uid, timestamp, message) instead of the raw UID string.

## Testing and Diagnostics

Four standalone scripts sit next to the firmware, plus the webhook receiver
covered in the next section. None of them is part of the reader firmware:
they never touch Wi-Fi, MQTT, webhooks or the captive portal, and you run them
*instead of* `main.py`. All of them print to the serial console at 115200 baud.

| Script | Runs on | What it proves |
|--------|---------|----------------|
| `src/pn532/loopback_test.py` | ESP32 | The board's own UART, both GPIO pads and one jumper wire. No PN532 involved. |
| `src/pn532/pn532_test.py` | ESP32 | HSU/UART wiring: pin-by-pin voltage/bias scan, raw wake probe, real driver handshake, then a tag poll. |
| `src/pn532/iic_test.py` | ESP32 | I2C wiring: line pull-ups, a `0x24` scan with SDA/SCL in both orders, handshake, then a tag poll. |
| `src/pn532/test_pins_auto.py` | ESP32 | Auto-detects I2C or HSU mode and polls for a tag to quickly verify the working interface. |
| `src/pn532/main_esp32_s3_super_mini_test.py` | ESP32 | A minimal reader: handshake, PASS/FAIL verdict, then UID polling with the status LED. |
| `tools/webhook_example.py` | your computer | Receives the device's webhook POSTs and checks the auth header. |

`pn532_test.py` and `main_esp32_s3_super_mini_test.py` import `pn532.py`;
`iic_test.py` imports `pn532_iic.py`. `test_pins_auto.py` auto-detects and
imports whichever driver is needed. Copy the matching driver to the board as
well. `loopback_test.py` needs nothing but `machine`.

Run a device script straight from the host without copying it first:

```sh
ampy -p /dev/tty.usbmodem1401 -b 115200 run "$PWD/src/pn532/pn532_test.py"
```

(`ampy run` resolves the path itself, so pass an absolute one - a relative path
fails with `Failed to find or read input file`.) Or copy it over and run it from
the board:

```sh
ampy -p /dev/tty.usbmodem1401 -b 115200 put src/pn532/pn532_test.py :pn532_test.py
ampy -p /dev/tty.usbmodem1401 -b 115200 run :pn532_test.py
```

### `loopback_test.py` - is the board itself good?

Put a jumper directly between the two header pads named at the top of the file
(`TX_PIN = 1`, `RX_PIN = 2` on the Super-Mini), with no module in the circuit,
then run it. Every pattern prints `MATCH` and the last line reads
`LOOPBACK RESULT: PASS`. A `MISMATCH` or `GOT NOTHING` means the fault is on the
board side - wrong hole, bad jumper, no contact - not in the PN532 or its
driver. Edit `TX_PIN`/`RX_PIN` to test a different pair.

### `pn532_test.py` - where is the module wired?

This is the one to reach for when the module never answers, because the first
steps need no reply from it at all. It runs six steps:

0. Optional: wire the module's VCC to `VCC_PROBE_PIN` (GPIO 9) and it prints the
   actual supply voltage.
1. Scans every safe GPIO with the ADC, and again with the internal pull-up and
   pull-down, then gives a verdict per pin (`driven HIGH`, `floating`,
   `semi-floating`, ...). A push-pull line that stays high under a pull-down is
   the module's TXD.
2. Prints what the scan implies, naming the likely TXD pin.
3. Sends the raw PN532 wake pattern on each candidate pair and dumps any bytes
   that come back.
4. Runs the real driver handshake on the promising pairs and prints the firmware
   version when the module answers.
5. Polls the working pair for 15 s (`POLL_SECONDS`) and prints `TAG READ: <UID>`,
   with a heartbeat every 3 s so ampy does not time the run out.

`PAIRS` near the top lists `(esp32_tx, esp32_rx)` as GPIO numbers, not header
pin numbers; add your own pair if you wire something unusual. The successful
pair is the wiring the firmware should use, and step 4 stops at the first pair
that answers.

### `iic_test.py` - is the module really in I2C mode?

The I2C equivalent, and the one that separates the three things that all look
identical from the host side: wrong DIP switches, swapped SDA/SCL, and missing
pull-ups. It runs four steps:

0. Reads both signal pins with the ADC, free and with the ESP32's internal
   pull-up. I2C needs an external pull-up on each line, so both should idle near
   3.3 V; a low line means missing pull-ups or the wrong pads.
1. Scans address `0x24` on pads 1/2 with **SDA and SCL in both orders**, then on
   21/22 (which report `ValueError: invalid pin` on an S3 - expected, ignore).
2. Runs the real driver handshake on whichever orientation answered and prints
   the firmware version.
3. Polls that orientation for 20 s (`POLL_SECONDS`) and prints `TAG READ: <UID>`.

It ends by printing the exact `I2C(0, scl=Pin(...), sda=Pin(...), freq=100000)`
line the firmware should use. A successful run looks like:

```
scl=GPIO1  sda=GPIO2   found 0x24
RESULT: PASS - the module answered at 0x24 with scl=GPIO1 sda=GPIO2.
PN532 firmware: 32 01 06 07
```

If the scan finds nothing at all while both lines idle high, the module is
almost always still in **HSU** mode: set the DIP switches to the `1 0` row and
**power-cycle** it. Running the module in HSU mode on the same two pads is how
you tell the two cases apart - it will answer a UART handshake there.

### `main_esp32_s3_super_mini_test.py` - does it read tags?

A stripped-down reader for the Super-Mini: `tx=Pin(1)`, `rx=Pin(2)`, no Wi-Fi and
no portal. It handshakes, prints a PASS/FAIL verdict (Neopixel red on failure,
green once the module answers), then polls forever, printing every UID it sees
and flashing blue while a tag is on the antenna. Use it to confirm the reader
works before wiring up MQTT or a webhook.

### When a run fails under ampy

`ampy run` gives up with `timeout waiting for first EOF reception` when the
script goes quiet for too long. The diagnostics now print a heartbeat during
their long waits, so this should not happen; if it does, the board is usually
left in raw-paste mode and the next `ampy ls` recovers it.

## Testing the Webhook

`tools/webhook_example.py` is a small receiver you run on a computer that is on
the same Wi-Fi network as the reader. It prints every event as it arrives and
rejects requests whose auth header is missing or wrong, so it exercises both the
**Webhook URL** and the **Webhook headers** settings of the portal.

```sh
python3 tools/webhook_example.py --token secret123
```

It prints the exact values to paste into the portal, and on every request it
shows the path, all received headers, and the decoded event:

```
Paste these into the reader's configuration portal:
  Webhook URL:     http://192.168.0.113:8080/webhook
  Webhook headers: Authorization: Bearer secret123

[17:02:38] POST /webhook from 192.168.0.42
  headers:
    Content-Type: application/json
    Authorization: Bearer secret123
  event:   present
  device:  esp32-a1b2c3d4e5f6
  uid:     A6DFEED7
  message: Tag present
  -> 200 OK  (event #1)
```

Portal settings for the test:

| Portal field | Value |
|--------------|-------|
| Webhook URL | `http://<your-computer-ip>:8080/webhook` |
| Webhook headers | `Authorization: Bearer secret123` |
| MQTT Broker | leave blank |

- MQTT takes precedence: the reader uses the webhook only when no MQTT broker is
  configured, so blank out **MQTT Broker** while testing.
- Headers are one `Name: value` per line. To confirm the device is sending them,
  delete the header line in the portal and watch the receiver answer `401` with
  `missing the 'Authorization' header`, or change the token and watch it answer
  `wrong 'Authorization' header`.
- `{device}` in the URL expands to the Device ID (`/hook/{device}`); the
  receiver accepts any path.
- Wrong tokens, missing tokens and non-JSON bodies are all logged with the
  reason and answered with `401` or `400`.
- `--token`, `--port`, `--header` and `--scheme` change the expected secret,
  port, header name and prefix; run with `--help` for the full list.
- If the reader cannot reach the receiver, check that both are on the same
  network and allow incoming connections for the Python process in the
  computer's firewall.

## Operation Notes

- Debounced retire: a tag is marked "retired" after 3 consecutive missed reads (configurable via `DEBOUNCE_THRESHOLD`).
- Alert: if a tag remains on the reader longer than `MAX_PRESENT_TIME` seconds, an alert event is published.
- Button on GPIO 4 forces the configuration portal on boot.
- All LED and polling logic is non-blocking using `time.ticks_ms()`/`time.ticks_diff()`.
- Network operations are guarded with try/except and timeouts where applicable; the main loop yields with `time.sleep_ms(5)`.
- Timeouts: `WEBHOOK_TIMEOUT_MS` (default 3000 ms), `MQTT_TIMEOUT_MS` (default 3000 ms), `MQTT_RECONNECT_DELAY_MS` (default 2000 ms).
- `config.json` is stored on the device after saving from the portal. Keys: `DEVICE_ID`, `WIFI_SSID`, `WIFI_PASS`, `MQTT_BROKER`, `MQTT_PORT`, `MQTT_CLIENT_ID`, `MQTT_TOPIC`, `WEBHOOK_URL`, `WEBHOOK_HEADERS`, `NEOPIXEL_PIN`, `WEBHOOK_TIMEOUT_MS`, `MQTT_TIMEOUT_MS`, `MQTT_RECONNECT_DELAY_MS`.

## Development Notes

- There are twelve `main*.py` files: three board variants for each of the four reader/bus combinations (RC522 SPI, PN532 HSU, PN532 I2C, PN532 SPI). Within one combination the three files share the same logic and differ only in the hardware pin block, `STATUS_LED_PIN` and the default `NEOPIXEL_PIN`, so keep any edit in sync across those three.
- The three diagnostics (`loopback_test.py`, `pn532_test.py`, `main_esp32_s3_super_mini_test.py`) are deliberately outside that set. They are hand-written, not generated from the firmware, and can be edited freely.
- There is no test suite, linter or CI. `ast.parse` (or `python3 -m py_compile`) is the only host-side check available, and it catches syntax only - MicroPython API misuse still shows up only on the board.
- Use `time.ticks_*` for all timing; avoid `time.sleep()` in the main/portal loops except short delays as written.
- Keep changes non-blocking: network calls must not stall the NFC polling loop.
