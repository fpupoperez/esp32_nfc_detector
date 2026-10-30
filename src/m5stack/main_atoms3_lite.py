import time
import machine
from machine import Pin, I2C
import network
import usocket as socket
import urequests
import json
from st25r3916 import ST25R3916

# --- HARDWARE DEFINITIONS (M5Stack AtomS3 Lite defaults) ---
# Preconfigured for the M5Stack AtomS3 Lite, reading an M5Stack Unit NFC
# (ST25R3916) in I2C mode at address 0x50 via the onboard Grove HY2.0-4P
# Port A (White/SCL=GPIO1, Yellow/SDA=GPIO2, Red=5V, Black=GND).
RESET_PORTAL_PIN = 41 # Onboard user button on AtomS3 Lite (GPIO41, active-low)
STATUS_LED_PIN   = 35 # Plain-LED fallback only; onboard WS2812 RGB LED is on GPIO35 by default

# M5Stack Unit NFC I2C Pins (AtomS3 Lite Grove Port A: SCL=GPIO1, SDA=GPIO2)
i2c = I2C(0, scl=Pin(1), sda=Pin(2), freq=100000)

# --- CONSTANTS ---
CONFIG_FILE = "config.json"
POLL_INTERVAL = 0.2
DEBOUNCE_THRESHOLD = 3
MAX_PRESENT_TIME = 15.0

# --- STATE VARIABLES ---
config_data = {}
active_session = {
    "tag_present": False,
    "last_uid": None,
    "consecutive_misses": 0,
    "inserted_at": 0.0,
    "timeout_triggered": False
}

# --- STATUS LED DEVICE (plain GPIO LED or onboard Neopixel/WS2812) ---
# init_status_led() picks the device at boot: if NEOPIXEL_PIN is set in the
# config, the onboard WS2812 is used (e.g. GPIO48 on the ESP32-S3 Super-Mini,
# GPIO21 on the ESP32-S3 Zero); otherwise a plain LED on STATUS_LED_PIN.
neopixel_led = None
led_pin = None
LED_COLORS = {
    "portal": (0, 0, 255),        # Blue: AP/captive portal + Wi-Fi connecting
    "tag":    (0, 255, 0),        # Green (fixed): NFC tag inserted
    "no_tag": (255, 165, 0),      # Orange (fixed): no NFC tag on the reader
    "retire": (255, 255, 0),      # Yellow: retire confirmation blink (request sent)
}

# Non-Blocking LED Controller State
led_state = {
    "mode": "idle",       # Modes: "portal", "idle", "burst", "retire_blink"
    "last_toggle": 0,
    "burst_until": 0,
    "blink_until": 0,
    "state": 0
}
led_last_color = None  # Cache so the Neopixel is only re-written when the color changes

def render_led(on, mode=None):
    """Drives the active LED device. Neopixel shows fixed status colors, a plain LED on/off."""
    global led_last_color
    if neopixel_led is not None:
        mode = mode or led_state["mode"]
        if not on:
            color = (0, 0, 0)
        elif mode == "portal":
            color = LED_COLORS["portal"]
        elif mode == "retire_blink":
            color = LED_COLORS["retire"]
        elif active_session["tag_present"]:
            color = LED_COLORS["tag"]    # Fixed green while the tag is on the reader
        else:
            color = LED_COLORS["no_tag"] # Fixed orange while no tag is detected
        if color != led_last_color:
            led_last_color = color
            neopixel_led[0] = color
            try:
                neopixel_led.write()
            except Exception as e:
                print("Neopixel write failed:", e)
    elif led_pin is not None:
        led_pin.value(1 if on else 0)

def init_status_led():
    """Selects the status LED: onboard Neopixel (NEOPIXEL_PIN config) or plain GPIO."""
    global neopixel_led, led_pin, led_last_color
    np_pin = str(config_data.get("NEOPIXEL_PIN", "")).strip()
    if np_pin:
        try:
            try:
                from neopixel import NeoPixel
            except ImportError:
                from machine import NeoPixel
            neopixel_led = NeoPixel(Pin(int(np_pin), Pin.OUT), 1)
            led_pin = None
            led_last_color = None
            render_led(False)
            print("Neopixel status LED enabled on GPIO" + np_pin)
            return
        except Exception as e:
            print("Neopixel init failed, falling back to plain LED:", e)
            neopixel_led = None
    neopixel_led = None
    led_last_color = None
    led_pin = Pin(STATUS_LED_PIN, Pin.OUT)
    led_pin.value(0)

def update_led():
    """Calculates and renders non-blocking blinking sequences based on system state."""
    now = time.ticks_ms()

    # 1. Retire confirmation: 2s of 500ms yellow blinks (plain LED: on/off),
    #    then the LED settles back to its normal status color.
    if led_state["mode"] == "retire_blink":
        if active_session["tag_present"] or time.ticks_diff(led_state["blink_until"], now) <= 0:
            led_state["mode"] = "idle" # Window expired (or a new tag arrived) -> steady status
        else:
            if time.ticks_diff(now, led_state["last_toggle"]) >= 500:
                led_state["state"] = 1 - led_state["state"]
                led_state["last_toggle"] = now
            render_led(bool(led_state["state"]), "retire_blink")
            return

    # 2. Handle short high-priority transaction burst overrides
    if led_state["mode"] == "burst":
        if time.ticks_diff(led_state["burst_until"], now) > 0:
            render_led(True, "burst") # Keep LED on during the burst window
            return
        else:
            # Burst expired, revert smoothly to regular operational modes
            led_state["mode"] = "idle"
            led_state["last_toggle"] = now

    # 3. Handle Portal Mode Blink Pattern (500ms intervals)
    if led_state["mode"] == "portal":
        if time.ticks_diff(now, led_state["last_toggle"]) >= 500:
            led_state["state"] = 1 - led_state["state"]
            render_led(bool(led_state["state"]), "portal")
            led_state["last_toggle"] = now

    # 4. Handle Idle Scan Mode Pattern
    elif led_state["mode"] == "idle":
        if neopixel_led is not None:
            # Fixed status color: green while a tag is inserted, orange otherwise
            render_led(True, "idle")
        else:
            # Plain LED: brief heartbeat pulse every 3000ms
            diff = time.ticks_diff(now, led_state["last_toggle"])
            if led_state["state"] == 0 and diff >= 3000:
                led_state["state"] = 1
                render_led(True, "idle")
                led_state["last_toggle"] = now
            elif led_state["state"] == 1 and diff >= 60: # Keep on for only 60ms
                led_state["state"] = 0
                render_led(False)
                led_state["last_toggle"] = now

def trigger_led_burst():
    """Forces an immediate 300ms high-brightness blink override (plain LED);
    on a Neopixel the steady green/orange status color shows the tag transition."""
    led_state["mode"] = "burst"
    led_state["burst_until"] = time.ticks_add(time.ticks_ms(), 300)
    render_led(True, "burst")

def trigger_retire_blink():
    """After a tag retire request was sent: blink yellow every 500ms for 2 seconds
    (plain LED: on/off) so the user sees the MQTT/webhook message went out,
    then update_led() settles the Neopixel back to fixed orange."""
    led_state["mode"] = "retire_blink"
    led_state["blink_until"] = time.ticks_add(time.ticks_ms(), 2000)
    led_state["last_toggle"] = time.ticks_ms()
    led_state["state"] = 1 # Start with the blink ON
    render_led(True, "retire_blink")

# --- LIGHTWEIGHT CAPTIVE PORTAL DNS SERVER ---
class DNSServer:
    def __init__(self, ip_address="192.168.4.1"):
        self.ip = ip_address
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.sock.bind(('', 53))
        self.ip_bytes = bytes([int(x) for x in self.ip.split('.')])

    def handle_request(self):
        try:
            data, addr = self.sock.recvfrom(512)
            if len(data) < 12: return
            transaction_id = data[:2]
            response_header = transaction_id + b'\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00'
            query_idx = 12
            while data[query_idx] != 0:
                query_idx += data[query_idx] + 1
            query_block = data[12:query_idx + 5]
            answer_record = b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04' + self.ip_bytes
            self.sock.sendto(response_header + query_block + answer_record, addr)
        except OSError:
            pass

    def close(self):
        try: self.sock.close()
        except: pass

# --- PORTAL & CONFIG UTILITIES ---
def load_config():
    global config_data
    try:
        with open(CONFIG_FILE, "r") as f: config_data = json.load(f)
    except Exception:
        config_data = {"DEVICE_ID": "", "WIFI_SSID": "", "WIFI_PASS": "", "MQTT_BROKER": "", "MQTT_PORT": 1883, "MQTT_CLIENT_ID": "esp32_nfc_reader", "MQTT_TOPIC": "nfc", "WEBHOOK_URL": "", "WEBHOOK_HEADERS": "", "NEOPIXEL_PIN": "35", "WEBHOOK_TIMEOUT_MS": 3000, "MQTT_TIMEOUT_MS": 3000, "MQTT_RECONNECT_DELAY_MS": 2000}

def save_config(new_config):
    try:
        with open(CONFIG_FILE, "w") as f: json.dump(new_config, f)
        return True
    except Exception as e:
        print("Error saving config:", e); return False

def default_device_id():
    """Chip-unique fallback identifier (ESP32 MAC as hex), used when DEVICE_ID is blank."""
    return "esp32-" + "".join(["{:02x}".format(b) for b in machine.unique_id()])

def get_device_id():
    """The identifier stamped into every event message so consumers can tell
    which physical device reported an event: the configured DEVICE_ID, or the
    chip-unique default when blank."""
    dev_id = str(config_data.get("DEVICE_ID", "") or "").strip().strip("/")
    return dev_id or default_device_id()

def get_html_template():
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>ESP32 NFC Node Config Portal</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f4f4f9; color: #333; }}
        .container {{ max-width: 450px; background: white; padding: 25px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); margin: 0 auto; }}
        h2 {{ text-align: center; color: #007bff; }}
        label {{ font-weight: bold; display: block; margin-top: 15px; font-size: 14px; }}
        input[type="text"], input[type="password"], input[type="number"], textarea {{ width: 100%; padding: 10px; margin-top: 5px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; font-family: Arial, sans-serif; font-size: 14px; }}
        .note {{ font-size: 12px; color: #666; font-style: italic; margin-top: 2px; }}
        input[type="submit"] {{ width: 100%; background-color: #007bff; color: white; border: none; padding: 12px; margin-top: 25px; border-radius: 4px; font-size: 16px; cursor: pointer; font-weight: bold; }}
        input[type="submit"]:hover {{ background-color: #0056b3; }}
    </style>
</head>
<body>
    <div class="container">
        <h2>NFC Provisioning Portal</h2>
        <form action="/save" method="POST">
            <label>Wi-Fi SSID:</label>
            <input type="text" name="wifi_ssid" value="{config_data.get('WIFI_SSID', '')}" required>

            <label>Wi-Fi Password:</label>
            <input type="password" name="wifi_pass" value="{config_data.get('WIFI_PASS', '')}">

            <label>Device ID:</label>
            <input type="text" name="device_id" value="{config_data.get('DEVICE_ID', '')}" placeholder="{default_device_id()}">
            <div class="note">Sent inside every event message so several devices can be told apart. Leave blank to use the chip-unique id shown as placeholder.</div>

            <label>MQTT Broker Host IP:</label>
            <input type="text" name="mqtt_broker" value="{config_data.get('MQTT_BROKER', '')}">
            <div class="note">Leave blank to use Webhook Fallback instead.</div>

            <label>MQTT Port:</label>
            <input type="number" name="mqtt_port" value="{config_data.get('MQTT_PORT', 1883)}">

            <label>MQTT Client ID:</label>
            <input type="text" name="mqtt_client_id" value="{config_data.get('MQTT_CLIENT_ID', 'esp32_nfc_reader')}">

            <label>MQTT Topic Base:</label>
            <input type="text" name="mqtt_topic" value="{config_data.get('MQTT_TOPIC', 'nfc')}" placeholder="nfc">
            <div class="note">Prefix for all topics: <code>BASE/tag/present</code>, <code>BASE/tag/retired</code>, <code>BASE/tag/alert</code>, <code>BASE/reader/status</code>. Leave blank for <code>nfc</code>. Supports <code>{{device}}</code> to insert the Device ID, e.g. <code>nfc/{{device}}</code>.</div>

            <label>HTTPS Webhook URL:</label>
            <input type="text" name="webhook_url" value="{config_data.get('WEBHOOK_URL', '')}">
            <div class="note">Supports <code>{{device}}</code> to insert the Device ID, e.g. <code>https://example.com/hook/{{device}}</code>.</div>

            <label>Webhook Custom Headers (optional):</label>
            <textarea name="webhook_headers" rows="4" placeholder="Authorization: Bearer YOUR_TOKEN">{config_data.get('WEBHOOK_HEADERS', '')}</textarea>
            <div class="note">One header per line in <code>Name: value</code> form, e.g. <code>Authorization: Bearer YOUR_TOKEN</code>. Leave blank to send no extra headers.</div>

            <label>Status Neopixel Pin (GPIO):</label>
            <input type="number" name="neopixel_pin" value="{config_data.get('NEOPIXEL_PIN', '35')}" min="0" max="48" placeholder="35">
            <div class="note">Onboard WS2812/Neopixel GPIO: <b>48</b> on ESP32-S3 Super-Mini, <b>21</b> on ESP32-S3 Zero. Leave blank to use a plain LED on GPIO{STATUS_LED_PIN}.</div>

            <label>Webhook Timeout (ms):</label>
            <input type="number" name="webhook_timeout_ms" value="{config_data.get('WEBHOOK_TIMEOUT_MS', 3000)}" min="500" max="10000" step="100">

            <label>MQTT Timeout (ms):</label>
            <input type="number" name="mqtt_timeout_ms" value="{config_data.get('MQTT_TIMEOUT_MS', 3000)}" min="500" max="10000" step="100">

            <label>MQTT Reconnect Delay (ms):</label>
            <input type="number" name="mqtt_reconnect_delay_ms" value="{config_data.get('MQTT_RECONNECT_DELAY_MS', 2000)}" min="0" max="10000" step="100">

            <input type="submit" value="Save Configuration & Reboot">
        </form>
    </div>
</body>
</html>
"""

def parse_post_data(req_body):
    params = {}
    pairs = req_body.split("&")
    for pair in pairs:
        if "=" in pair:
            k, v = pair.split("=", 1)
            v = v.replace("+", " ")
            i, res = 0, []
            while i < len(v):
                if v[i] == "%" and i + 2 < len(v):
                    try:
                        res.append(chr(int(v[i+1:i+3], 16)))
                        i += 3
                    except: res.append(v[i]); i += 1
                else: res.append(v[i]); i += 1
            params[k] = "".join(res)
    return params

def parse_webhook_headers(raw):
    """Parses optional 'Name: value' lines (from the portal textarea) into a header dict."""
    headers = {}
    if not raw:
        return headers
    for line in raw.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue  # Skip blank lines and malformed entries
        name, value = line.split(":", 1)
        name = name.strip()
        if name:
            headers[name] = value.strip()
    return headers

def run_configuration_portal():
    """Hosts Access Point with an asynchronous DNS interceptor and blinking portal LED status."""
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.ifconfig(('192.168.4.1', '255.255.255.0', '192.168.4.1', '192.168.4.1'))
    ap.config(essid="ESP32_NFC_SETUP", authmode=network.AUTH_OPEN)

    print("\n[PORTAL MODE] Access Point Active: 'ESP32_NFC_SETUP'")
    led_state["mode"] = "portal" # Engage the slow-blinking LED cycle

    dns_server = DNSServer("192.168.4.1")
    web_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    web_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    web_sock.bind(('', 80))
    web_sock.listen(2)
    web_sock.setblocking(False)

    while True:
        dns_server.handle_request()
        update_led() # Smoothly updates the blinking pattern in the background

        try:
            conn, addr = web_sock.accept()
            time.sleep(0.05)
            request = conn.recv(1024).decode('utf-8')

            if "POST /save" in request:
                parts = request.split("\r\n\r\n", 1)
                body = parts[1] if len(parts) > 1 else ""
                form_data = parse_post_data(body)

                updated_config = {
                    "DEVICE_ID": form_data.get("device_id", "").strip().strip("/"),
                    "WIFI_SSID": form_data.get("wifi_ssid", ""),
                    "WIFI_PASS": form_data.get("wifi_pass", ""),
                    "MQTT_BROKER": form_data.get("mqtt_broker", ""),
                    "MQTT_PORT": int(form_data.get("mqtt_port", 1883)),
                    "MQTT_CLIENT_ID": form_data.get("mqtt_client_id", "esp32_nfc_reader"),
                    "MQTT_TOPIC": form_data.get("mqtt_topic", "nfc").strip("/") or "nfc",
                    "WEBHOOK_URL": form_data.get("webhook_url", ""),
                    "WEBHOOK_HEADERS": form_data.get("webhook_headers", ""),
                    "NEOPIXEL_PIN": form_data.get("neopixel_pin", ""),
                    "WEBHOOK_TIMEOUT_MS": int(form_data.get("webhook_timeout_ms", 3000) or 3000),
                    "MQTT_TIMEOUT_MS": int(form_data.get("mqtt_timeout_ms", 3000) or 3000),
                    "MQTT_RECONNECT_DELAY_MS": int(form_data.get("mqtt_reconnect_delay_ms", 2000) or 2000)
                }

                save_config(updated_config)

                response = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<html><body><h2>Configuration Saved! Device is rebooting now...</h2></body></html>"
                conn.send(response)
                conn.close()

                dns_server.close()
                web_sock.close()
                time.sleep(1.5)
                machine.reset()

            elif "GET /generate_204" in request or "GET /hotspot-detect" in request or "GET /" in request:
                response = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + get_html_template()
                conn.send(response)
                conn.close()
            else:
                response = "HTTP/1.1 302 Found\r\nLocation: http://192.168.4.1/\r\n\r\n"
                conn.send(response)
                conn.close()
        except OSError:
            pass
        time.sleep(0.01)

def apply_device_placeholder(url_or_topic):
    """Expands the {device} placeholder to the Device ID, so users can embed the
    identifier in the MQTT topic or webhook URL if their consumer prefers that.
    The message payload always carries device_id regardless."""
    return str(url_or_topic).replace("{device}", get_device_id())

def mqtt_topic(suffix):
    """Builds a full MQTT topic from the configured base (MQTT_TOPIC) and a suffix."""
    base = str(config_data.get("MQTT_TOPIC", "nfc") or "nfc").strip("/")
    return apply_device_placeholder(base + "/" + suffix).encode()

def build_event_payload(event_type, uid, message=None):
    """The message body sent on both transports. device_id is always present so
    multi-device deployments can attribute events directly from the message data,
    independent of topic/URL structure or external service behavior."""
    return {
        "device_id": get_device_id(),
        "event": event_type,
        "uid": uid,
        "timestamp": time.time(),
        "message": message if message else f"Tag {event_type}",
    }

def dispatch_event(use_mqtt, client, event_type, uid, message=None):
    payload = build_event_payload(event_type, uid, message)
    if use_mqtt and client:
        try:
            client.publish(mqtt_topic("tag/" + event_type), json.dumps(payload).encode())
        except Exception as e:
            print("MQTT dispatch failed:", e)
    elif config_data.get("WEBHOOK_URL"):
        headers = {"Content-Type": "application/json"}
        headers.update(parse_webhook_headers(config_data.get("WEBHOOK_HEADERS", "")))
        timeout_ms = int(config_data.get("WEBHOOK_TIMEOUT_MS", 3000) or 3000)
        url = apply_device_placeholder(config_data.get("WEBHOOK_URL", ""))
        try:
            res = urequests.post(url, data=json.dumps(payload), headers=headers, timeout=timeout_ms / 1000.0)
            res.close()
        except Exception as e:
            print("Webhook dispatch failed:", e)

def main():
    load_config()
    init_status_led()
    portal_button = Pin(RESET_PORTAL_PIN, Pin.IN, Pin.PULL_UP)
    time.sleep(0.1)
    if not config_data.get("WIFI_SSID") or portal_button.value() == 0:
        run_configuration_portal()
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    print(f"Connecting to Wi-Fi Network: {config_data['WIFI_SSID']}...")
    wlan.connect(config_data["WIFI_SSID"], config_data["WIFI_PASS"])
    # Fast blink during standard Wi-Fi station connection phase
    led_state["mode"] = "portal"
    conn_timeout = 20
    while not wlan.isconnected() and conn_timeout > 0:
        update_led()
        time.sleep(0.5)
        conn_timeout -= 1
    if not wlan.isconnected():
        print("Failed to connect to Wi-Fi. Entering Configuration Portal...")
        run_configuration_portal()
    print("Wi-Fi Connected successfully! IP Node Address:", wlan.ifconfig())
    led_state["mode"] = "idle" # Transition seamlessly into the low-frequency background heartbeat blink
    use_mqtt = bool(config_data.get("MQTT_BROKER"))
    mqtt_client = None
    if use_mqtt:
        from umqtt.simple import MQTTClient
        mqtt_client = MQTTClient(config_data["MQTT_CLIENT_ID"], config_data["MQTT_BROKER"], port=int(config_data["MQTT_PORT"]))
        status_payload = json.dumps({"device_id": get_device_id(), "status": "offline"}).encode()
        mqtt_client.set_last_will(mqtt_topic("reader/status"), status_payload, retain=True)
        try:
            mqtt_client.connect()
            mqtt_client.publish(mqtt_topic("reader/status"), json.dumps({"device_id": get_device_id(), "status": "online"}).encode(), retain=True)
            print("MQTT Pipeline Established.")
        except Exception as e:
            print("MQTT Broker unreachable, falling back to Webhooks:", e)
            use_mqtt = False
    reader = ST25R3916(i2c)
    print("M5Stack Unit NFC (ST25R3916) Scanner Online. Ready for passive tags...")

    def format_uid(uid_bytes):
        return "".join(["{:02X}".format(x) for x in uid_bytes])

    def handle_tag_miss():
        """Called whenever a poll fails to read the tag; drives the debounced retire."""
        if active_session["tag_present"]:
            active_session["consecutive_misses"] += 1
            if active_session["consecutive_misses"] >= DEBOUNCE_THRESHOLD:
                retired_uid = active_session["last_uid"]
                active_session["tag_present"] = False
                active_session["last_uid"] = None
                active_session["consecutive_misses"] = 0
                active_session["timeout_triggered"] = False
                print(f" TAG RETIRED: {retired_uid}")
                dispatch_event(use_mqtt, mqtt_client, "retired", retired_uid)
                trigger_retire_blink() # Yellow confirmation blink, then fixed orange

    # Variables to handle non-blocking loop delays for reading/polling cards
    last_poll_time = 0
    while True:
        update_led() # Keeps background blinking consistent on every single loop loop pass
        if portal_button.value() == 0:
            print("Manual reset button detected. Booting Configuration Portal...")
            run_configuration_portal()
        # Handle non-blocking timing loop intervals for the NFC reader field checks
        now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, last_poll_time) >= int(POLL_INTERVAL * 1000):
            last_poll_time = now_ms
            (status, tag_type) = reader.request(reader.REQIDL)
            if status != reader.OK:
                # Tag is out of the field: register a miss for the debounced retire
                handle_tag_miss()
            else:
                (status, uid) = reader.anticoll()
                if status != reader.OK:
                    # Field detected but UID could not be read: count as a miss too
                    handle_tag_miss()
                else:
                    current_uid = format_uid(uid)
                    active_session["consecutive_misses"] = 0
                    if not active_session["tag_present"]:
                        active_session["tag_present"] = True
                        active_session["last_uid"] = current_uid
                        active_session["inserted_at"] = time.time()
                        active_session["timeout_triggered"] = False
                        print(f" TAG INSERTED: {current_uid}")
                        trigger_led_burst()
                        dispatch_event(use_mqtt, mqtt_client, "present", current_uid)
                    elif active_session["last_uid"] != current_uid:
                        old_uid = active_session["last_uid"]
                        print(f" TAG RETIRED: {old_uid}")
                        dispatch_event(use_mqtt, mqtt_client, "retired", old_uid)
                        trigger_retire_blink()
                        active_session["tag_present"] = True
                        active_session["last_uid"] = current_uid
                        active_session["inserted_at"] = time.time()
                        active_session["timeout_triggered"] = False
                        print(f" TAG INSERTED: {current_uid}")
                        trigger_led_burst()
                        dispatch_event(use_mqtt, mqtt_client, "present", current_uid)
                    else:
                        time_held = time.time() - active_session["inserted_at"]
                        if time_held > MAX_PRESENT_TIME and not active_session["timeout_triggered"]:
                            active_session["timeout_triggered"] = True
                            alert_msg = f"Warning: Tag {current_uid} left on reader for {time_held}s"
                            print(f" {alert_msg}")
                            dispatch_event(use_mqtt, mqtt_client, "alert", current_uid, alert_msg)
        if use_mqtt and mqtt_client:
            try: mqtt_client.ping()
            except Exception:
                try:
                    reconnect_delay = int(config_data.get("MQTT_RECONNECT_DELAY_MS", 2000) or 0)
                    if reconnect_delay > 0:
                        time.sleep_ms(min(reconnect_delay, 2000))
                    mqtt_client.connect()
                except Exception:
                    pass
        # Yield execution minimally to keep the processing engine efficient
        time.sleep_ms(5)

if __name__ == "__main__":
    main()

