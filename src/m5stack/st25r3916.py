# MicroPython driver for the M5Stack Unit NFC (ST25R3916) in I2C mode.
#
# Exposes the same surface as MFRC522 and PN532 drivers used by the rest of this
# firmware: OK/NOTAGERR/ERR status codes, REQIDL/REQALL constants, and a
# request()/anticoll() pair so that the main application loop remains identical.
#
# The M5Stack Unit NFC connects via standard Grove (HY2.0-4P) I2C port at
# default 7-bit slave address 0x50.

import time

try:
    _ticks_ms = time.ticks_ms
    _ticks_diff = time.ticks_diff
    _sleep_ms = time.sleep_ms
except AttributeError:
    def _ticks_ms():
        return int(time.time() * 1000)

    def _ticks_diff(a, b):
        return a - b

    def _sleep_ms(ms):
        time.sleep(ms / 1000.0)

# ST25R3916 Registers (Space A)
_REG_IO_CONF1       = 0x00
_REG_IO_CONF2       = 0x01
_REG_OP_CONTROL     = 0x02
_REG_MODE           = 0x03
_REG_BIT_RATE       = 0x04
_REG_ISO14443A_CONF = 0x05
_REG_RX_CONF1       = 0x0B
_REG_RX_CONF2       = 0x0C
_REG_IRQ_MAIN       = 0x1A
_REG_IRQ_TIMER      = 0x1B
_REG_IRQ_ERROR      = 0x1C
_REG_FIFO_STATUS1   = 0x1E
_REG_FIFO_STATUS2   = 0x1F
_REG_NUM_TX_BYTES1  = 0x22
_REG_NUM_TX_BYTES2  = 0x23
_REG_TX_DRIVER      = 0x28
_REG_REGULATOR      = 0x2C
_REG_IC_IDENTITY    = 0x3F

# ST25R3916 Direct Commands
_CMD_SET_DEFAULT             = 0xC1
_CMD_STOP_ALL                = 0xC2
_CMD_CLEAR_FIFO              = 0xC3
_CMD_TRANSMIT_WITH_CRC       = 0xC4
_CMD_TRANSMIT_WITHOUT_CRC    = 0xC5
_CMD_TRANSMIT_REQA           = 0xC6
_CMD_TRANSMIT_WUPA           = 0xC7
_CMD_RESET_RX_GAIN           = 0xD5
_CMD_ADJUST_REGULATORS       = 0xD6

I2C_ADDRESS = 0x50


class ST25R3916:
    """ST25R3916 NFC Reader Driver for MicroPython (M5Stack Unit NFC)."""

    OK = 0
    NOTAGERR = 1
    ERR = 2

    REQIDL = 0x26
    REQALL = 0x52

    def __init__(self, i2c, address=I2C_ADDRESS, debug=False):
        self.i2c = i2c
        self.address = address
        self.debug = debug
        self._uid = None
        self._wakeup()

    # --- Register & Direct Command I/O ----------------------------------------

    def _read_reg(self, reg):
        """Read a single register byte in Space A (address masked with 0x40 read bit)."""
        return self.i2c.readfrom_mem(self.address, 0x40 | (reg & 0x3F), 1)[0]

    def _write_reg(self, reg, val):
        """Write a single register byte in Space A."""
        self.i2c.writeto_mem(self.address, reg & 0x3F, bytes([val]))

    def _direct_cmd(self, cmd_byte):
        """Send a Direct Command code."""
        try:
            self.i2c.writeto(self.address, bytes([cmd_byte]))
        except OSError:
            pass

    def _clear_irqs(self):
        """Clear interrupt registers by reading them."""
        try:
            self._read_reg(_REG_IRQ_MAIN)
            self._read_reg(_REG_IRQ_TIMER)
            self._read_reg(_REG_IRQ_ERROR)
        except OSError:
            pass

    def _transceive(self, data, with_crc=True, timeout_ms=30):
        """Send payload via FIFO and wait for response."""
        self._direct_cmd(_CMD_CLEAR_FIFO)
        self._direct_cmd(_CMD_RESET_RX_GAIN)
        self._clear_irqs()

        n = len(data)
        # NUM_TX_BYTES1 holds n >> 5, NUM_TX_BYTES2 holds (n & 0x1F) << 3
        self._write_reg(_REG_NUM_TX_BYTES1, n >> 5)
        self._write_reg(_REG_NUM_TX_BYTES2, (n & 0x1F) << 3)

        # Load FIFO (prefix 0x80)
        try:
            self.i2c.writeto(self.address, bytes([0x80]) + bytes(data))
        except OSError:
            return None

        # Execute transmit
        self._direct_cmd(_CMD_TRANSMIT_WITH_CRC if with_crc else _CMD_TRANSMIT_WITHOUT_CRC)

        start = _ticks_ms()
        while _ticks_diff(_ticks_ms(), start) < timeout_ms:
            try:
                irq = self._read_reg(_REG_IRQ_MAIN)
                if irq & 0x10:  # RXE: End of receive
                    break
            except OSError:
                pass
            _sleep_ms(1)

        try:
            fifo_len = self._read_reg(_REG_FIFO_STATUS1)
            if fifo_len > 0:
                # Read from FIFO (mode 0x9F)
                return self.i2c.readfrom_mem(self.address, 0x9F, fifo_len)
        except OSError:
            pass
        return None

    # --- Initialization -------------------------------------------------------

    def _wakeup(self):
        """Initialize the ST25R3916 chip for ISO14443-A NFC reader mode."""
        # Wake I2C bus from standby
        try:
            self.i2c.writeto(self.address, b"")
        except OSError:
            pass
        _sleep_ms(10)

        # Stop any active tasks and reset
        self._direct_cmd(_CMD_STOP_ALL)
        _sleep_ms(2)
        self._direct_cmd(_CMD_SET_DEFAULT)
        _sleep_ms(5)

        # Silicon errata fix for internal overheat protection:
        # 3-byte sequence FCh 04h 10h prevents premature shutdown at room temperature
        try:
            self.i2c.writeto(self.address, bytes([0xFC, 0x04, 0x10]))
        except OSError:
            pass
        _sleep_ms(2)

        # IO Configuration 2: sup3V = 1 (bit 7) for 3.3V supply
        self._write_reg(_REG_IO_CONF2, 0x80)

        # Operation Control: en=1 (oscillator on), rx_en=1, tx_en=1 (RF field on)
        self._write_reg(_REG_OP_CONTROL, 0xC8)
        _sleep_ms(5)

        # Mode Definition: ISO14443A Initiator (mode = 0x01 << 3 = 0x08)
        self._write_reg(_REG_MODE, 0x08)
        self._write_reg(_REG_BIT_RATE, 0x00)        # 106 kbps tx/rx
        self._write_reg(_REG_ISO14443A_CONF, 0x00)  # Standard ISO14443A framing
        self._write_reg(_REG_RX_CONF1, 0xD0)        # AM channel, 212kHz subcarrier
        self._write_reg(_REG_RX_CONF2, 0x20)        # Fast AGC enabled
        self._write_reg(_REG_TX_DRIVER, 0x00)       # Full power driver resistance

        # Adjust regulators
        self._direct_cmd(_CMD_ADJUST_REGULATORS)
        _sleep_ms(5)

        try:
            identity = self._read_reg(_REG_IC_IDENTITY)
            chip_type = (identity >> 3) & 0x1F
            rev = identity & 0x07
            if chip_type == 0x05:
                print("ST25R3916 (M5Stack Unit NFC) Online - IC Identity: 0x{:02X} (rev {})".format(identity, rev))
            else:
                print("M5Stack NFC: device responded with identity 0x{:02X}".format(identity))
        except Exception as e:
            print("M5Stack NFC: failed to read IC identity:", e)

    # --- MFRC522-compatible surface -------------------------------------------

    def request(self, mode=REQIDL):
        """Poll for a passive ISO14443-A tag without blocking.

        Returns (OK, tag_type) once a tag UID has been captured, otherwise
        (NOTAGERR, None).
        """
        self._direct_cmd(_CMD_CLEAR_FIFO)
        self._direct_cmd(_CMD_RESET_RX_GAIN)
        self._clear_irqs()

        # Send WUPA (0xC7) or REQA (0xC6) short frame
        self._direct_cmd(_CMD_TRANSMIT_WUPA if mode == self.REQALL else _CMD_TRANSMIT_WUPA)

        start = _ticks_ms()
        while _ticks_diff(_ticks_ms(), start) < 12:
            try:
                irq = self._read_reg(_REG_IRQ_MAIN)
                if irq & 0x10:  # RXE: End of receive
                    break
            except OSError:
                pass
            _sleep_ms(1)

        try:
            fifo_len = self._read_reg(_REG_FIFO_STATUS1)
        except OSError:
            fifo_len = 0

        if fifo_len == 0:
            return (self.NOTAGERR, None)

        try:
            atqa = self.i2c.readfrom_mem(self.address, 0x9F, fifo_len)
        except OSError:
            return (self.NOTAGERR, None)

        # Step 2: Anticollision Cascade Level 1 (0x93 0x20 without CRC)
        cl1_resp = self._transceive([0x93, 0x20], with_crc=False)
        if not cl1_resp or len(cl1_resp) < 5:
            return (self.NOTAGERR, None)

        uid_part = cl1_resp[:4]
        bcc = cl1_resp[4]
        if (uid_part[0] ^ uid_part[1] ^ uid_part[2] ^ uid_part[3]) != bcc:
            return (self.NOTAGERR, None)

        # Step 3: Select Cascade Level 1 (with CRC)
        sel1 = self._transceive([0x93, 0x70] + list(cl1_resp[:5]), with_crc=True)
        if not sel1:
            return (self.NOTAGERR, None)

        if uid_part[0] == 0x88:  # Cascade tag: 7-byte UID
            # Step 4: Anticollision Cascade Level 2 (0x95 0x20)
            cl2_resp = self._transceive([0x95, 0x20], with_crc=False)
            if not cl2_resp or len(cl2_resp) < 5:
                return (self.NOTAGERR, None)
            uid2 = cl2_resp[:4]
            bcc2 = cl2_resp[4]
            if (uid2[0] ^ uid2[1] ^ uid2[2] ^ uid2[3]) != bcc2:
                return (self.NOTAGERR, None)
            self._transceive([0x95, 0x70] + list(cl2_resp[:5]), with_crc=True)
            self._uid = bytes(uid_part[1:4]) + bytes(uid2)
        else:
            self._uid = bytes(uid_part)

        return (self.OK, 4)

    def anticoll(self):
        """Return the UID captured by the last successful request()."""
        if self._uid is None:
            return (self.ERR, None)
        uid = self._uid
        self._uid = None
        return (self.OK, uid)


# Aliases for compatibility
M5StackNFC = ST25R3916
MFRC522 = ST25R3916
