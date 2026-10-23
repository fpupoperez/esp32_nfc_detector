# MicroPython driver for the Elechouse PN532 NFC module in HSU (UART) mode.
#
# The frame format (preamble / length checksum / TFI / data checksum / postamble)
# and the ACK + response protocol follow the PN532 datasheet; the command
# sequences and the InListPassiveTarget response layout are adapted from
# Adafruit's CircuitPython PN532 driver (MIT, Tony DiCola for Adafruit
# Industries), rewritten for machine.UART and for the non-blocking
# request()/anticoll() surface the rest of this firmware expects.
#
# Usage: reader = PN532(uart)
#        uart = UART(2, baudrate=115200, bits=8, parity=None, stop=1,
#                    tx=Pin(...), rx=Pin(...))
#
# The module's DIP switches must select HSU, and the ESP32 TX pin must go to
# the module's RXD (crossed) with a common GND.

import time

try:
    _ticks_ms = time.ticks_ms
    _ticks_diff = time.ticks_diff
    _sleep_ms = time.sleep_ms
except AttributeError:  # host-side tests running on CPython
    def _ticks_ms():
        return int(time.time() * 1000)

    def _ticks_diff(a, b):
        return a - b

    def _sleep_ms(ms):
        time.sleep(ms / 1000.0)

_ACK = b"\x00\x00\xff\x00\xff\x00"
_PREAMBLE = b"\x00\x00\xff"
_HOSTTOPN532 = 0xD4
_PN532TOHOST = 0xD5
_COMMAND_GETFIRMWAREVERSION = 0x02
_COMMAND_SAMCONFIGURATION = 0x14
_COMMAND_INLISTPASSIVETARGET = 0x4A
# Wake-up pattern for HSU: 0x55 0x00 0x00 0x00 preceded by an extra 0x55 the
# module tolerates, then zero padding until it sees a valid frame.
_WAKEUP = b"\x55\x55" + b"\x00" * 15
_MAX_RX = 1024


class PN532:
    """PN532 (HSU/UART) driver.

    Exposes the same surface as the MFRC522 driver used by the RC522 variant of
    this firmware - OK/NOTAGERR/ERR status codes, REQIDL/REQALL constants and a
    request()/anticoll() pair - so main.py's polling loop is unchanged.

    request() performs one non-blocking poll step: it never sleeps or waits for
    the module. It hands a freshly read UID to the next anticoll() call.
    """

    OK = 0
    NOTAGERR = 1
    ERR = 2

    REQIDL = 0x26
    REQALL = 0x52

    RESP_TIMEOUT_MS = 1500  # give up on an unanswered poll command after this

    def __init__(self, uart, debug=False):
        self.uart = uart
        self.debug = debug
        self._rx = bytearray()
        self._uid = None
        self._pending = False
        self._pending_at = 0
        self._wakeup()

    # --- MFRC522-compatible surface -------------------------------------------

    def request(self, mode=REQIDL):
        """Poll for a passive ISO14443-A tag without blocking.

        Returns (OK, tag_type) once a UID has been read, otherwise
        (NOTAGERR, None). The mode argument is accepted for compatibility with
        the MFRC522 call site; the PN532 always polls for ISO14443-A targets.
        """
        self._pump()
        if self._uid is not None:
            return (self.OK, 4)
        if self._pending:
            if _ticks_diff(_ticks_ms(), self._pending_at) < self.RESP_TIMEOUT_MS:
                return (self.NOTAGERR, None)
            # The command will never be answered: drop it and any stale bytes.
            self._pending = False
            self._rx = bytearray()
        self._send(_COMMAND_INLISTPASSIVETARGET, b"\x01\x00")
        self._pending = True
        self._pending_at = _ticks_ms()
        return (self.NOTAGERR, None)

    def anticoll(self):
        """Return the UID captured by the last successful request()."""
        if self._uid is None:
            return (self.ERR, None)
        uid = self._uid
        self._uid = None
        return (self.OK, uid)

    # --- internals ------------------------------------------------------------

    # How many times the constructor re-tries the boot-time handshake before it
    # gives up. The PN532's HSU interface can be left mid-frame by a host that
    # was interrupted (a reset, a host tool that closed the port), and the wake
    # burst plus a fresh SAMConfiguration brings it back. A cold module needs a
    # power-cycle; a desynced one recovers here.
    HANDSHAKE_ATTEMPTS = 3

    def _wakeup(self):
        """Wake the module from HSU standby and run the boot-time handshake.

        This is the synchronous part the MFRC522 driver also does inside its
        constructor, before the non-blocking main loop starts.
        """
        for _attempt in range(self.HANDSHAKE_ATTEMPTS):
            self.uart.write(_WAKEUP)
            _sleep_ms(20)
            self._drain()
            # Drop anything stale so a late reply from a previous command
            # cannot be mistaken for the answer to this one.
            self._rx = bytearray()
            if self._sync_call(_COMMAND_SAMCONFIGURATION, b"\x01\x14\x01",
                               500) is not None:
                break
        else:
            print("PN532: no reply to SAMConfiguration - check that the DIP "
                  "switches select HSU and that TX/RX are wired crossed")
            return
        version = self._sync_call(_COMMAND_GETFIRMWAREVERSION, b"", 500)
        if version is None:
            print("PN532: no reply to GetFirmwareVersion - module silent on UART")
        else:
            print("PN532 firmware:", " ".join(["{:02X}".format(b) for b in version[2:]]))

    def _send(self, command, params=b""):
        data = bytes([_HOSTTOPN532, command]) + bytes(params)
        length = len(data)
        checksum = 0xFF + sum(data)
        frame = (_PREAMBLE + bytes([length, (~length + 1) & 0xFF]) + data +
                 bytes([~checksum & 0xFF, 0x00]))
        if self.debug:
            print("PN532 TX:", " ".join(["{:02X}".format(b) for b in frame]))
        self.uart.write(frame)

    def _drain(self):
        waiting = self.uart.any()
        if not waiting:
            return
        chunk = self.uart.read(waiting)
        if chunk:
            self._rx.extend(chunk)
            if len(self._rx) > _MAX_RX:
                # Rebinding rather than del: MicroPython cannot delete items
                # from a bytearray in place.
                self._rx = bytearray(self._rx[len(self._rx) - _MAX_RX:])

    def _pop_unit(self):
        """Consume one complete unit from the head of the receive buffer.

        Returns None when more bytes are needed, "ack"/"junk" for units to
        ignore, or ("frame", data) for a full response frame, where data holds
        the transfer byte, the echoed command and the response payload.

        The buffer is always advanced by *rebinding* self._rx to a fresh
        bytearray rather than by `del buf[...]`: MicroPython does not implement
        scalar-index deletion on a bytearray (and its slice-deletion path is
        picky about full-range slices), so deleting from the buffer raised
        TypeError on-device even though it works on CPython.
        """
        buf = self._rx
        n = len(buf)
        # Resync: find the next plausible frame start (00 00 FF). This matters
        # at boot because HSU echoes the wake-up pattern back, so the buffer
        # opens with the 0x55 bytes of _WAKEUP rather than a frame.
        if n < 3:
            return None
        start = -1
        limit = n - 2
        for i in range(limit):
            if buf[i] == 0x00 and buf[i + 1] == 0x00 and buf[i + 2] == 0xFF:
                start = i
                break
        if start < 0:
            # No frame start yet: keep only a possible 00 00 run at the tail.
            if buf[n - 2:n] == b"\x00\x00":
                keep = 2
            elif buf[n - 1] == 0x00:
                keep = 1
            else:
                keep = 0
            self._rx = bytearray(buf[len(buf) - keep:]) if keep else bytearray()
            return None
        if start:
            self._rx = bytearray(buf[start:])
            return "junk"
        if n >= 6 and buf[:6] == _ACK:
            self._rx = bytearray(buf[6:])
            return "ack"
        if n < 5:
            return None
        frame_len = buf[3]
        lcs = buf[4]
        if frame_len == 0x00 and lcs == 0xFF:
            # ACK-shaped but not an exact match: one more byte decides.
            if n < 6:
                return None
            self._rx = bytearray(buf[1:])
            return "junk"
        if (frame_len + lcs) & 0xFF != 0:
            self._rx = bytearray(buf[1:])
            return "junk"
        total = 7 + frame_len
        if n < total:
            return None
        data = bytes(buf[5:5 + frame_len])
        if (sum(buf[5:5 + frame_len + 1]) & 0xFF) != 0:
            self._rx = bytearray(buf[1:])
            return "junk"
        self._rx = bytearray(buf[total:])
        return ("frame", data)

    def _pump(self):
        """Drain the UART and fold every complete frame into the driver state."""
        self._drain()
        while True:
            unit = self._pop_unit()
            if unit is None:
                break
            if unit == "ack" or unit == "junk":
                continue
            data = unit[1]
            if len(data) < 2 or data[0] != _PN532TOHOST:
                continue
            if not self._pending or data[1] != _COMMAND_INLISTPASSIVETARGET + 1:
                continue
            # Response layout after the echoed command byte:
            # NbTg, Tg, SENS_RES (2), SEL_RES, NFCID length, NFCID...
            targets = data[2]
            self._pending = False
            if targets == 0:
                continue
            if len(data) < 8:
                continue
            uid_len = data[7]
            if uid_len < 4 or uid_len > 10 or len(data) < 8 + uid_len:
                continue
            self._uid = data[8:8 + uid_len]

    def _sync_call(self, command, params, timeout_ms):
        """Blocking request/response exchange used only during __init__."""
        self._send(command, params)
        start = _ticks_ms()
        while _ticks_diff(_ticks_ms(), start) < timeout_ms:
            self._drain()
            unit = self._pop_unit()
            if unit is None:
                _sleep_ms(1)
                continue
            if unit == "ack" or unit == "junk":
                continue
            data = unit[1]
            if len(data) >= 2 and data[1] == command + 1:
                return data
        return None
