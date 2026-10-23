#!/usr/bin/env python3
"""Minimal webhook receiver for testing the ESP32 NFC reader's webhook mode.

This runs on your computer (CPython 3, standard library only) and is not
deployed to the board. It accepts the POST requests the reader sends, prints
each event as it arrives, and refuses requests whose auth header is missing or
wrong, so you can exercise both the "Webhook URL" and the "Webhook Headers"
settings of the configuration portal.

Start it:

    python3 esp32_nfc_detector/tools/webhook_example.py --token secret123

It prints the two values to paste into the portal, for example:

    Webhook URL:     http://192.168.0.113:8080/webhook
    Webhook headers: Authorization: Bearer secret123

Tap a tag on the reader and watch the "present", "retired" and "alert" events
arrive here. A request with no token, or the wrong one, is rejected with 401
and the reason is printed, so you can confirm the headers are really being sent.

Options (each also settable through an environment variable):

    --token    shared secret                      WEBHOOK_TOKEN
    --port     listening port, default 8080       WEBHOOK_PORT
    --host     bind address, default 0.0.0.0      WEBHOOK_HOST
    --header   header name, default Authorization WEBHOOK_HEADER
    --scheme   expected prefix, default Bearer    WEBHOOK_SCHEME

Use --scheme "" if you want to send the bare token in the header.
"""

import argparse
import hmac
import json
import os
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EXIT_OK = 0

events_seen = []
event_count = 0


def local_ip():
    """Best-effort LAN address of this machine, for the URL hint."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packet is sent; this only asks the OS which interface it would use.
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def stamp():
    return time.strftime("%H:%M:%S")


class WebhookHandler(BaseHTTPRequestHandler):
    # Set by main() before the server starts.
    expected_header = "Authorization"
    expected_value = ""
    quiet_paths = ("/favicon.ico",)

    def log_message(self, fmt, *args):
        """Silence the default per-request logging; we print our own."""
        pass

    def _reply(self, code, body, content_type="application/json"):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _headers_as_text(self):
        lines = []
        for name, value in self.headers.items():
            lines.append("    %s: %s" % (name, value))
        return "\n".join(lines) if lines else "    (none)"

    def do_GET(self):
        if self.path in self.quiet_paths:
            self._reply(404, '{"ok": false, "error": "not found"}')
            return
        body = {
            "ok": True,
            "service": "esp32-nfc webhook example",
            "events_received": event_count,
            "how_to_send": "POST JSON with header '%s: %s'"
                           % (self.expected_header, self.expected_value),
        }
        self._reply(200, json.dumps(body, indent=2))

    def do_POST(self):
        global event_count

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        sender = self.client_address[0]
        arrived = self.headers.get(self.expected_header)

        print("[%s] POST %s from %s" % (stamp(), self.path, sender))
        print("  headers:")
        print(self._headers_as_text())

        # Auth is checked before the body is trusted, and with a constant-time
        # comparison so the token cannot be probed byte by byte.
        if arrived is None:
            reason = ("missing the %r header - fill in the portal's "
                      "Webhook headers field" % self.expected_header)
            print("  REJECTED: %s" % reason)
            self._reply(401, json.dumps({"ok": False, "error": reason}))
            print()
            sys.stdout.flush()
            return
        if not hmac.compare_digest(arrived.strip(), self.expected_value):
            reason = ("wrong %r header - got %r, expected %r"
                      % (self.expected_header, arrived.strip(),
                         self.expected_value))
            print("  REJECTED: %s" % reason)
            self._reply(401, json.dumps({"ok": False, "error": reason}))
            print()
            sys.stdout.flush()
            return

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            reason = "body is not valid JSON: %s" % exc
            print("  REJECTED: %s" % reason)
            print("  raw body: %r" % raw[:200])
            self._reply(400, json.dumps({"ok": False, "error": reason}))
            print()
            sys.stdout.flush()
            return

        if not isinstance(payload, dict):
            reason = "body is JSON but not an object"
            print("  REJECTED: %s" % reason)
            self._reply(400, json.dumps({"ok": False, "error": reason}))
            print()
            sys.stdout.flush()
            return

        event_count += 1
        events_seen.append(payload)
        when = payload.get("timestamp")
        when_txt = "?"
        if isinstance(when, (int, float)):
            when_txt = "%s (%s)" % (when, time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(when)))

        print("  event:   %s" % payload.get("event"))
        print("  device:  %s" % payload.get("device_id"))
        print("  uid:     %s" % payload.get("uid"))
        print("  message: %s" % payload.get("message"))
        print("  time:    %s" % when_txt)
        print("  -> 200 OK  (event #%d)" % event_count)
        print()

        self._reply(200, json.dumps({"ok": True, "received": payload}))
        sys.stdout.flush()

    def do_PUT(self):
        self._reply(405, '{"ok": false, "error": "use POST"}')

    def do_HEAD(self):
        self._reply(200, b"")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Webhook receiver for the ESP32 NFC reader.")
    parser.add_argument("--token", default=os.environ.get("WEBHOOK_TOKEN",
                                                          "secret123"),
                        help="shared secret the reader must send "
                             "(default: secret123)")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("WEBHOOK_PORT", "8080")),
                        help="port to listen on (default: 8080)")
    parser.add_argument("--host", default=os.environ.get("WEBHOOK_HOST",
                                                         "0.0.0.0"),
                        help="address to bind (default: 0.0.0.0)")
    parser.add_argument("--header", default=os.environ.get("WEBHOOK_HEADER",
                                                          "Authorization"),
                        help="header to check (default: Authorization)")
    parser.add_argument("--scheme", default=os.environ.get("WEBHOOK_SCHEME",
                                                           "Bearer"),
                        help='expected prefix, e.g. "Bearer"; use "" for a '
                             "bare token (default: Bearer)")
    args = parser.parse_args(argv)

    if not args.token:
        parser.error("--token must not be empty")

    scheme = args.scheme.strip()
    expected = ("%s %s" % (scheme, args.token)) if scheme else args.token

    WebhookHandler.expected_header = args.header
    WebhookHandler.expected_value = expected

    try:
        server = ThreadingHTTPServer((args.host, args.port), WebhookHandler)
    except OSError as exc:
        print("Cannot listen on %s:%d - %s" % (args.host, args.port, exc))
        print("Is another copy already running, or is the port taken?")
        return 1

    host_for_url = local_ip() if args.host in ("0.0.0.0", "") else args.host
    url = "http://%s:%d/webhook" % (host_for_url, args.port)

    print("ESP32 NFC webhook example listening on %s:%d"
          % (args.host, args.port))
    print()
    print("Paste these into the reader's configuration portal:")
    print("  Webhook URL:     %s" % url)
    print("  Webhook headers: %s: %s" % (args.header, expected))
    print()
    print("Also set the device's Wi-Fi, and leave Webhook URL as the only")
    print("output (MQTT is used instead when an MQTT broker is configured).")
    print("The URL accepts any path, so {device} in the URL works too.")
    print()
    print("Waiting for events - tap a tag on the reader. Ctrl+C to stop.")
    print()
    sys.stdout.flush()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("Stopped. Received %d event(s)." % event_count)
    finally:
        server.server_close()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
