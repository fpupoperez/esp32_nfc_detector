# MicroPython driver for the Elechouse PN532 NFC module in SPI mode.
#
# The frame format (preamble / length checksum / TFI / data checksum / postamble)
# and the ACK + response protocol follow the PN532 datasheet; the command
# sequences and the InListPassiveTarget response layout are adapted from
# Adafruit's CircuitPython PN532 driver (MIT, Tony DiCola for Adafruit
# Industries), rewritten for machine.SPI and for the non-blocking
# request()/anticoll() surface the rest of this firmware expects.
#
# SPI specifics: the PN532 shifts bits LSB-first while virtually every SPI
# peripheral is MSB-first, so every byte crossing the wire is bit-reversed.
# Each access starts with a one-byte opcode - 0x01 to write data, 0x02 to poll
# the status byte, 0x03 to read data - followed by the payload. The status byte
# comes back bit-reversed too, and its LSB set means "a frame is ready"; that is
# what makes the non-blocking poll possible: request() only ever submits.
#
# Usage: spi = SPI(1, baudrate=1000000, polarity=0, phase=0,
#                 sck=Pin(18), mosi=Pin(23), miso=Pin(19))
#        reader = PN532_SPI(spi, Pin(5, Pin.OUT))
#
# The module's DIP switches must select SPI, and the module must be powered from
# 3.3 V with a common GND. The Elechouse board needs its CS line driven by us.

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

_PREAMBLE = b"\x00\x00\xff"
_HOSTTOPN532 = 0xD4
_PN532TOHOST = 0xD5
_COMMAND_GETFIRMWAREVERSION = 0x02
_COMMAND_SAMCONFIGURATION = 0x14
_COMMAND_INLISTPASSIVETARGET = 0x4A
_MAX_RX = 1024

_SPI_STATREAD = 0x02
_SPI_DATAWRITE = 0x01
_SPI_DATAREAD = 0x03
_SPI_READY = 0x01


def reverse_bit(num):
    """Turn an LSB byte into an MSB byte and vice versa.

    The PN532 speaks LSB-first over SPI, so this is applied to every byte in
    both directions.
    """
    result = 0
    for _ in range(8):
        result <<= 1
        result += num & 1
        num >>= 1
    return result


class PN532_SPI:
    """PN532 (SPI) driver.

    Exposes the same surface as the MFRC522 driver used by the RC522 variant of
    this firmware - OK/NOTAGERR/ERR status codes, REQIDL/REQALL constants and a
    request()/anticoll() pair - so main.py's polling loop is unchanged.

    request() performs one non-blocking poll step: it reads whatever the module
    has already produced and returns, without waiting for the answer. It hands a
    freshly read UID to the next anticoll() call.
    """

    OK = 0
    NOTAGERR = 1
    ERR = 2

    REQIDL = 0x26
    REQALL = 0x52

    RESP_TIMEOUT_MS = 1500  # give up on an unanswered poll command after this

    def __init__(self, spi, cs, debug=False):
        self.spi = spi
        self.cs = cs
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

    def _wakeup(self):
        """Run the boot-time handshake.

        This is the synchronous part the MFRC522 driver also does inside its
        constructor, before the non-blocking main loop starts. A single 0x00
        byte on the bus brings the SPI interface out of its idle state, then
        SAMConfiguration prepares the module for polling and GetFirmwareVersion
        confirms it is actually answering.
        """
        self.cs.value(0)
        try:
            try:
                self.spi.write(b"\x00")
            except OSError:
                # A failed idle byte is not fatal on its own; the handshake
                # below decides whether the bus is actually alive.
                pass
        finally:
            self.cs.value(1)
        _sleep_ms(2)
        if self._sync_call(_COMMAND_SAMCONFIGURATION, b"\x01\x14\x01", 500) is None:
            print("PN532: no reply to SAMConfiguration - check that the DIP "
                  "switches select SPI and that SCK/MOSI/MISO/CS are wired")
            return
        version = self._sync_call(_COMMAND_GETFIRMWAREVERSION, b"", 500)
        if version is None:
            print("PN532: no reply to GetFirmwareVersion - module silent on SPI")
        else:
            print("PN532 firmware:", " ".join(["{:02X}".format(b) for b in version[2:]]))

    def _xfer(self, tx, rx_len):
        """Shift `tx` out and `rx_len` bytes in, with CS held for the exchange.

        Returns None when the bus raised, so callers can treat a transient
        failure exactly like "nothing to read" instead of crashing the loop.
        """
        rx = bytearray(rx_len)
        self.cs.value(0)
        try:
            self.spi.write_readinto(bytes(tx), rx)
        except OSError:
            return None
        finally:
            self.cs.value(1)
        return rx

    def _send(self, command, params=b""):
        data = bytes([_HOSTTOPN532, command]) + bytes(params)
        length = len(data)
        checksum = 0xFF + sum(data)
        frame = (_PREAMBLE + bytes([length, (~length + 1) & 0xFF]) + data +
                 bytes([~checksum & 0xFF, 0x00]))
        # Prefix the data-write opcode and flip every byte to LSB-first.
        out = bytes([reverse_bit(b) for b in bytes([_SPI_DATAWRITE]) + frame])
        if self.debug:
            print("PN532 TX:", " ".join(["{:02X}".format(b) for b in out]))
        self._xfer(out, 0)
    def _drain(self):
        """Read the status byte, then the payload if a frame is waiting.

        Everything arrives bit-reversed, so bytes are flipped back on the way in.
        """
        status = self._xfer(bytes([reverse_bit(_SPI_STATREAD), 0x00]), 2)
        if status is None or len(status) < 2:
            return
        if reverse_bit(status[1]) & _SPI_READY == 0:
            return  # busy / no frame yet
        # One opcode byte plus the payload; the last byte is a trailing status.
        raw = self._xfer(bytes([reverse_bit(_SPI_DATAREAD)]) + b"\x00" * _MAX_RX,
                         _MAX_RX + 1)
        if raw is None:
            return
        chunk = bytes([reverse_bit(b) for b in raw[1:]])
        if chunk:
            self._rx.extend(chunk)
            if len(self._rx) > _MAX_RX:
                # Rebinding rather than del: MicroPython cannot delete items
                # from a bytearray in place.
                self._rx = bytearray(self._rx[len(self._rx) - _MAX_RX:])

    def _pop_unit(self):
        """Consume one complete unit from the head of the receive buffer.

        Returns None when more bytes are needed, "junk" for units to ignore, or
        ("frame", data) for a full response frame, where data holds the transfer
        byte, the echoed command and the response payload.

        The buffer is advanced by rebinding self._rx to a fresh bytearray, never
        by `del buf[...]`: MicroPython does not implement scalar-index deletion
        on a bytearray, so deleting raised TypeError on-device even though it
        works on CPython.
        """
        buf = self._rx
        n = len(buf)
        # Resync: find the next plausible frame start (00 00 FF).
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
        if n < 5:
            return None
        frame_len = buf[3]
        lcs = buf[4]
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
        """Read the bus and fold every complete frame into the driver state."""
        self._drain()
        while True:
            unit = self._pop_unit()
            if unit is None:
                break
            if unit == "junk":
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
            while True:
                unit = self._pop_unit()
                if unit is None:
                    break
                if unit == "junk":
                    continue
                data = unit[1]
                if len(data) >= 2 and data[1] == command + 1:
                    return data
            _sleep_ms(1)
        return None
