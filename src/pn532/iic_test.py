# PN532 (Elechouse V3/V4, I2C / "IIC" mode) CONNECTIVITY + TAG-READ TEST
# for ESP32-S3 Super-Mini (also fine on a classic ESP32) running MicroPython
#
# Run it straight from the host:
#   ampy -p /dev/tty.usbmodem1401 -b 115200 run esp32_nfc_detector/src/pn532/iic_test.py
#
# WHAT IT DOES, IN ORDER
#   0. Measures the two signal pins with the ADC, free and with the ESP32's
#      internal pull-up. I2C needs an external pull-up on each line, so both
#      should sit near 3.3 V on their own.
#   1. Scans the bus for address 0x24 with SDA and SCL in BOTH orders, on the
#      1/2 pads and on the 21/22 pads. This is the step that tells you whether
#      the two wires are the right way round.
#   2. Runs the real driver handshake (SAMConfiguration + GetFirmwareVersion)
#      on whichever orientation answered and prints the firmware version.
#   3. Polls that orientation for a tag and prints "TAG READ: <uid>".
#
# WIRING (DIP switches set to I2C, which on the Elechouse silkscreen is
# Channel 1 ON, Channel 2 OFF - "I2C 10")
#   ESP32 SDA -> module SDA   (the pad also labelled MOSI or TX)
#   ESP32 SCL -> module SCL   (the pad also labelled SSEL or RX)
#   ESP32 GND -> module GND   (common ground, essential)
#   PN532 VCC -> 3.3V, never 5V
#
# The module's I2C and HSU pins are the SAME physical pads, so if you kept the
# two data wires from an HSU setup the assignments are:
#   old HSU wire to module RXD (MOSI/SDA pad) -> SDA
#   old HSU wire to module TXD (SSEL/SCL pad) -> SCL
#
# After changing the DIP switches, POWER-CYCLE the module: unplug VCC, wait a
# few seconds, plug it back in. The switches are only read at power-up.

import time
from machine import Pin, I2C

ADDR = 0x24
# (scl, sda) GPIO numbers to try, in order. Both orders of each pair, because a
# swapped SDA/SCL is the most common I2C wiring mistake.
CANDIDATES = [(1, 2), (2, 1), (22, 21), (21, 22)]
POLL_SECONDS = 20

try:
    from machine import ADC
except ImportError:
    ADC = None

try:
    import pn532_iic
    HAVE_DRIVER = True
except ImportError:
    HAVE_DRIVER = False


def hexs(data):
    return " ".join("{:02X}".format(b) for b in data)


def volts(pin_number, pull=None):
    """Average ADC reading of a pin, or None when the pin has no ADC."""
    if ADC is None:
        return None
    try:
        if pull is None:
            Pin(pin_number, Pin.IN)
        else:
            Pin(pin_number, Pin.IN, pull)
        time.sleep_ms(20)
        channel = ADC(Pin(pin_number))
        total = 0
        for _ in range(16):
            total += channel.read()
        return total / 16.0 * 3.3 / 4095.0
    except Exception:
        return None


def scan_bus(scl, sda):
    """Return (devices, error_text) for one pin assignment."""
    try:
        bus = I2C(0, scl=Pin(scl), sda=Pin(sda), freq=100000)
    except Exception as exc:
        return None, "cannot create bus: %r" % (exc,)
    try:
        return bus.scan(), None
    except OSError as exc:
        return None, "scan failed: %r" % (exc,)
    finally:
        try:
            bus.deinit()
        except Exception:
            pass


def main():
    print("=== PN532 I2C (IIC) connectivity + tag-read test ===")
    if HAVE_DRIVER:
        print("pn532_iic.py found on the board.")
    else:
        print("pn532_iic.py is NOT on the board - only the bus scan will run.")
        print("  ampy -p <port> -b 115200 put "
              "esp32_nfc_detector/src/pn532/pn532_iic.py")
    print()

    print("--- step 0: are the two lines pulled up? ---")
    for pin_number in (1, 2):
        free = volts(pin_number)
        up = volts(pin_number, Pin.PULL_UP)
        if free is None:
            print("GPIO%-2d no ADC on this pin" % pin_number)
        else:
            note = ""
            if free < 2.0:
                note = "  <- weak or missing pull-up"
            print("GPIO%-2d free %.2f V   with internal pull-up %.2f V%s"
                  % (pin_number, free, up, note))
    print("I2C needs a pull-up on BOTH lines. They idle high (about 3.3 V)")
    print("when idle; a low or drifting line means no pull-up or a wrong pad.")
    print()

    print("--- step 1: bus scan for 0x24 ---")
    hits = []
    for scl, sda in CANDIDATES:
        devices, error = scan_bus(scl, sda)
        if error:
            print("scl=GPIO%-2d sda=GPIO%-2d  %s" % (scl, sda, error))
            continue
        if devices:
            print("scl=GPIO%-2d sda=GPIO%-2d  found %s"
                  % (scl, sda, ", ".join("0x%02X" % d for d in devices)))
        else:
            print("scl=GPIO%-2d sda=GPIO%-2d  nothing" % (scl, sda))
        if ADDR in (devices or []):
            hits.append((scl, sda))
    print()

    if not hits:
        print("RESULT: FAIL - no device answered at 0x%02X on any pin order." % ADDR)
        print()
        print("Check, in this order:")
        print("  1. DIP switches. I2C is Channel 1 ON, Channel 2 OFF (I2C 10).")
        print("  2. POWER-CYCLE the module after changing them (unplug VCC,")
        print("     wait a few seconds, replug). They are latched at power-up.")
        print("  3. SDA/SCL not swapped: SDA is the MOSI/TX pad, SCL the")
        print("     SSEL/RX pad. Both orders were tried above, so if neither")
        print("     worked the wires are on different pins or not connected.")
        print("  4. Pull-ups: both lines must idle high. If step 0 shows a")
        print("     low line, add 4.7k to 3.3 V on SDA and SCL.")
        print("  5. Common GND, and VCC on 3.3 V (never 5 V).")
        return

    scl, sda = hits[0]
    print("RESULT: PASS - the module answered at 0x%02X with scl=GPIO%d sda=GPIO%d."
          % (ADDR, scl, sda))
    if len(hits) > 1:
        print("  (it also answered as %s)"
              % ", ".join("scl=GPIO%d sda=GPIO%d" % h for h in hits[1:]))
    print()

    if not HAVE_DRIVER:
        print("Install pn532_iic.py to continue with the handshake.")
        return

    print("--- step 2: driver handshake ---")
    bus = I2C(0, scl=Pin(scl), sda=Pin(sda), freq=100000)
    reader = pn532_iic.PN532_IIC(bus)
    version = reader._sync_call(pn532_iic._COMMAND_GETFIRMWAREVERSION, b"", 800)
    if version is None:
        print("RESULT: FAIL - the module ACKs its address but never returns a")
        print("frame. Power-cycle it; if it still fails, try another bus speed.")
        return
    print("firmware:", hexs(version[2:]))
    print()

    print("--- step 3: reading tags for %d s - tap a card now ---" % POLL_SECONDS)
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
        if time.ticks_diff(time.ticks_ms(), last_report) > 3000:
            last_report = time.ticks_ms()
            print("  waiting for a tag... %d s left"
                  % (time.ticks_diff(deadline, time.ticks_ms()) // 1000))
        time.sleep_ms(50)

    if last_uid is None:
        print("No tag read, but the handshake worked, so the bus is fine.")
        print("Check the card and that the antenna is not shorted or covered.")
    else:
        print("Read the tag %d times; UID %s" % (reads, hexs(last_uid)))
    print()
    print("Use these pins in the firmware: i2c = I2C(0, scl=Pin(%d), sda=Pin(%d), "
          "freq=100000)" % (scl, sda))
    print("Done.")


main()
