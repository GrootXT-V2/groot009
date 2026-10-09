"""Groot on your phone.

`python -m groot --phone` starts a small web server on this computer. Open the
link it prints (or scan the QR code) on your phone to get the same buddy, with
the same brain, voice and memory.

The buddy's drawings are recorded here as simple drawing commands and replayed
by the phone's browser, so the phone shows exactly the same character.
"""

import asyncio
import gzip
import json
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .buddy import Area, Buddy, Canvas, rgba

APP_PAGE = Path(__file__).with_name("phone_app.html")
PORT = 8765


# ------------------------------------------------------------------ recording the buddy's drawings

def css_color(color):
    if color is None:
        return None
    if isinstance(color, tuple):
        r, g, b, a = rgba(color)
        return f"rgba({round(r * 255)},{round(g * 255)},{round(b * 255)},{a:.2f})"
    return color


def _n(value):
    return round(float(value), 1)


class RecordingCanvas(Canvas):
    """Records drawing commands so a web browser can replay them."""

    def __init__(self):
        self.ops = []

    @staticmethod
    def _path(shape):
        parts = []
        for cmd in shape.cmds:
            parts.append(cmd[0] + (" " + " ".join(str(_n(v)) for v in cmd[1:]) if len(cmd) > 1 else ""))
        return " ".join(parts)

    def save(self):
        self.ops.append(["S"])

    def restore(self):
        self.ops.append(["R"])

    def translate(self, dx, dy):
        self.ops.append(["T", _n(dx), _n(dy)])

    def rotate(self, degrees):
        self.ops.append(["O", _n(degrees)])

    def scale(self, factor):
        self.ops.append(["K", round(factor, 3), round(factor, 3)])

    def scale_xy(self, sx, sy):
        self.ops.append(["K", round(sx, 3), round(sy, 3)])

    def fill_stroke(self, shape, fill=None, outline=None, width=0):
        self.ops.append(["P", self._path(shape), css_color(fill), css_color(outline), _n(width)])

    def gradient(self, shape, start, end, stops, outline=None, width=0):
        # browsers draw gradients themselves, so record one command instead of many bands
        self.ops.append(["G", self._path(shape), _n(start[0]), _n(start[1]), _n(end[0]), _n(end[1]),
                         [[p, css_color(c)] for p, c in stops], css_color(outline), _n(width)])

    def clip(self, shape):
        self.ops.append(["C", self._path(shape)])

    def fill_rect(self, x, y, w, h, color):
        self.ops.append(["F", _n(x), _n(y), _n(w), _n(h), css_color(color)])

    def text(self, x, y, text, size, color, bold=False):
        self.ops.append(["X", text, _n(x), _n(y), size, css_color(color), bool(bold)])

    def measure(self, text, size, max_width):
        return min(len(text) * size * 0.55, max_width), size * 1.4

    def text_box(self, x, y, w, h, text, size, color):
        pass  # the phone shows speech in its own chat bubbles


def _frames(buddy, count, setup, every=1):
    """Run the buddy for `count` frames after `setup`, recording each drawing."""
    base = time.monotonic()
    setup(buddy, base)
    frames = []
    for i in range(count * every):
        buddy.tick(base + i * Buddy.FRAME)
        if i % every == 0:
            canvas = RecordingCanvas()
            buddy.draw(canvas, base + i * Buddy.FRAME)
            frames.append(canvas.ops)
    return frames


def build_frames(style="fox"):
    """All the phone animations as lists of recorded frames."""
    def make():
        buddy = Buddy(size=1.0, style=style, area=Area(0, 0, 4000, 2000))
        buddy.caption = ""
        buddy.x = 2000
        buddy.next_blink = float("inf")
        return buddy

    def pose(state, action="look", blink_at=None):
        def setup(buddy, base):
            buddy.state = state
            buddy.action = {"name": action, "start": base, "until": base + 1e6, "target": 0.0}
            buddy.next_blink = base + blink_at if blink_at is not None else float("inf")
        return setup

    def activity(name):
        def setup(buddy, base):
            buddy.state = "idle"
            buddy.activity = {"name": name, "start": base, "until": base + 1e6, "kick_until": 0.0,
                              "kick_dir": 1, "jump_start": -10.0, "target": None, "retarget": 0.0}
        return setup

    walk_frames = int(round(2 * 3.14159 / (1.6 * 0.12))) + 1  # one full step cycle
    anims = {
        "idle": _frames(make(), 60, pose("idle", "look", blink_at=1.5), every=2),
        "sleep": _frames(make(), 30, pose("idle", "rest"), every=2),
        "walk": _frames(make(), walk_frames, pose("idle", "walk")),
        "listening": _frames(make(), 30, pose("listening", "rest", blink_at=0.6), every=2),
        "thinking": _frames(make(), 40, pose("thinking", "rest"), every=2),
        "speaking": _frames(make(), 24, pose("speaking", "rest"), every=2),
        "dance": _frames(make(), 40, activity("dance"), every=2),
        "jump": _frames(make(), 21, activity("jump")),
        "wave": _frames(make(), 30, activity("wave"), every=2),
    }
    sample = make()
    return {"W": sample.W, "H": sample.H, "fps": 30, "every": {"walk": 1, "jump": 1}, "anims": anims}


# ------------------------------------------------------------------ talking to the brain

class PhoneActions:
    """The phone version of 'perform_action': the phone's fox acts it out."""

    def __init__(self):
        self.requested = None

    def perform_action(self, activity: str) -> str:
        self.requested = activity
        if activity in ("football", "butterfly"):
            return "That game is on the computer screen; on the phone I'll do a happy dance instead."
        return f"Doing it on the phone screen: {activity}."


def synthesize(text, voice, rate, pitch):
    """Natural voice as MP3 bytes (None if it isn't available, e.g. offline)."""
    try:
        import edge_tts
    except ImportError:
        return None

    async def run():
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        return bytes(audio)

    try:
        return asyncio.run(run()) or None
    except Exception as exc:
        print(f"[phone voice unavailable: {exc}]")
        return None


class PhoneBrain:
    """Handles one message from the phone: stop words, yes/no confirmations, or the AI."""

    def __init__(self, brain, skills, actions, voice=None):
        self.brain = brain
        self.skills = skills
        self.actions = actions
        self.voice = voice  # (voice, rate, pitch) for the natural voice, or None
        self.lock = threading.Lock()
        self.audio = {}  # id -> mp3 bytes

    def chat(self, text: str) -> dict:
        from .gui import is_stop_command
        from .voice import clean_for_speech

        text = text.strip()[:1000]
        if not text:
            return {"reply": "", "end": False}
        with self.lock:
            end = False
            self.actions.requested = None
            if is_stop_command(text):
                reply, end = "Okay! Tap me when you need me.", True
                self.skills.pending = None
            else:
                reply = self.skills.handle_confirmation(text)
                if reply is None:
                    try:
                        reply = self.brain.reply(text)
                    except Exception as exc:
                        print(f"[error: {exc}]")
                        reply = "Sorry, something went wrong. Please try again."
            result = {"reply": reply, "end": end, "activity": self.actions.requested}
            spoken = clean_for_speech(reply)
            if spoken and self.voice:
                audio = synthesize(spoken, *self.voice)
                if audio:
                    key = secrets.token_hex(8)
                    self.audio[key] = audio
                    while len(self.audio) > 20:
                        self.audio.pop(next(iter(self.audio)))
                    result["audio"] = key
            result["say"] = spoken
            return result


# ------------------------------------------------------------------ the web server

def make_handler(phone_brain, frames_json_gz, key):
    page = APP_PAGE.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # keep Terminal quiet

        def _send(self, status, body=b"", content_type="application/json", extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self, query):
            given = self.headers.get("X-Groot-Key") or query.get("k", [""])[0]
            return secrets.compare_digest(given, key)

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path in ("/", "/index.html"):
                return self._send(200, page, "text/html; charset=utf-8")
            if url.path == "/manifest.webmanifest":
                manifest = {"name": "Groot", "short_name": "Groot", "display": "standalone",
                            "background_color": "#bfe3f2", "theme_color": "#bfe3f2",
                            "start_url": "/", "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]}
                return self._send(200, json.dumps(manifest).encode(), "application/manifest+json")
            if url.path in ("/icon.svg", "/favicon.ico"):
                icon = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" '
                        'rx="22" fill="#bfe3f2"/><text x="50" y="68" font-size="60" text-anchor="middle">🦊</text></svg>')
                return self._send(200, icon.encode(), "image/svg+xml")
            if not self._authorized(query):
                return self._send(401, b'{"error": "wrong or missing key"}')
            if url.path == "/api/frames":
                return self._send(200, frames_json_gz, "application/json", {"Content-Encoding": "gzip"})
            if url.path.startswith("/api/audio/"):
                audio = phone_brain.audio.get(url.path.rsplit("/", 1)[-1])
                if audio is None:
                    return self._send(404, b"{}")
                return self._send(200, audio, "audio/mpeg")
            return self._send(404, b"{}")

        def do_POST(self):
            url = urlparse(self.path)
            if not self._authorized(parse_qs(url.query)):
                return self._send(401, b'{"error": "wrong or missing key"}')
            if url.path != "/api/chat":
                return self._send(404, b"{}")
            length = min(int(self.headers.get("Content-Length") or 0), 20000)
            try:
                text = json.loads(self.rfile.read(length) or b"{}").get("text", "")
            except json.JSONDecodeError:
                return self._send(400, b'{"error": "bad request"}')
            result = phone_brain.chat(str(text))
            return self._send(200, json.dumps(result).encode())

    return Handler


def phone_key(data_dir) -> str:
    """A secret key kept on this computer; the phone link includes it."""
    path = Path(data_dir) / "phone_key"
    try:
        key = path.read_text().strip()
        if len(key) >= 20:
            return key
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(18)
    path.write_text(key)
    return key


def lan_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packets are sent; this just picks the Wi-Fi address
            return s.getsockname()[0]
    except OSError:
        return "localhost"


def print_link(title, url):
    print(f"\n{title}\n  {url}")
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except ImportError:
        pass


def start_tunnel(port):
    """If cloudflared is installed, make a free secure https link that works anywhere."""
    if not shutil.which("cloudflared"):
        return None
    process = subprocess.Popen(["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 30
    for line in process.stderr:
        if "trycloudflare.com" in line:
            for word in line.split():
                if word.startswith("https://") and "trycloudflare.com" in word:
                    threading.Thread(target=lambda: [None for _ in process.stderr], daemon=True).start()
                    return word.strip("|")
        if time.time() > deadline:
            break
    return None


def run_phone(config, brain_kind: str) -> None:
    from .__main__ import make_brain
    from .gui import BUDDY_TOOLS
    from .skills import Skills

    skills = Skills(config.data_dir, default_city=config.city, announce=print, slack_token=config.slack_token)
    actions = PhoneActions()
    skills.integrations.append((actions, BUDDY_TOOLS))
    brain = make_brain(config, brain_kind, skills)
    voice = (config.edge_voice, config.edge_rate, config.edge_pitch) if config.tts == "edge" else None
    phone_brain = PhoneBrain(brain, skills, actions, voice)

    print("Preparing the animations...")
    frames = gzip.compress(json.dumps(build_frames(config.robot_style), separators=(",", ":")).encode())
    key = phone_key(config.data_dir)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(phone_brain, frames, key))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print(f"\n{config.name} for your phone is running! Keep this window open.")
    print_link("On the same Wi-Fi, open this on your phone (typing works; for talking use the https link):",
               f"http://{lan_address()}:{PORT}/?k={key}")
    tunnel = start_tunnel(PORT)
    if tunnel:
        print_link("Secure link that works anywhere, with the microphone (scan this one):", f"{tunnel}/?k={key}")
    else:
        print("\nFor talking with the microphone (and using it away from home), install the free tunnel:\n"
              "  brew install cloudflared\nthen start this again: it will print a secure https link.")
    print("\nKeep the link private - it includes your secret key. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()
        sys.exit(0)
