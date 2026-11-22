#!/usr/bin/env python3
"""On-demand RainViewer radar and OSM viewport tiles; Python standard library only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import storage
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import struct
import sys
import tempfile
import threading
import time
import zlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from image_validation import PNG as PNG, png_size
import wind_style

STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "pixel-weather"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "pixel-weather/radar"
MANIFEST_URL = "https://api.rainviewer.com/public/weather-maps.json"
RADAR_HOST = "https://tilecache.rainviewer.com"
OSM_HOST = "https://tile.openstreetmap.org"
DWD_WMS = "https://maps.dwd.de/geoserver/dwd/wms"
DWD_PAST_LAYER = "Radar_wn-analysis_1x1km_ger"
DWD_FUTURE_LAYER = "Radar_wn-product_1x1km_ger"
# ICON 2.5 km wind barbs for the same viewport.
DWD_WIND_LAYER = "Icon_reg025_fd_sl_UV10M"
WIND_FRAMES = 12
WIND_TTL = 1800
# The DWD composite covers Germany and the near border area.
DWD_WEST, DWD_SOUTH, DWD_EAST, DWD_NORTH = 5.5, 47.0, 15.6, 55.2
MAP_MIN_ZOOM = 3
MAP_MAX_ZOOM = 10
RAINVIEWER_MAX_ZOOM = 7
DWD_STEP = 300
DWD_LAG = 300
DWD_PAST_FRAMES = 25
# The DWD nowcast layer publishes five-minute steps up to two hours ahead.
DWD_FUTURE_FRAMES = 24
DWD_FUTURE_TTL = 900
DWD_RETRY = 300
# The first load paints the basemap and the latest observation. Older
# observations and the nowcast warm up in the background after the response.
# Each frame is a separate WMS render, so warming runs several requests at
# once; a close zoom would otherwise take minutes to fill the timeline.
DWD_PREFETCH_SECONDS = 180
DWD_PREFETCH_WORKERS = 6
# Ask for twice the logical viewport so the raster stays sharp on HiDPI screens.
DWD_WIDTH, DWD_HEIGHT = 864, 480
# DWD draws wind barbs at a fixed pixel size. Request them at the displayed
# size, so they keep their full stroke instead of shrinking to half a pixel.
WIND_WIDTH, WIND_HEIGHT = 432, 240
SOURCES = ("auto", "rainviewer", "dwd")
LAYERS = ("rain", "wind")
ALLOWED_HOSTS = {"api.rainviewer.com", "tilecache.rainviewer.com", "tile.openstreetmap.org", "maps.dwd.de"}
USER_AGENT = "OWEE/1.3 (community desktop weather)"
MERCATOR_MAX_LATITUDE = 85.05112878
JSON_LIMIT = 65_536
IMAGE_LIMIT = 1_000_000
MAX_CACHE_BYTES = 96 * 1024 * 1024
OSM_CACHE_BYTES = 32 * 1024 * 1024
RATE_LOCK = threading.Lock()
REQUEST_SECONDS = 40
# The first paint waits only for the basemap and the newest observation. A slow
# DWD render must not hold the whole map, so the foreground budget stays short;
# the background worker fills the rest of the timeline.
FIRST_PAINT_SECONDS = 10
# One cold DWD load now requests a two-hour timeline in five-minute steps:
# about 50 frames plus the basemap. A layer switch inside the same minute adds
# more, so the guard sits well above a full timeline. It still stops a loop
# that would hammer the providers.
REQUESTS_PER_MINUTE = 180
_deadline = None


class RateLimited(OSError):
    """The local request guard refused a provider call."""


@contextmanager
def request_budget(seconds=REQUEST_SECONDS):
    """Share one monotonic budget across metadata, imagery and basemap workers."""
    global _deadline
    previous = _deadline
    _deadline = min(previous, time.monotonic() + seconds) if previous is not None else time.monotonic() + seconds
    try:
        yield
    finally:
        _deadline = previous


def remaining_timeout(idle):
    remaining = REQUEST_SECONDS if _deadline is None else _deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Map request timed out")
    return min(idle, remaining)


def read_response(response, limit):
    """Read available chunks rather than allowing a slow drip to reset the budget."""
    output = bytearray()
    while len(output) <= limit:
        timeout = remaining_timeout(8)
        socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if socket is not None:
            socket.settimeout(timeout)
        block = getattr(response, "read1", response.read)(min(65_536, limit + 1 - len(output)))
        if not block:
            break
        output.extend(block)
    remaining_timeout(8)
    if len(output) > limit:
        raise ValueError("Map response too large")
    return bytes(output)


@contextmanager
def file_lock(file):
    while True:
        remaining_timeout(8)
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            time.sleep(min(0.01, remaining_timeout(8)))
    try:
        yield
    finally:
        fcntl.flock(file, fcntl.LOCK_UN)


def bounded_cli(callback, fallback):
    """The CLI also bounds stalled DNS and non-interruptible worker shutdown."""
    def expired(signum, frame):
        output = fallback()
        output.update(stale=True, error="Map request timed out. Please try again.")
        print(json.dumps(output, ensure_ascii=False, allow_nan=False), flush=True)
        os._exit(124)
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, REQUEST_SECONDS)
    try:
        return callback()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def read_json(path, fallback):
    if path.name.endswith("settings.json"): return storage.read_json(path, fallback)
    try:
        if path.stat().st_size > JSON_LIMIT:
            return fallback
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def save_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".radar-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save_json(path, value):
    if path.name.endswith("settings.json"): return storage.save_json(path, value)
    save_bytes(path, json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def settings():
    raw = read_json(STATE / "radar-settings.json", {})
    if not isinstance(raw, dict):
        raw = {}
    zoom = raw.get("zoom", 6)
    source = raw.get("source")
    layer = raw.get("layer")
    return {"enabled": raw.get("enabled") is True,
            "zoom": zoom if type(zoom) is int and MAP_MIN_ZOOM <= zoom <= MAP_MAX_ZOOM else 6,
            "source": source if source in SOURCES else "auto",
            "layer": layer if layer in LAYERS else "rain"}


def configure(value):
    with storage.lock(STATE / ".radar-settings.lock"):
        return _configure(value)

def _configure(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid radar setting")
    current = settings()
    if "enabled" in value:
        if type(value["enabled"]) is not bool:
            raise ValueError("Invalid radar activation")
        current["enabled"] = value["enabled"]
    if "zoom" in value:
        if type(value["zoom"]) is not int or not MAP_MIN_ZOOM <= value["zoom"] <= MAP_MAX_ZOOM:
            raise ValueError("Invalid radar zoom")
        current["zoom"] = value["zoom"]
    if "source" in value:
        if value["source"] not in SOURCES:
            raise ValueError("Invalid radar source")
        current["source"] = value["source"]
    if "layer" in value:
        if value["layer"] not in LAYERS:
            raise ValueError("Invalid map layer")
        current["layer"] = value["layer"]
    save_json(STATE / "radar-settings.json", current)
    return current


def coordinates(city):
    if not isinstance(city, dict):
        raise ValueError("Invalid city")
    lat, lon = city.get("latitude"), city.get("longitude")
    if (type(lat) not in (int, float) or type(lon) not in (int, float)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180
            or not math.isfinite(lat) or not math.isfinite(lon)):
        raise ValueError("Invalid coordinates")
    return lat, lon


def dwd_covers(city):
    """The German composite only has data near Germany; check the centre point."""
    try:
        lat, lon = coordinates(city)
    except ValueError:
        return False
    return DWD_SOUTH <= lat <= DWD_NORTH and DWD_WEST <= lon <= DWD_EAST


def local_frame_time(stamp, city):
    """Only label frames when the chosen location provides a valid IANA zone."""
    zone = city.get("timezone") if isinstance(city, dict) else None
    if not isinstance(zone, str) or not 0 < len(zone) <= 80:
        return {}
    try:
        clock = datetime.fromtimestamp(stamp, ZoneInfo(zone))
    except (ValueError, OverflowError, OSError, ZoneInfoNotFoundError):
        return {}
    return {"local_time": clock.isoformat(timespec="minutes"), "timezone": zone}


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme != "https" or parsed.netloc not in ALLOWED_HOSTS:
            raise ValueError("Radar redirect refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@contextmanager
def rate_guard():
    # Shared across threads and short-lived processes; waits share the request budget.
    CACHE.mkdir(parents=True, exist_ok=True)
    if not RATE_LOCK.acquire(timeout=remaining_timeout(8)):
        raise TimeoutError("Map rate lock timed out")
    try:
        with (CACHE / ".request-lock").open("a") as lock, file_lock(lock):
            now = time.time()
            recent = read_json(CACHE / "requests.json", [])
            if not isinstance(recent, list):
                recent = []
            recent = [t for t in recent if type(t) in (float, int) and now - 60 < t <= now]
            if len(recent) >= REQUESTS_PER_MINUTE:
                raise RateLimited("Radar rate limit reached; try again in a minute")
            save_json(CACHE / "requests.json", recent + [now])
            yield
    finally:
        RATE_LOCK.release()


def download(url, limit, idle=5):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc not in ALLOWED_HOSTS:
        raise ValueError("Radar source refused")
    with rate_guard():
        pass
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/png, application/json"})
    with build_opener(SafeRedirect()).open(req, timeout=remaining_timeout(idle)) as response:
        return read_response(response, limit)


def valid_png(data, size=256):
    expected = size if isinstance(size, tuple) else (size, size)
    try:
        return png_size(data) == expected
    except ValueError:
        return False


def decode_rgba(data):
    """Minimal 8-bit RGBA decoder for the DWD WMS output."""
    if not data.startswith(PNG):
        return None
    offset, width, height, compressed = 8, 0, 0, bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind, body = data[offset + 4:offset + 8], data[offset + 8:offset + 8 + length]
        offset += length + 12
        if kind == b"IHDR":
            width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or colour != 6 or interlace != 0:
                return None
        elif kind == b"IDAT":
            compressed.extend(body)
        elif kind == b"IEND":
            break
    stride = width * 4 + 1
    if not width or not height or not compressed:
        return None
    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error:
        return None
    if len(raw) != stride * height:
        return None
    pixels = bytearray(width * 4 * height)
    previous = bytearray(width * 4)
    for y in range(height):
        kind = raw[y * stride]
        row = bytearray(raw[y * stride + 1:(y + 1) * stride])
        if kind == 1:
            for i in range(4, len(row)):
                row[i] = (row[i] + row[i - 4]) & 0xff
        elif kind == 2:
            for i in range(len(row)):
                row[i] = (row[i] + previous[i]) & 0xff
        elif kind == 3:
            for i in range(len(row)):
                left = row[i - 4] if i >= 4 else 0
                row[i] = (row[i] + ((left + previous[i]) >> 1)) & 0xff
        elif kind == 4:
            for i in range(len(row)):
                left = row[i - 4] if i >= 4 else 0
                above = previous[i]
                upper_left = previous[i - 4] if i >= 4 else 0
                estimate = left + above - upper_left
                distances = (abs(estimate - left), abs(estimate - above), abs(estimate - upper_left))
                predictor = (left, above, upper_left)[distances.index(min(distances))]
                row[i] = (row[i] + predictor) & 0xff
        elif kind != 0:
            return None
        pixels[y * width * 4:(y + 1) * width * 4] = row
        previous = row
    return width, height, pixels


def encode_rgba(width, height, pixels):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
    stride = width * 4
    raw = bytearray((stride + 1) * height)
    for y in range(height):
        raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)] = pixels[y * stride:(y + 1) * stride]
    return (PNG + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def strip_dwd_mask(data):
    """Remove the DWD no-data grey fill and magenta coverage border."""
    decoded = decode_rgba(data)
    if decoded is None:
        return data
    width, height, pixels = decoded
    for i in range(0, len(pixels), 4):
        red, green, blue, alpha = pixels[i], pixels[i + 1], pixels[i + 2], pixels[i + 3]
        if not alpha:
            continue
        grey = abs(red - green) <= 6 and abs(green - blue) <= 6 and 95 <= red <= 160
        magenta = red >= 160 and blue >= 160 and green <= 140
        if grey or magenta:
            pixels[i] = pixels[i + 1] = pixels[i + 2] = 255
            pixels[i + 3] = 0
    return encode_rgba(width, height, pixels)


def validate_manifest(value, now=None):
    now = time.time() if now is None else now
    if not isinstance(value, dict) or value.get("host") != RADAR_HOST:
        raise ValueError("Invalid radar tile source")
    radar = value.get("radar")
    frames = radar.get("past") if isinstance(radar, dict) else None
    if not isinstance(frames, list) or len(frames) > 24:
        raise ValueError("Invalid radar sequence")
    found = {}
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        stamp, path = frame.get("time"), frame.get("path")
        if type(stamp) is not int or not now - 86400 <= stamp <= now + 300:
            continue
        # Live manifests use opaque frame tokens as well as numeric identifiers.
        if not isinstance(path, str) or not re.fullmatch(r"/v2/radar/[A-Za-z0-9_-]{1,80}", path):
            continue
        found[stamp] = {"time": stamp, "path": path}
    if not found:
        raise ValueError("No recent radar image")
    return {"host": RADAR_HOST, "radar": {"past": [found[t] for t in sorted(found)[-13:]]}}


def manifest():
    path = CACHE / "manifest.json"
    saved = read_json(path, {})
    try:
        cached = validate_manifest(saved)
    except ValueError:
        cached = None
    if cached and time.time() - path.stat().st_mtime < 300:
        return cached, time.time() - cached["radar"]["past"][-1]["time"] > 1800
    try:
        result = validate_manifest(json.loads(download(MANIFEST_URL, JSON_LIMIT)))
        save_json(path, result)
        return result, time.time() - result["radar"]["past"][-1]["time"] > 1800
    except (OSError, ValueError):
        if cached:
            return cached, True
        raise


def viewport(lat, lon, zoom, width=432, height=240):
    """Only valid tiles intersecting the viewport; keep the selected point centred."""
    lat, lon = coordinates({"latitude": lat, "longitude": lon})
    if abs(lat) > MERCATOR_MAX_LATITUDE:
        raise ValueError("Map projection unavailable at this latitude")
    if (type(zoom) is not int or not MAP_MIN_ZOOM <= zoom <= MAP_MAX_ZOOM
            or type(width) is not int or type(height) is not int
            or not 1 <= width <= 1024 or not 1 <= height <= 1024):
        raise ValueError("Invalid map viewport")
    count = 2 ** zoom
    x = ((lon + 180) / 360 * count) % count
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * count
    left, top = x * 256 - width / 2, y * 256 - height / 2
    result = []
    for row in range(math.floor(top / 256), math.ceil((top + height) / 256)):
        for column in range(math.floor(left / 256), math.ceil((left + width) / 256)):
            if 0 <= row < count:
                result.append({"x": column % count, "y": row,
                               "left": column * 256 - left, "top": row * 256 - top})
    return result


def mercator_bounds(lat, lon, zoom, width=432, height=240):
    """Mercator box of the same viewport, for a single WMS radar request."""
    lat, lon = coordinates({"latitude": lat, "longitude": lon})
    if abs(lat) > MERCATOR_MAX_LATITUDE:
        raise ValueError("Map projection unavailable at this latitude")
    if (type(zoom) is not int or not MAP_MIN_ZOOM <= zoom <= MAP_MAX_ZOOM
            or type(width) is not int or type(height) is not int
            or not 1 <= width <= 1024 or not 1 <= height <= 1024):
        raise ValueError("Invalid map viewport")
    count = 2 ** zoom
    x = ((lon + 180) / 360 * count) % count
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * count
    left, top = x * 256 - width / 2, y * 256 - height / 2
    half = math.pi * 6378137.0
    world = count * 256
    min_x = left / world * 2 * half - half
    max_y = half - top / world * 2 * half
    max_x = (left + width) / world * 2 * half - half
    min_y = half - (top + height) / world * 2 * half
    return min_x, min_y, max_x, max_y


def dwd_times(now=None):
    """Five-minute steps: two observed hours, then the two-hour nowcast."""
    now = time.time() if now is None else now
    latest = int((now - DWD_LAG) // DWD_STEP * DWD_STEP)
    past = [latest - i * DWD_STEP for i in range(DWD_PAST_FRAMES - 1, -1, -1)]
    future = [latest + i * DWD_STEP for i in range(1, DWD_FUTURE_FRAMES + 1)]
    return past, future


def dwd_url(layer, stamp, bounds):
    return DWD_WMS + "?" + urlencode({
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
        "LAYERS": "dwd:" + layer, "STYLES": "", "FORMAT": "image/png",
        "TRANSPARENT": "true", "CRS": "EPSG:3857",
        "BBOX": ",".join(f"{value:.2f}" for value in bounds),
        "WIDTH": str(DWD_WIDTH), "HEIGHT": str(DWD_HEIGHT),
        "TIME": datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})


def dwd_image(url, future, network=True, deadline=None):
    """One viewport-sized PNG per frame, cached by its full request URL."""
    digest = hashlib.sha256(url.encode()).hexdigest()
    path = CACHE / "dwd-" / (digest + ".png")
    miss = CACHE / "dwd-" / (digest + ".miss")
    cached = None
    try:
        if path.stat().st_size <= IMAGE_LIMIT:
            data = path.read_bytes()
            if valid_png(data, (DWD_WIDTH, DWD_HEIGHT)):
                cached = path.resolve().as_uri()
                lifetime = DWD_FUTURE_TTL if future else 7 * 86400
                if time.time() - path.stat().st_mtime < lifetime:
                    return cached
    except OSError:
        pass
    if not network or (deadline is not None and time.monotonic() > deadline):
        return cached
    if future:
        try:
            # A forecast frame that is not yet published should not stall every load.
            if time.time() - miss.stat().st_mtime < DWD_RETRY:
                return cached
        except OSError:
            pass
    try:
        # GeoServer renders the forecast product slowly, often beyond five seconds.
        idle = 20 if deadline is None else max(1, min(20, deadline - time.monotonic()))
        data = download(url, IMAGE_LIMIT, idle)
        if not valid_png(data, (DWD_WIDTH, DWD_HEIGHT)):
            raise ValueError("Invalid radar image")
        save_bytes(path, strip_dwd_mask(data))
        try:
            miss.unlink()
        except OSError:
            pass
        return path.resolve().as_uri()
    except RateLimited:
        # The local guard refused this call, so the provider never reported the
        # frame as missing. Remembering a miss here would hide the frame for
        # five minutes and leave a permanent gap in the timeline.
        return cached
    except (OSError, ValueError):
        # A frame cut off by the shared window may succeed on a later load, so
        # only remember failures that happened before the deadline.
        if future and (deadline is None or time.monotonic() < deadline):
            try:
                save_bytes(miss, b"")
            except OSError:
                pass
        return cached


def wind_times(now=None):
    """Hourly ICON wind fields: the next twelve hours."""
    now = time.time() if now is None else now
    start = int(now // 3600 * 3600) + 3600
    return [start + i * 3600 for i in range(WIND_FRAMES)]


def wind_url(stamp, bounds):
    return DWD_WMS + "?" + urlencode({
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
        "LAYERS": "dwd:" + DWD_WIND_LAYER, "STYLES": "", "FORMAT": "image/png",
        "TRANSPARENT": "true", "CRS": "EPSG:3857",
        "BBOX": ",".join(f"{value:.2f}" for value in bounds),
        "WIDTH": str(WIND_WIDTH), "HEIGHT": str(WIND_HEIGHT),
        "TIME": datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})


def wind_image(url, network=True, deadline=None):
    """One wind-barb PNG per forecast hour, cached by its request URL.

    The wind map dims the basemap, so the barbs are stored in white. Older
    caches hold the black DWD barbs; a marker records the restyled copy, and
    each old frame is restyled once in place.
    """
    digest = hashlib.sha256(url.encode()).hexdigest()
    path = CACHE / "dwd-wind-" / (digest + ".png")
    marker = CACHE / "dwd-wind-" / (digest + ".white")
    cached = None
    try:
        if path.stat().st_size <= IMAGE_LIMIT:
            data = path.read_bytes()
            if valid_png(data, (WIND_WIDTH, WIND_HEIGHT)):
                if not marker.exists():
                    data = restyle_cached(path, data, marker)
                cached = path.resolve().as_uri()
                if time.time() - path.stat().st_mtime < WIND_TTL:
                    return cached
    except OSError:
        pass
    if not network or (deadline is not None and time.monotonic() > deadline):
        return cached
    try:
        idle = 12 if deadline is None else max(1, min(12, deadline - time.monotonic()))
        data = download(url, IMAGE_LIMIT, idle)
        if not valid_png(data, (WIND_WIDTH, WIND_HEIGHT)):
            raise ValueError("Invalid wind image")
        data = wind_style.restyle(data)
        save_bytes(path, data)
        marker.touch()
        return path.resolve().as_uri()
    except (OSError, ValueError):
        return cached


def restyle_cached(path, data, marker):
    """Recolour a cached barb image once for the dimmed map."""
    try:
        light = wind_style.restyle(data)
    except ValueError:
        return data
    save_bytes(path, light)
    marker.touch()
    return light


def prefetch_dwd(urls, forecast=True):
    """Warm slow DWD frames after the response, without blocking the panel.

    The DWD product layer needs several seconds per frame. The foreground load
    returns observed frames at once and leaves the nowcast to this worker, so
    the next radar open finds a complete timeline in the cache. Frames render
    independently, so several requests run at the same time.
    """
    global _deadline
    if not urls:
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    try:
        pid = os.fork()
    except OSError:
        return
    if pid:
        return
    try:
        _deadline = None
        os.setsid()
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(null, fd)
        if null > 2:
            os.close(null)
        with (CACHE / ".dwd-prefetch").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os._exit(0)
            deadline = time.monotonic() + DWD_PREFETCH_SECONDS

            def warm(url):
                if time.monotonic() >= deadline:
                    return
                if forecast:
                    dwd_image(url, True, True, deadline)
                else:
                    wind_image(url, True, deadline)

            def image_path(url):
                folder = "dwd-" if forecast else "dwd-wind-"
                return CACHE / folder / (hashlib.sha256(url.encode()).hexdigest() + ".png")

            def missing(url):
                path = image_path(url)
                size = (DWD_WIDTH, DWD_HEIGHT) if forecast else (WIND_WIDTH, WIND_HEIGHT)
                try:
                    return not (path.stat().st_size <= IMAGE_LIMIT
                                and valid_png(path.read_bytes(), size))
                except OSError:
                    return True

            with ThreadPoolExecutor(max_workers=DWD_PREFETCH_WORKERS) as pool:
                list(pool.map(warm, urls))
            # A short retry round repairs the frames a busy first burst dropped.
            # Fewer workers keep the second round gentle on the render service.
            retries = [url for url in urls if missing(url)]
            if retries and time.monotonic() < deadline:
                time.sleep(1)
                for url in retries:
                    try:
                        image_path(url).with_suffix(".miss").unlink()
                    except OSError:
                        pass
                with ThreadPoolExecutor(max_workers=3) as pool:
                    list(pool.map(warm, retries))
        os._exit(0)
    except BaseException:
        os._exit(1)


def osm_room(preserve):
    """Reserve one bounded response without evicting OSM tiles younger than 7 days."""
    entries = []
    for path in (CACHE / "osm-").glob("*.png"):
        try:
            stat = path.stat()
            entries.append((stat.st_mtime, path, stat.st_size))
        except OSError:
            continue
    total = sum(item[2] for item in entries)
    for modified, path, size in sorted(entries):
        if total + IMAGE_LIMIT <= OSM_CACHE_BYTES:
            break
        if path != preserve and time.time() - modified >= 7 * 86400:
            try:
                path.unlink()
                total -= size
            except OSError:
                pass
    return total + IMAGE_LIMIT <= OSM_CACHE_BYTES


def _tile(url, osm=False, network=True, deadline=None):
    digest = hashlib.sha256(url.encode()).hexdigest()
    coverage = url.startswith(RADAR_HOST + "/v2/coverage/")
    path = CACHE / ("osm-" if osm else "coverage-" if coverage else "radar-") / (digest + ".png")
    cached = None
    try:
        if path.stat().st_size <= IMAGE_LIMIT:
            data = path.read_bytes()
            if valid_png(data):
                cached = path.resolve().as_uri()
                if time.time() - path.stat().st_mtime < (7 * 86400 if osm or coverage else 86400):
                    return cached
    except OSError:
        pass
    if not network or (deadline is not None and time.monotonic() > deadline):
        return cached
    if osm and not osm_room(path):
        return cached  # Refuse a new request rather than repeatedly fetch/evict protected tiles.
    try:
        data = download(url, IMAGE_LIMIT)
        if not valid_png(data):
            raise ValueError("Invalid radar image")
        save_bytes(path, data)
        return path.resolve().as_uri()
    except (OSError, ValueError):
        return cached


def tile(url, osm=False, network=True, deadline=None):
    if not osm:
        return _tile(url, False, network, deadline)
    CACHE.mkdir(parents=True, exist_ok=True)
    # Serialize quota reservation and write, including across simultaneous shell instances.
    with (CACHE / ".osm-cache-lock").open("a") as lock, file_lock(lock):
        return _tile(url, True, network, deadline)


def prune_cache(protected=()):
    """Bound disk usage without prematurely re-fetching recently viewed OSM tiles."""
    CACHE.mkdir(parents=True, exist_ok=True)
    entries = []
    protected = set(protected)
    for folder in (CACHE / "osm-", CACHE / "radar-", CACHE / "coverage-", CACHE / "dwd-", CACHE / "dwd-wind-"):
        if not folder.exists():
            continue
        for path in folder.glob("*.png"):
            try:
                stat = path.stat()
                entries.append((stat.st_mtime, path, stat.st_size))
            except OSError:
                continue
    total = sum(item[2] for item in entries)
    for marker in (CACHE / "dwd-").glob("*.miss"):
        try:
            if time.time() - marker.stat().st_mtime >= DWD_RETRY:
                marker.unlink()
        except OSError:
            pass
    # Radar imagery is expendable before a map tile's minimum cache lifetime.
    for modified, path, size in sorted(entries, key=lambda item: (item[1].parent.name == "osm-", item[0])):
        age = time.time() - modified
        keep = path in protected or (path.parent.name == "osm-" and age < 7 * 86400)
        lifetime = 30 * 86400 if path.parent.name == "osm-" else 7 * 86400 if path.parent.name == "coverage-" else 86400
        if not keep and (age > lifetime or total > MAX_CACHE_BYTES):
            try:
                path.unlink()
                total -= size
                marker = path.with_suffix(".white")
                if marker.exists():
                    marker.unlink()
            except OSError:
                pass


def cached_path(source):
    return Path(unquote(urlsplit(source).path))


def load_rainviewer(city, prefs):
    lat, lon = coordinates(city)
    if abs(lat) > MERCATOR_MAX_LATITUDE:
        return {"settings": prefs, "latitude": lat, "longitude": lon,
                "tiles": [], "frames": [], "coverage_tiles": [], "coverage_status": "unsupported",
                "status": "unsupported", "reason": "projection_limit",
                "capabilities": {"radar": {"status": "unsupported", "source": "RainViewer", "reason": "projection_limit"}},
                "error": "Radar map projection is unavailable beyond 85.05° latitude. The selected location has not moved."}
    # RainViewer publishes radar tiles up to zoom 7 only.
    zoom = min(prefs["zoom"], RAINVIEWER_MAX_ZOOM)
    layout = viewport(lat, lon, zoom)
    value, stale = manifest()
    frames = value["radar"]["past"]
    deadline = _deadline
    jobs = [("base", i, f"{OSM_HOST}/{zoom}/{t['x']}/{t['y']}.png", True)
            for i, t in enumerate(layout)]
    jobs.extend(("coverage", i, f"{RADAR_HOST}/v2/coverage/0/256/{zoom}/{t['x']}/{t['y']}/0/0_0.png", False)
                for i, t in enumerate(layout))
    # Prioritise the newest observation if the bounded request budget is exhausted.
    for frame_index in range(len(frames)-1, -1, -1):
        frame = frames[frame_index]
        for i, t in enumerate(layout):
            jobs.append((frame_index, i, f"{RADAR_HOST}{frame['path']}/256/{zoom}/{t['x']}/{t['y']}/2/1_0.png", False))
    def fetch(job):
        group, index, url, osm = job
        return group, index, tile(url, osm, not stale, deadline)
    images = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for group, index, source in pool.map(fetch, jobs):
            images[group, index] = source
    base = [dict(t, source=images.get(("base", i)) or "") for i, t in enumerate(layout)]
    ready = []
    for fi, frame in enumerate(frames):
        if all(images.get((fi, i)) for i in range(len(layout))):
            ready.append({"time": frame["time"], "tiles": [images[fi, i] for i in range(len(layout))],
                          **local_frame_time(frame["time"], city)})
    protected = {cached_path(source) for source in images.values() if source}
    prune_cache(protected)
    result = {"settings": prefs, "latitude": lat, "longitude": lon, "tiles": base,
              "frames": ready, "render": "tiles", "stale": stale, "width": 432, "height": 240,
              "partial": len(ready) < len(frames) or any(not t["source"] for t in base)}
    coverage = [dict(t, source=images.get(("coverage", i)) or "") for i, t in enumerate(layout)]
    result.update(coverage_tiles=coverage,
                  coverage_status="available" if all(t["source"] for t in coverage) else "unknown",
                  provider="RainViewer")
    # A downloaded mask is evidence of coverage metadata, never evidence of dry weather.
    result["capabilities"] = {"radar": {"status": ("partial" if result["partial"] else "available") if ready else "unavailable", "source": "RainViewer"}}
    if ready and ready[0].get("timezone"):
        result["timezone"] = ready[0]["timezone"]
    if not ready:
        result["error"] = "Radar unavailable. Try again in a minute."
    elif result["partial"]:
        result["message"] = "Some images or tiles are unavailable."
    return result


def load_wind(city, prefs):
    lat, lon = coordinates(city)
    unsupported = {"settings": prefs, "latitude": lat, "longitude": lon,
                   "tiles": [], "frames": [], "coverage_tiles": [], "coverage_status": "unsupported",
                   "status": "unsupported", "render": "raster", "layer": "wind",
                   "capabilities": {"radar": {"status": "unsupported", "source": "DWD", "reason": "coverage_limit"}}}
    if not dwd_covers(city):
        return {**unsupported, "reason": "coverage_limit",
                "error": "The wind map covers Germany only. Choose a German city."}
    if abs(lat) > MERCATOR_MAX_LATITUDE:
        return {**unsupported, "reason": "projection_limit",
                "error": "The wind map projection is unavailable beyond 85.05° latitude."}
    zoom = prefs["zoom"]
    layout = viewport(lat, lon, zoom)
    bounds = mercator_bounds(lat, lon, zoom)
    deadline = _deadline
    times = wind_times()
    images = {}
    jobs = [("base", i, f"{OSM_HOST}/{zoom}/{t['x']}/{t['y']}.png")
            for i, t in enumerate(layout)]
    # Only the first hour paints with the map. Wind barbs take seconds to
    # render, so the rest of the day warms in the background.
    near = times[:1]
    jobs.extend(("wind", stamp, wind_url(stamp, bounds)) for stamp in near)
    def run(job):
        kind, key, url = job
        source = tile(url, True, True, deadline) if kind == "base" else wind_image(url, True, deadline)
        return kind, key, source
    with ThreadPoolExecutor(max_workers=12) as pool:
        for kind, key, source in pool.map(run, jobs):
            images[kind, key] = source
    if not any(images.get(("wind", stamp)) for stamp in near):
        # DWD can drop a burst of renders while a radar prefetch is busy. Try
        # the near hour once, within the remaining first-paint budget, so the
        # first paint is not an error message.
        retry_deadline = time.monotonic() + 8
        if deadline is not None:
            retry_deadline = min(retry_deadline, deadline)
        for stamp in near:
            source = wind_image(wind_url(stamp, bounds), True, retry_deadline)
            if source:
                images["wind", stamp] = source
                break
    waiting = []
    for stamp in times:
        url = wind_url(stamp, bounds)
        source = images.get(("wind", stamp)) or wind_image(url, False)
        if source:
            images["wind", stamp] = source
        else:
            waiting.append(url)
    if waiting:
        prefetch_dwd(waiting, forecast=False)
    base = [dict(t, source=images.get(("base", i)) or "") for i, t in enumerate(layout)]
    frames = [{"time": stamp, "image": images["wind", stamp], "forecast": True,
               **local_frame_time(stamp, city)}
              for stamp in times if images.get(("wind", stamp))]
    prune_cache({cached_path(source) for source in images.values() if source})
    partial = any(not t["source"] for t in base)
    result = {"settings": prefs, "latitude": lat, "longitude": lon,
              "tiles": base, "frames": frames, "render": "raster", "layer": "wind",
              "width": 432, "height": 240, "stale": False,
              "forecast": bool(frames), "default_index": 0,
              "partial": partial, "provider": "DWD", "model": "ICON",
              "warming": bool(waiting),
              "coverage_tiles": [], "coverage_status": "unknown",
              "capabilities": {"radar": {"status": "available" if frames else "unavailable", "source": "DWD"}}}
    if frames and frames[0].get("timezone"):
        result["timezone"] = frames[0]["timezone"]
    if not frames:
        result["error"] = "Wind map unavailable. Try again in a minute."
    elif partial:
        result["message"] = "Some map tiles are unavailable."
    return result


def load_dwd(city, prefs):
    lat, lon = coordinates(city)
    if not dwd_covers(city):
        return {"settings": prefs, "latitude": lat, "longitude": lon,
                "tiles": [], "frames": [], "coverage_tiles": [], "coverage_status": "unsupported",
                "status": "unsupported", "reason": "coverage_limit",
                "capabilities": {"radar": {"status": "unsupported", "source": "DWD", "reason": "coverage_limit"}},
                "error": "DWD radar covers Germany only. Choose another source or a German city."}
    if abs(lat) > MERCATOR_MAX_LATITUDE:
        return {"settings": prefs, "latitude": lat, "longitude": lon,
                "tiles": [], "frames": [], "coverage_tiles": [], "coverage_status": "unsupported",
                "status": "unsupported", "reason": "projection_limit",
                "capabilities": {"radar": {"status": "unsupported", "source": "DWD", "reason": "projection_limit"}},
                "error": "Radar map projection is unavailable beyond 85.05° latitude. The selected location has not moved."}
    zoom = prefs["zoom"]
    layout = viewport(lat, lon, zoom)
    bounds = mercator_bounds(lat, lon, zoom)
    past, future = dwd_times()
    deadline = _deadline
    jobs = [("base", i, f"{OSM_HOST}/{zoom}/{t['x']}/{t['y']}.png", True, False)
            for i, t in enumerate(layout)]
    # Paint the basemap and the latest observation first. The nowcast layer is
    # the slowest DWD render, so it and the older observations warm in the
    # background. Playback arms on one frame and starts as frames arrive.
    jobs.append(("past", past[-1], dwd_url(DWD_PAST_LAYER, past[-1], bounds), False, False))
    def fetch(deadline):
        def run(job):
            kind, key, url, osm, forecast = job
            source = tile(url, osm, True, deadline) if osm else dwd_image(url, forecast, True, deadline)
            return kind, key, source
        return run
    images = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        for kind, key, source in pool.map(fetch(deadline), jobs):
            images[kind, key] = source
    missing = []
    for stamp in past[:-1]:
        url = dwd_url(DWD_PAST_LAYER, stamp, bounds)
        source = dwd_image(url, False, False)
        if source:
            images["past", stamp] = source
        else:
            missing.append((stamp, url))
    for stamp in future:
        url = dwd_url(DWD_FUTURE_LAYER, stamp, bounds)
        source = dwd_image(url, True, False)
        if source:
            images["future", stamp] = source
        else:
            missing.append((stamp, url))
    # Warm the frames nearest the present first. The prefetch renders six
    # frames at once, so a cold timeline becomes playable in the direction
    # the user is looking before the older hours fill in.
    present = past[-1]
    prefetch_dwd([url for _, url in sorted(
        missing, key=lambda item: (abs(item[0] - present), item[0] < present))])
    base = [dict(t, source=images.get(("base", i)) or "") for i, t in enumerate(layout)]
    frames = []
    default_index = -1
    for stamp in past:
        source = images.get(("past", stamp))
        if not source:
            continue
        default_index = len(frames)
        frames.append({"time": stamp, "image": source, "forecast": False,
                       **local_frame_time(stamp, city)})
    for stamp in future:
        source = images.get(("future", stamp))
        if not source:
            continue
        frames.append({"time": stamp, "image": source, "forecast": True,
                       **local_frame_time(stamp, city)})
    protected = {cached_path(source) for source in images.values() if source}
    prune_cache(protected)
    # A not-yet-published newest observation is not a partial failure.
    missing = [stamp for stamp in past if not images.get(("past", stamp))]
    waiting = missing or [stamp for stamp in future if not images.get(("future", stamp))]
    partial = any(not t["source"] for t in base)
    result = {"settings": prefs, "latitude": lat, "longitude": lon,
              "tiles": base, "frames": frames, "render": "raster",
              "width": 432, "height": 240, "stale": False,
              "forecast": any(frame["forecast"] for frame in frames),
              "default_index": default_index if default_index >= 0 else max(0, len(frames) - 1),
              "partial": partial, "provider": "DWD", "warming": bool(waiting),
              "coverage_tiles": [], "coverage_status": "unknown",
              "capabilities": {"radar": {"status": ("partial" if partial else "available") if frames else "unavailable", "source": "DWD"}}}
    if frames and frames[0].get("timezone"):
        result["timezone"] = frames[0]["timezone"]
    if not frames:
        result["error"] = "DWD radar unavailable. Try again in a minute."
    elif partial:
        result["message"] = "Some images or tiles are unavailable."
    return result


@request_budget(FIRST_PAINT_SECONDS)
def load(city):
    prefs = settings()
    if not prefs["enabled"]:
        return {"settings": prefs, "frames": [], "tiles": []}
    if prefs["layer"] == "wind":
        result = load_wind(city, prefs)
        result["settings"] = prefs
        return result
    source = prefs["source"]
    if source == "auto":
        source = "dwd" if dwd_covers(city) else "rainviewer"
    result = load_dwd(city, prefs) if source == "dwd" else load_rainviewer(city, prefs)
    result["settings"] = prefs
    result.setdefault("provider", "DWD" if source == "dwd" else "RainViewer")
    return result


def main(args):
    action = args[0] if args else "settings"
    if action == "settings":
        return {"settings": settings()}
    if action == "configure":
        return {"settings": configure(json.loads(args[1]))}
    if action == "load":
        return load(json.loads(args[1]))
    raise ValueError("Unknown radar action")


if __name__ == "__main__":
    try:
        output = bounded_cli(lambda: main(sys.argv[1:]), lambda: {"settings": settings(), "frames": []})
    except Exception:
        output = {"settings": settings(), "frames": [], "error": "Radar connection unavailable. Please try again."}
    print(json.dumps(output, ensure_ascii=False, allow_nan=False))
