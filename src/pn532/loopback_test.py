# PN532 / ESP32-S3 Super-Mini UART TX-RX LOOPBACK TEST
#
# WHAT THIS CHECKS
#   Wire one jumper directly between the board's TX pin and its RX pin
#   (nothing else - no PN532 involved). This firmware sends bytes out of TX
#   and reads them straight back in on RX. If they match, the ESP32's UART,
#   both GPIO pads, and that jumper are all proven good. If they do NOT match,
#   the fault is on the board side (wrong hole, bad jumper, no contact), NOT
#   in the PN532 driver.
#
# HOW TO USE
#   1. Put a jumper wire between the two header holes named in TX_PIN/RX_PIN
#      below. For the S3 Super-Mini the easy pair is header pin 6 = IO1 and
#      header pin 7 = IO2, which is tx=Pin(1), rx=Pin(2) as set below.
#   2. Copy this file to the board (e.g. as main.py) and reset, OR paste it
#      into the REPL with mpremote:  mpremote run loopback_test.py
#   3. Watch the serial output at 115200 baud.
#
# EXPECTED RESULT WHEN THE JUMPER IS GOOD
#   Every line prints MATCH. Final line: LOOPBACK RESULT: PASS
#
# IF YOU SEE "MISMATCH" or "GOT NOTHING"
#   The jumper is not making contact, or you are not on the GPIO holes you
#   think you are. Re-check: multimeter continuity across the jumper ends.
#   Then try a different pair by editing TX_PIN/RX_PIN and moving the jumper.
#
# Common S3 Super-Mini pairs (code pin <- header label):
#   tx=Pin(1),  rx=Pin(2)    header IO1  -> IO2
#   tx=Pin(1),  rx=Pin(3)    header IO1  -> IO3
#   tx=Pin(17), rx=Pin(18)   header IO17 -> IO18
#   tx=Pin(43), rx=Pin(44)   header TX   -> RX   (also the USB console pins)

import time
from machine import Pin, UART

# --- CONFIGURATION: edit these two lines to match where your jumper is ------
TX_PIN = 1            # ESP32 transmits here  (header IO1 on S3 Super-Mini)
RX_PIN = 2            # ESP32 receives here   (header IO2 on S3 Super-Mini)
# ---------------------------------------------------------------------------

BAUD = 115200
ROUNDS = 6


def make_uart():
    return UART(2, baudrate=BAUD, bits=8, parity=None, stop=1,
                tx=Pin(TX_PIN), rx=Pin(RX_PIN))


def drain(u):
    """Return and clear any bytes currently waiting."""
    n = u.any()
    if not n:
        return b""
    data = u.read(n)
    return data if data else b""


def main():
    print("=== UART TX-RX loopback test ===")
    print("TX = GPIO%d   RX = GPIO%d   baud = %d" % (TX_PIN, RX_PIN, BAUD))
    print("Jumper must connect these two pins directly.")
    print()

    u = make_uart()
    time.sleep_ms(200)
    drain(u)  # throw away anything stale

    passes = 0
    total = 0
    patterns = [
        bytes([0xA5]),
        bytes([0xA5, 0x5A]),
        b"LOOP",
        bytes([0x00, 0x00, 0xFF, 0x05, 0xFB, 0xD4, 0x14, 0x01, 0x14, 0x01, 0x02, 0x00]),
        bytes(range(0, 32)),
        bytes([0xFF] * 16),
    ]

    for i in range(ROUNDS):
        payload = patterns[i % len(patterns)]
        drain(u)
        u.write(payload)
        time.sleep_ms(120)
        got = drain(u)
        total += 1
        ok = got == payload
        if ok:
            passes += 1
        print("round %d: sent %-26s got %-26s %s" % (
            i + 1,
            payload.hex(),
            got.hex() if got else "(nothing)",
            "MATCH" if ok else "MISMATCH",
        ))

    print()
    # Second pass: sample the line state at rest, to hint at the wiring problem.
    print("--- line state at rest (helps spot a bad jumper) ---")
    for name, n in (("TX", TX_PIN), ("RX", RX_PIN)):
        try:
            p_up = Pin(n, Pin.IN, Pin.PULL_UP)
            time.sleep_ms(15)
            up = p_up.value()
            p_dn = Pin(n, Pin.IN, Pin.PULL_DOWN)
            time.sleep_ms(15)
            dn = p_dn.value()
            if up == 0:
                state = "driven LOW"
            elif dn == 1:
                state = "driven HIGH"
            else:
                state = "floating"
            print("GPIO%-3d pullup=%d pulldown=%d -> %s" % (n, up, dn, state))
        except Exception as exc:
            print("GPIO%-3d error: %s" % (n, exc))

    # Direct electrical check: drive TX low/high and see if RX follows.
    # If the jumper is real, RX MUST track TX. This is the clearest proof.
    print()
    print("--- jumper continuity check (drive TX, read RX) ---")
    drv = Pin(TX_PIN, Pin.OUT)
    drv.value(0)
    time.sleep_ms(20)
    rd = Pin(RX_PIN, Pin.IN, Pin.PULL_UP)
    time.sleep_ms(20)
    low_seen = rd.value()
    drv.value(1)
    time.sleep_ms(20)
    rd = Pin(RX_PIN, Pin.IN, Pin.PULL_DOWN)
    time.sleep_ms(20)
    high_seen = rd.value()
    print("drive TX LOW  -> RX reads %d (expect 0 if jumpered)" % low_seen)
    print("drive TX HIGH -> RX reads %d (expect 1 if jumpered)" % high_seen)
    jumpered = (low_seen == 0 and high_seen == 1)
    print("JUMPER:", "CONNECTED" if jumpered else "NOT CONNECTED")

    print()
    if passes == total and jumpered:
        print("LOOPBACK RESULT: PASS - UART and jumper are good.")
        print("The ESP32 side works. Any remaining fault is the PN532 wiring.")
    else:
        print("LOOPBACK RESULT: FAIL - %d/%d rounds matched." % (passes, total))
        print("The jumper is not conducting between GPIO%d and GPIO%d." % (TX_PIN, RX_PIN))
        print("Check: multimeter continuity, correct header holes, jumper seated.")
        print("Then edit TX_PIN/RX_PIN and retry another pair.")
    print()
    print("Leaving UART open; press Ctrl-D or reset to exit.")


main()
