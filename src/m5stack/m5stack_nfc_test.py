# M5Stack Unit NFC (ST25R3916) Connectivity & Tag Read Test
# for ESP32 boards running MicroPython
#
# Run from the host:
#   ampy -p /dev/tty.usbmodem1401 -b 115200 run esp32_nfc_detector/src/m5stack/m5stack_nfc_test.py

import time
from machine import Pin, I2C

ADDR = 0x50
CANDIDATES = [(2, 1), (1, 2), (22, 21), (21, 22), (6, 7), (7, 6)]
POLL_SECONDS = 20

def hexs(data):
    return " ".join("{:02X}".format(b) for b in data)

def scan_bus(scl, sda):
    try:
        bus = I2C(0, scl=Pin(scl), sda=Pin(sda), freq=100000)
        devices = bus.scan()
        bus.deinit()
        return devices, None
    except Exception as exc:
        return None, str(exc)

def main():
    print("=== M5Stack Unit NFC (ST25R3916) Connectivity & Tag Test ===")
    print()

    print("--- step 1: scanning I2C for address 0x50 ---")
    hits = []
    for scl, sda in CANDIDATES:
        devices, err = scan_bus(scl, sda)
        if err:
            continue
        if devices:
            print("scl=GPIO%-2d sda=GPIO%-2d  found %s" % (scl, sda, ", ".join("0x%02X" % d for d in devices)))
        if ADDR in (devices or []):
            hits.append((scl, sda))

    if not hits:
        print()
        print("RESULT: FAIL - no device answered at 0x50.")
        print("Check wiring:")
        print("  M5Stack Grove Yellow (SCL) -> ESP32 SCL")
        print("  M5Stack Grove White  (SDA) -> ESP32 SDA")
        print("  M5Stack Grove Red    (VCC) -> 3.3V or 5V")
        print("  M5Stack Grove Black  (GND) -> GND")
        return

    scl, sda = hits[0]
    print()
    print("RESULT: PASS - M5Stack Unit NFC found at 0x50 with scl=GPIO%d sda=GPIO%d." % (scl, sda))
    print()

    print("--- step 2: driver initialization & handshake ---")
    try:
        from st25r3916 import ST25R3916
    except ImportError:
        print("Error: st25r3916.py not found on board. Upload it with:")
        print("  ampy -p <port> -b 115200 put esp32_nfc_detector/src/m5stack/st25r3916.py")
        return

    bus = I2C(0, scl=Pin(scl), sda=Pin(sda), freq=100000)
    reader = ST25R3916(bus)
    print()

    print("--- step 3: polling for tags for %d s - tap a card now ---" % POLL_SECONDS)
    deadline = time.ticks_add(time.ticks_ms(), POLL_SECONDS * 1000)
    last_uid = None
    reads = 0
    last_report = time.ticks_ms()

    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        status, _ = reader.request()
        if status == reader.OK:
            uid_status, uid = reader.anticoll()
            if uid_status == reader.OK and uid:
                reads += 1
                if uid != last_uid:
                    last_uid = uid
                    print("TAG READ:", hexs(uid), "(%d bytes)" % len(uid))
                elif reads % 10 == 0:
                    print("  still reading", hexs(uid), "(%d reads)" % reads)

        if time.ticks_diff(time.ticks_ms(), last_report) > 3000:
            last_report = time.ticks_ms()
            remaining = time.ticks_diff(deadline, time.ticks_ms()) // 1000
            print("  waiting for a tag... %d s left" % remaining)

        time.sleep_ms(50)

    print()
    if last_uid is None:
        print("No tag read within %d seconds." % POLL_SECONDS)
    else:
        print("Tag read successfully %d times; UID: %s" % (reads, hexs(last_uid)))

if __name__ == "__main__":
    main()
