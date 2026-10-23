# PN532 (Elechouse V3/V4, HSU/UART) CONNECTIVITY + TAG-READ TEST
# for ESP32-S3 Super-Mini (also fine on a classic ESP32) running MicroPython
#
# Run it the same way the loopback test worked:
#   ampy -p /dev/tty.usbmodem1401 -b 115200 run esp32_nfc_detector/src/pn532/pn532_test.py
#
# It works when the module is completely silent, which is the whole point: the
# first two steps measure the wiring with the ADC and usually tell you what is
# wrong without any reply from the module.
#
# WHAT IT DOES, IN ORDER
#   0. OPTIONAL: run a wire from the module's VCC pin to GPIO9 and the actual
#      supply voltage at the module is printed (a saturated reading means 5 V).
#   1. Scans every safe GPIO with the ADC and with the internal pull-up and
#      pull-down, then prints a verdict per pin:
#        * driven HIGH  - holds 1 under both pulls. That is a push-pull output,
#                         i.e. almost certainly the module's TXD line.
#        * ~3.0-3.3 V  - healthy HIGH.
#        * ~1.9-2.9 V  - a line that is connected but semi-floating.
#        * ~1.7 V or less with a pull-up, 0 V with a pull-down - floating,
#                         nothing attached.
#   2. Prints what the scan found: the pin that looks like the module's TXD.
#   3. Raw mode: sends the PN532 wake pattern on each candidate pair and dumps
#      any bytes that come back, with no driver involved.
#   4. Driver mode: runs the real handshake (SAMConfiguration +
#      GetFirmwareVersion) on the pairs that look promising and prints the
#      firmware version if the module answers. The driver retries the wake and
#      handshake, so a module left mid-frame by an interrupted run recovers.
#   5. If a pair answers, it polls that pair for a tag and prints
#      "TAG READ: <UID>" when you tap a card, plus a heartbeat every 3 s so a
#      host tool such as ampy does not time the run out.
#
# WIRING (HSU mode, DIP switches set to HSU per the module's silkscreen)
#   ESP32 TX  -> PN532 RXD      (crossed)
#   ESP32 RX  -> PN532 TXD      (crossed)
#   ESP32 GND -> PN532 GND      (common ground, essential)
#   PN532 VCC -> 3.3V, never 5V. The board's level shifter puts the I2C/UART
#               pins at "standard 5 V TTL" when the module is fed 5 V, which
#               would drive 5 V into the ESP32's non-5 V tolerant RX pin.
#
# After changing the DIP switches, POWER-CYCLE the module: unplug VCC, wait a
# few seconds, plug it back in. The switches are only read at power-up.
#
# PAIRS are (esp32_tx, esp32_rx) GPIO numbers, not header pin numbers. The
# board's pads are labelled with GPIO numbers, so pad "17" is Pin(17).
# First the pads on the bench right now (1 and 2, both orders), then the
# documented ESP32-S3 defaults, then the earlier GPIO3/GPIO1 wiring, then the
# board's own TX/RX pads.
PAIRS = [
    (1, 2),
    (2, 1),
    (17, 18),
    (18, 17),
    (3, 1),
    (1, 3),
    (43, 44),
    (44, 43),
]

SAFE_PINS = [1, 2, 3, 4, 5, 6, 7, 8, 15, 16, 17, 18, 21,
             33, 34, 35, 36, 37, 38, 43, 44]

BAUD = 115200
POLL_SECONDS = 15
VCC_PROBE_PIN = 9      # optional: wire the module's VCC here to read it

import time
from machine import Pin, UART

try:
    from machine import ADC
except ImportError:
    ADC = None

try:
    import pn532
    HAVE_DRIVER = True
except ImportError:
    HAVE_DRIVER = False

# The PN532 wake pattern: 0x55 0x55 followed by fifteen 0x00 bytes.
WAKE = b"\x55\x55" + b"\x00" * 15


def measure(pin):
    """(raw_average, volts) for a pin, or (None, None).

    The raw value is kept because the ADC saturates near 3.3 V, so a 5 V
    reading shows up as a full-scale raw value.
    """
    if ADC is None:
        return None, None
    try:
        Pin(pin, Pin.IN)
        time.sleep_ms(20)
        ch = ADC(Pin(pin))
    except Exception:
        return None, None
    total = 0
    for _ in range(24):
        total += ch.read()
    raw = total / 24.0
    return raw, raw * 3.3 / 4095.0


def bias_state(pin):
    """Digital value of a pin with its internal pull-up, then pull-down.

    (1, 1) means something external holds the pin high, because the internal
    pull-down (~45 kOhm) cannot win. (0, 0) means the opposite. Anything else
    is a floating pin that just follows whichever pull is active.
    """
    a = Pin(pin, Pin.IN, Pin.PULL_UP)
    time.sleep_ms(25)
    up = a.value()
    b = Pin(pin, Pin.IN, Pin.PULL_DOWN)
    time.sleep_ms(25)
    dn = b.value()
    Pin(pin, Pin.IN)
    time.sleep_ms(10)
    return up, dn


def verdict(raw, v, up, dn):
    if v is None:
        return "not readable", "no ADC on this pin"
    if up == 1 and dn == 1:
        return "driven HIGH", "push-pull output - most likely a module TX line"
    if up == 0 and dn == 0:
        return "driven LOW", "push-pull output held low"
    if raw >= 4080:
        return "FULL SCALE", "3.3 V or more - the ADC tops out here"
    if v >= 2.9:
        return "HIGH", "healthy idle-high line"
    if v >= 1.9:
        return ("semi-floating", "connected, but not driven high - if this is "
                "the module's line its rail is sagging (power it from 5V)")
    return "floating", "nothing attached"


def raw_probe(tx, rx):
    """Send the wake pattern and return whatever bytes come back, or b''.

    A jumper that shorts TX to RX makes the board echo its own bytes back.
    That is not the module talking, so the echo is detected and stripped.
    """
    u = UART(2, baudrate=BAUD, bits=8, parity=None, stop=1,
             tx=Pin(tx), rx=Pin(rx))
    time.sleep_ms(150)
    while u.any():
        u.read(u.any())
    u.write(WAKE)
    time.sleep_ms(300)
    n = u.any()
    got = u.read(n) if n else b""
    # Give the module a moment to answer the wake burst on its own.
    time.sleep_ms(300)
    n = u.any()
    if n:
        got = got + u.read(n)
    u.deinit()
    if got.startswith(WAKE):
        got = got[len(WAKE):]
    return got


def looks_like_pn532(data):
    """A PN532 frame starts 00 00 FF and an ACK is 00 00 FF 00 FF."""
    return data.find(b"\x00\x00\xff") >= 0


def hexs(data):
    return " ".join("%02X" % b for b in data)


def main():
    print("=== PN532 HSU connectivity + tag-read test ===")
    if HAVE_DRIVER:
        print("pn532.py found on the board.")
    else:
        print("pn532.py is NOT on the board - only the raw probe will run.")
        print("  ampy -p <port> -b 115200 put "
              "esp32_nfc_detector/src/pn532/pn532.py")
    print()

    print("--- step 0: optional module supply voltage ---")
    raw, v = measure(VCC_PROBE_PIN)
    if v is None:
        print("GPIO%d has no ADC here." % VCC_PROBE_PIN)
    elif raw >= 4080:
        print("GPIO%d is at full scale -> the module is fed 5V or more. Good."
              % VCC_PROBE_PIN)
    elif v > 2.9:
        print("GPIO%d reads %.2fV -> the module is fed from 3.3V." % (VCC_PROBE_PIN, v))
        print("  >>> THIS IS THE USUAL BUG. Move VCC to the board's 5V pad,")
        print("  >>> then unplug and replug the module to power-cycle it.")
    elif v > 0.5:
        print("GPIO%d reads %.2fV -> odd supply, check the VCC wiring."
              % (VCC_PROBE_PIN, v))
    else:
        print("GPIO%d reads %.2fV -> nothing wired there (this is optional)."
              % (VCC_PROBE_PIN, v))
    print()

    print("--- step 1: every safe GPIO, voltage and bias ---")
    print("Look for a 'driven HIGH' pin: that is the module's TX line.")
    driven_high = []
    semi = []
    for pin in SAFE_PINS:
        raw, v = measure(pin)
        up, dn = bias_state(pin)
        state, note = verdict(raw, v, up, dn)
        print("GPIO%-3d %5s V  raw=%-5s  up=%d dn=%d  %-13s %s"
              % (pin,
                 ("%.2f" % v) if v is not None else "n/a",
                 ("%d" % raw) if raw is not None else "n/a",
                 up, dn, state, note))
        if up == 1 and dn == 1:
            driven_high.append(pin)
        elif v is not None and 1.9 <= v < 2.9:
            semi.append(pin)
    print()

    print("--- step 2: what the scan says ---")
    if driven_high:
        print("Driven HIGH (module TX candidates): GPIO%s"
              % ", GPIO".join(str(p) for p in driven_high))
        print("So the ESP32 should use rx=Pin(%d)." % driven_high[0])
    else:
        print("No pin is driven HIGH. The module's TXD is either not")
        print("connected or the module is not running (power / DIP switches).")
    if semi:
        print("Semi-floating lines: GPIO%s" % ", GPIO".join(str(p) for p in semi))
        print("A line parked near 2.2-2.4 V can be the module's idle input pin.")
        print("Keep VCC on 3.3 V: at 5 V the module's level shifter drives 5 V")
        print("into the ESP32, whose pins are not 5 V tolerant.")
    print()

    print("--- step 3: raw wake pattern on each candidate pair ---")
    raw_hits = []
    for tx, rx in PAIRS:
        try:
            got = raw_probe(tx, rx)
        except Exception as exc:
            print("tx=GPIO%-2d rx=GPIO%-2d error %s" % (tx, rx, exc))
            continue
        if got:
            flag = "  <-- PN532 FRAME" if looks_like_pn532(got) else ""
            print("tx=GPIO%-2d rx=GPIO%-2d got %2d bytes: %s%s"
                  % (tx, rx, len(got), hexs(got), flag))
            raw_hits.append((tx, rx, got))
        else:
            print("tx=GPIO%-2d rx=GPIO%-2d nothing" % (tx, rx))
    print()

    print("--- step 4: driver handshake ---")
    good = []
    if not HAVE_DRIVER:
        print("skipped (no pn532.py)")
    else:
        # Only handshake pairs that replied, plus the wiring in use and the
        # documented defaults, so a silent module does not cost a long wait on
        # every candidate pair.
        interesting = [(tx, rx) for tx, rx, _ in raw_hits]
        for pair in PAIRS[:4]:
            if pair not in interesting:
                interesting.append(pair)
        for tx, rx in interesting:
            print("tx=GPIO%-2d rx=GPIO%-2d ..." % (tx, rx))
            u = None
            try:
                u = UART(2, baudrate=BAUD, bits=8, parity=None, stop=1,
                         tx=Pin(tx), rx=Pin(rx))
                trial = pn532.PN532(u)
                ver = trial._sync_call(pn532._COMMAND_GETFIRMWAREVERSION,
                                       b"", 800)
                if ver:
                    print("  ANSWERED, raw reply: %s" % hexs(ver))
                    good.append((tx, rx))
                else:
                    print("  no answer")
            except Exception as exc:
                print("  error:", exc)
            finally:
                # UART2 is one peripheral shared by every attempt. Free it (and
                # its pin mapping) before the next pair, otherwise the last
                # trial's pins would still own UART2 when step 5 starts.
                if u is not None:
                    try:
                        u.deinit()
                    except Exception:
                        pass
            if good:
                break
    print()

    if not good:
        print("RESULT: FAIL - the PN532 did not complete a handshake.")
        print()
        print("Check, in this order:")
        print("  1. GROUND shared with the ESP32.")
        print("  2. TX/RX crossed: ESP32 TX -> module RXD, ESP32 RX <- module TXD.")
        print("  3. VCC on 3.3 V (5 V would put 5 V on the ESP32's pins).")
        print("  4. Module powered only after its DIP switches were set - the")
        print("     switches are latched at power-up, so power-cycle the module.")
        print("  5. DIP switches on HSU (both OFF).")
        if raw_hits:
            print()
            print("Bytes did come back on %s, so the link is alive -"
                  % ", ".join("tx=GPIO%d rx=GPIO%d" % (a, b)
                              for a, b, _ in raw_hits))
            print("suspect the module mode or the baud rate next.")
        return

    tx, rx = good[0]
    print("RESULT: PASS - the PN532 answered on tx=GPIO%d rx=GPIO%d." % (tx, rx))
    print()
    # Build a fresh UART for the winning pair: step 4 deinitialised the one it
    # used, and UART2 can only be mapped to one pair of pins at a time.
    u = UART(2, baudrate=BAUD, bits=8, parity=None, stop=1,
             tx=Pin(tx), rx=Pin(rx))
    reader = pn532.PN532(u)
    print("--- step 5: reading tags for %d s - tap a card now ---" % POLL_SECONDS)
    deadline = time.ticks_add(time.ticks_ms(), POLL_SECONDS * 1000)
    last_uid = None
    reads = 0
    last_report = time.ticks_ms()
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        status = reader.request(reader.REQIDL)[0]
        if status == reader.OK:
            uid_status, uid = reader.anticoll()
            if uid_status == reader.OK and uid:
                reads += 1
                if uid != last_uid:
                    last_uid = uid
                    print("TAG READ:", hexs(uid))
                elif reads % 20 == 0:
                    print("  still reading", hexs(uid), "(%d reads)" % reads)
        # A heartbeat every few seconds keeps host tools such as ampy from
        # timing out on a silent run, and shows that the loop is alive.
        if time.ticks_diff(time.ticks_ms(), last_report) > 3000:
            last_report = time.ticks_ms()
            print("  waiting for a tag... %d s left"
                  % (time.ticks_diff(deadline, time.ticks_ms()) // 1000))
        time.sleep_ms(50)
    if last_uid is None:
        print("No tag read, but the handshake worked, so the link is fine.")
        print("Check the card and that the antenna is not shorted or covered.")
    else:
        print("Read the tag %d times; UID %s" % (reads, hexs(last_uid)))
    print()
    print("Done.")


main()
