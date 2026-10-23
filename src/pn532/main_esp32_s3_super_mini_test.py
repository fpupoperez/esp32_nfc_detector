# Minimal PN532 (HSU/UART) connectivity + tag-read test.
#
# This is a standalone diagnostic, NOT the full reader firmware. It does three
# things and nothing else:
#   1. builds the UART and constructs the PN532 driver (which runs the
#      SAMConfiguration + GetFirmwareVersion handshake),
#   2. prints a clear PASS/FAIL verdict for the wiring,
#   3. polls for ISO14443-A tags and prints every UID it reads.
#
# Run it by copying it to the board as main.py (or paste it into the REPL with
# mpremote). No Wi-Fi, no MQTT, no webhooks, no captive portal.
#
# Wiring (HSU - crossed, plus common GND):
#   ESP32 GPIO1 (TX)  ->  PN532 RXD
#   ESP32 GPIO2 (RX)  <-  PN532 TXD
#   ESP32 GND         --  PN532 GND
#   PN532 VCC 3.3V, module DIP switches set to HSU
#
# If nothing is detected, try the other pin pair: tx=Pin(43), rx=Pin(44),
# which are the board's labelled TX/RX pins.

import time
from machine import Pin, UART
import pn532
from pn532 import PN532

# --- CONFIGURATION ---------------------------------------------------------
TX_PIN = 1            # ESP32 TX -> PN532 RXD  (GPIO1, header pin 1)
RX_PIN = 2            # ESP32 RX <- PN532 TXD  (GPIO2, header pin 2)
STATUS_LED_PIN = 48   # onboard Neopixel data pin on the S3 Super-Mini
USE_NEOPIXEL = True
POLL_INTERVAL = 0.2   # seconds between polls
# ---------------------------------------------------------------------------


def make_led(pin_number, use_neopixel):
    """Return (set_rgb, set_plain) helpers, or (None, None) if unavailable."""
    if use_neopixel:
        try:
            from neopixel import NeoPixel
            np = NeoPixel(Pin(pin_number, Pin.OUT), 1)

            def set_rgb(r, g, b):
                np[0] = (r, g, b)
                np.write()
            return set_rgb, None
        except Exception as exc:
            print("Neopixel unavailable (%s), using plain LED" % exc)

    led = Pin(pin_number, Pin.OUT)

    def set_plain(on):
        led.value(1 if on else 0)
    return None, set_plain


def main():
    set_rgb, set_plain = make_led(STATUS_LED_PIN, USE_NEOPIXEL)

    def show(r, g, b):
        if set_rgb:
            set_rgb(r, g, b)
        elif set_plain:
            set_plain(g or b)  # any non-zero channel means "on"

    print("=== PN532 HSU test ===")
    print("Building UART on TX=GPIO%d RX=GPIO%d ..." % (TX_PIN, RX_PIN))
    uart = UART(2, baudrate=115200, bits=8, parity=None, stop=1,
                tx=Pin(TX_PIN), rx=Pin(RX_PIN))

    show(0, 0, 64)  # blue: connecting
    print("Constructing driver (runs the boot handshake, may pause briefly)...")
    reader = PN532(uart)

    # The driver stores nothing on a failed handshake, so re-run one blocking
    # GetFirmwareVersion ourselves to get a definite verdict.
    version = reader._sync_call(pn532._COMMAND_GETFIRMWAREVERSION, b"", 500)

    if version is None:
        print()
        print("RESULT: FAIL - the PN532 did not answer.")
        print("Check, in this order:")
        print("  1. module DIP switches are set to HSU (not I2C/SPI)")
        print("  2. TX/RX are CROSSED: ESP32 TX -> PN532 RXD, ESP32 RX <- PN532 TXD")
        print("  3. common GND between board and module, module powered at 3.3V")
        print("  4. try the other pin pair: TX=43, RX=44")
        show(64, 0, 0)  # red: fail
        return

    print("RESULT: PASS - module replied with firmware bytes:", version)
    show(0, 64, 0)  # green: connected
    print()
    print("Scanning for tags. Tap a card on the reader...")

    last_uid = None
    while True:
        (status, _tag_type) = reader.request(reader.REQIDL)
        if status == reader.OK:
            (status, uid) = reader.anticoll()
            if status == reader.OK and uid:
                uid_hex = "".join(["{:02X}".format(b) for b in uid])
                print("TAG READ:", uid_hex)
                last_uid = uid_hex
                show(0, 0, 64)      # blue: a tag is present right now
                time.sleep_ms(200)
                show(0, 64, 0)      # back to green
        time.sleep(POLL_INTERVAL)


main()
