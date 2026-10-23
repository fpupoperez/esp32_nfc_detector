from machine import Pin, I2C, UART
import time

found_iic = None

print("=== Scanning I2C for PN532 @0x24 ===")
for scl,sda in [(6,7),(7,6),(1,2),(2,1)]:
    try:
        b = I2C(0, scl=Pin(scl), sda=Pin(sda), freq=100000)
        scan = b.scan()
        if 0x24 in scan:
            print('I2C FOUND: scl=%d sda=%d' % (scl,sda))
            found_iic = (scl,sda)
            b.deinit()
            break
        b.deinit()
    except:
        pass

if found_iic:
    print("=== IIC MODE DETECTED - trying to read tag ===")
    try:
        from pn532_iic import PN532_IIC
        scl,sda = found_iic
        bus = I2C(0, scl=Pin(scl), sda=Pin(sda), freq=100000)
        r = PN532_IIC(bus)
        time.sleep_ms(100)
        print("Handshake done, polling for 15s (present a tag)...")
        for i in range(150):
            try:
                if r.request(r.REQIDL)[0] == r.OK:
                    st, uid = r.anticoll()
                    if st == r.OK and uid:
                        print("TAG READ:", " ".join("%02X" % b for b in uid))
                        break
            except:
                pass
            time.sleep_ms(100)
        else:
            print("No tag read in 15s")
    except Exception as e:
        print("ERR:", e)
else:
    print("=== No IIC @0x24, scanning HSU ===")
    try:
        import pn532
        for tx,rx in [(1,2),(2,1),(6,7),(7,6)]:
            try:
                u = UART(2, baudrate=115200, bits=8, parity=None, stop=1, tx=Pin(tx), rx=Pin(rx))
                time.sleep_ms(100)
                r = pn532.PN532(u)
                v = r._sync_call(pn532._COMMAND_GETFIRMWAREVERSION, b"", 1500)
                if v:
                    print('HSU FOUND: tx=%d rx=%d fw:' % (tx,rx), " ".join("%02X" % b for b in v[2:]))
                    print("Polling for 15s (present a tag)...")
                    for i in range(150):
                        try:
                            if r.request(r.REQIDL)[0] == r.OK:
                                st, uid = r.anticoll()
                                if st == r.OK and uid:
                                    print("TAG READ:", " ".join("%02X" % b for b in uid))
                                    break
                        except:
                            pass
                        time.sleep_ms(100)
                    else:
                        print("No tag read in 15s")
                    u.deinit()
                    break
                u.deinit()
            except:
                try: u.deinit()
                except: pass
    except Exception as e:
        print("ERR:", e)
print("=== DONE ===")
