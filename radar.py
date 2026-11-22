#!/usr/bin/env python3
"""Rain and wind radars; Python standard library only.

Rain shows observed and predicted radar images. In Germany this is the DWD
composite at five minute steps, from two hours before now to two hours after.
Elsewhere it is RainViewer's worldwide feed. Wind shows a model vector grid
from Open-Meteo at fifteen minute steps over the same window.

The `load` action prints one JSON object per line. The first line carries the
map layout and every frame without images, so the interface can paint the
basemap at once. Each following line adds one rain frame image as it lands,
newest first. Images are validated PNGs cached on disk.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
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
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from image_validation import PNG as PNG, png_size

STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "pixel-weather"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "pixel-weather/radar"
MANIFEST_URL = "https://api.rainviewer.com/public/weather-maps.json"
RADAR_HOST = "https://tilecache.rainviewer.com"
OSM_HOST = "https://tile.openstreetmap.org"
BRIGHT_SKY_HOST = "https://api.brightsky.dev"
OPEN_METEO_HOST = "https://api.open-meteo.com"
DWD_WMS_HOST = "https://maps.dwd.de/geoserver/dwd/ows"
USER_AGENT = "OWEE/1.3 (community desktop weather)"
MERCATOR_MAX_LATITUDE = 85.05112878
VIEW_WIDTH = 432
VIEW_HEIGHT = 240
WINDOW_SECONDS = 7200  # Half the timeline on each side of now.
WIND_SECONDS = 900     # Wind steps: Open-Meteo's finest 10 m wind interval.
DWD_BOX = (46.5, 5.0, 55.5, 16.0)
VALID_SIZES = {(256, 256), (512, 512), (VIEW_WIDTH, VIEW_HEIGHT)}
JSON_LIMIT = 2_097_152
IMAGE_LIMIT = 1_000_000
MAX_CACHE_BYTES = 96 * 1024 * 1024
OSM_CACHE_BYTES = 32 * 1024 * 1024
WIND_MAX_AGE = 600
RATE_LOCK = threading.Lock()
# The DWD WMS renders each requested timestep on demand; a cold composite of
# the full four hour window can take minutes before every frame is rendered.
# Frames stream as they finish, so the interface is never blocked on this.
REQUEST_SECONDS = 240
_deadline = None


@contextmanager
def request_budget():
    """Share one monotonic budget across metadata, imagery and basemap workers."""
    global _deadline
    previous = _deadline
    _deadline = min(previous, time.monotonic() + REQUEST_SECONDS) if previous is not None else time.monotonic() + REQUEST_SECONDS
    try:
        yield
    finally:
        _deadline = previous


def remaining_timeout(idle):
    remaining = REQUEST_SECONDS if _deadline is None else _deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Map request timed out")
    return min(idle, remaining)


def read_response(response, limit, idle=8):
    """Read available chunks rather than allowing a slow drip to reset the budget."""
    output = bytearray()
    while len(output) <= limit:
        timeout = remaining_timeout(idle)
        socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if socket is not None:
            socket.settimeout(timeout)
        block = getattr(response, "read1", response.read)(min(65_536, limit + 1 - len(output)))
        if not block:
            break
        output.extend(block)
    remaining_timeout(idle)
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


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def clamp(value, low, high):
    return low if value < low else high if value > high else value


def settings():
    raw = read_json(STATE / "radar-settings.json", {})
    if not isinstance(raw, dict):
        raw = {}
    zoom_level = raw.get("zoom_level")
    if type(zoom_level) is not int or not -2 <= zoom_level <= 3:
        # One older stored `zoom` maps to the same physical extent: 6 was 150 km.
        old = raw.get("zoom")
        zoom_level = clamp(old - 6, -2, 3) if type(old) is int and 3 <= old <= 7 else 1
    # Rain and wind switch separately; a legacy plain `enabled` seeds both.
    legacy = raw.get("enabled")
    legacy = legacy is not False if type(legacy) is not bool else legacy
    rain = raw.get("rain_enabled")
    wind = raw.get("wind_enabled")
    rain_enabled = legacy if type(rain) is not bool else rain
    wind_enabled = legacy if type(wind) is not bool else wind
    return {"enabled": rain_enabled and wind_enabled,
            "rain_enabled": rain_enabled, "wind_enabled": wind_enabled,
            "zoom_level": zoom_level}


def configure(value):
    with storage.lock(STATE / ".radar-settings.lock"):
        return _configure(value)

def _configure(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid radar setting")
    current = settings()
    if "rain_enabled" in value or "wind_enabled" in value or "enabled" in value:
        for key in ("rain_enabled", "wind_enabled"):
            if key in value:
                if type(value[key]) is not bool:
                    raise ValueError("Invalid radar activation")
                current[key] = value[key]
        if "enabled" in value:
            if type(value["enabled"]) is not bool:
                raise ValueError("Invalid radar activation")
            current["rain_enabled"] = current["wind_enabled"] = value["enabled"]
        current["enabled"] = current["rain_enabled"] and current["wind_enabled"]
    if "zoom_level" in value:
        if type(value["zoom_level"]) is not int or not -2 <= value["zoom_level"] <= 3:
            raise ValueError("Invalid radar zoom")
        current["zoom_level"] = value["zoom_level"]
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
        if parsed.scheme != "https" or parsed.netloc not in {
                "api.rainviewer.com", "tilecache.rainviewer.com", "tile.openstreetmap.org",
                "maps.dwd.de", "api.brightsky.dev", "api.open-meteo.com"}:
            raise ValueError("Radar redirect refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


HOSTS = {"api.rainviewer.com", "tilecache.rainviewer.com", "tile.openstreetmap.org",
         "maps.dwd.de", "api.brightsky.dev", "api.open-meteo.com"}


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
            if len(recent) >= 90:
                raise OSError("Radar rate limit reached; try again in a minute")
            save_json(CACHE / "requests.json", recent + [now])
            yield
    finally:
        RATE_LOCK.release()


def download(url, limit, idle=8):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc not in HOSTS:
        raise ValueError("Radar source refused")
    with rate_guard():
        pass
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/png, application/json"})
    with build_opener(SafeRedirect()).open(req, timeout=remaining_timeout(idle)) as response:
        return read_response(response, limit, idle)


def valid_png(data):
    try:
        return png_size(data) in VALID_SIZES
    except ValueError:
        return False


def epoch_of(text):
    """Bright Sky stamps carry an offset; naive text is read as UTC."""
    if not isinstance(text, str) or not 4 <= len(text) <= 64:
        raise ValueError("Invalid timestamp")
    clock = datetime.fromisoformat(text)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    return clock.timestamp()


def iso_utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_offset(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def extent(lat, lon, zoom_level):
    """Physical map extent. One zoom step changes the half extent by 1.5."""
    radius = 150 / 1.5 ** zoom_level
    lat_radius = radius * (VIEW_HEIGHT / VIEW_WIDTH) / 111.32
    lon_radius = radius / (111.32 * max(0.2, math.cos(math.radians(lat))))
    circumference = 40075 * max(0.2, math.cos(math.radians(lat)))
    # The tile zoom is rounded down, so one tile always spans the whole view.
    tile_zoom = clamp(int(math.floor(math.log(circumference / max(1.0, 2 * radius), 2))), 1, 7)
    return {"latitude": lat, "longitude": lon, "zoom_level": zoom_level, "radius_km": radius,
            "west": lon - lon_radius, "east": lon + lon_radius,
            "south": lat - lat_radius, "north": lat + lat_radius,
            "circumference": circumference, "tile_zoom": tile_zoom}


def tile_layout(latitude, longitude, zoom, tile_pixels, width=VIEW_WIDTH, height=VIEW_HEIGHT):
    """Tiles of one zoom level, placed so the selected point stays centred."""
    count = 2 ** zoom
    x = ((longitude + 180) / 360 * count) % count
    y = (1 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2 * count
    column, row = math.floor(x), math.floor(y)
    left_edge = width / 2 - (x - column) * tile_pixels
    top_edge = height / 2 - (y - row) * tile_pixels
    span = max(1, math.ceil(width / tile_pixels)) + 1
    rows = max(1, math.ceil(height / tile_pixels)) + 1
    result = []
    for tile_row in range(row - rows, row + rows + 1):
        if not 0 <= tile_row < count:
            continue
        for tile_column in range(column - span, column + span + 1):
            left = left_edge + (tile_column - column) * tile_pixels
            top = top_edge + (tile_row - row) * tile_pixels
            if left + tile_pixels <= 0 or left >= width or top + tile_pixels <= 0 or top >= height:
                continue
            result.append({"x": tile_column % count, "y": tile_row,
                           "left": left, "top": top,
                           "width": tile_pixels, "height": tile_pixels})
    return result


def viewport(lat, lon, zoom, width=VIEW_WIDTH, height=VIEW_HEIGHT):
    """Only valid tiles intersecting the viewport; keep the selected point centred."""
    lat, lon = coordinates({"latitude": lat, "longitude": lon})
    if abs(lat) > MERCATOR_MAX_LATITUDE:
        raise ValueError("Map projection unavailable at this latitude")
    if (type(zoom) is not int or not 3 <= zoom <= 7
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


def validate_manifest(value, now=None):
    now = time.time() if now is None else now
    if not isinstance(value, dict) or value.get("host") != RADAR_HOST:
        raise ValueError("Invalid radar tile source")
    radar = value.get("radar")
    if not isinstance(radar, dict):
        raise ValueError("Invalid radar sequence")
    bounds = {"past": (now - 86400, now + 300), "nowcast": (now - 300, now + WINDOW_SECONDS)}
    found = {"past": {}, "nowcast": {}}
    for group, (low, high) in bounds.items():
        frames = radar.get(group)
        if not isinstance(frames, list) or len(frames) > 24:
            continue
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            stamp, path = frame.get("time"), frame.get("path")
            if type(stamp) is not int or not low <= stamp <= high:
                continue
            # Live manifests use opaque frame tokens as well as numeric identifiers.
            if not isinstance(path, str) or not re.fullmatch(r"/v2/radar/[A-Za-z0-9_-]{1,80}", path):
                continue
            found[group][stamp] = {"time": stamp, "path": path}
    if not found["past"]:
        raise ValueError("No recent radar image")
    past = [found["past"][t] for t in sorted(found["past"])[-13:]]
    # Never show a "future" frame that is already older than the newest observation.
    cut = past[-1]["time"]
    nowcast = [found["nowcast"][t] for t in sorted(found["nowcast"]) if t > cut][:13]
    return {"host": RADAR_HOST, "radar": {"past": past, "nowcast": nowcast}}


def manifest():
    path = CACHE / "manifest.json"
    saved = read_json(path, {})
    try:
        cached = validate_manifest(saved)
    except ValueError:
        cached = None
    try:
        if cached and time.time() - path.stat().st_mtime < 300:
            return cached, time.time() - cached["radar"]["past"][-1]["time"] > 1800
    except OSError:
        pass
    try:
        result = validate_manifest(json.loads(download(MANIFEST_URL, JSON_LIMIT)))
        save_json(path, result)
        return result, time.time() - result["radar"]["past"][-1]["time"] > 1800
    except (OSError, ValueError):
        if cached:
            return cached, True
        raise


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
    path = CACHE / ("osm-" if osm else "radar-") / (digest + ".png")
    cached = None
    try:
        if path.stat().st_size <= IMAGE_LIMIT:
            data = path.read_bytes()
            if valid_png(data):
                cached = path.resolve().as_uri()
                if time.time() - path.stat().st_mtime < (7 * 86400 if osm else 86400):
                    return cached
    except OSError:
        pass
    if not network or (deadline is not None and time.monotonic() > deadline):
        return cached
    if osm and not osm_room(path):
        return cached  # Refuse a new request rather than repeatedly fetch/evict protected tiles.
    try:
        # The DWD WMS renders cold timesteps on demand; first bytes can take
        # well past the eight second idle cap used for fast CDN sources.
        data = download(url, IMAGE_LIMIT, idle=8 if osm else 30)
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
    for folder in (CACHE / "osm-", CACHE / "radar-"):
        if not folder.exists():
            continue
        for path in folder.glob("*.png"):
            try:
                stat = path.stat()
                entries.append((stat.st_mtime, path, stat.st_size))
            except OSError:
                continue
    total = sum(item[2] for item in entries)
    # Radar imagery is expendable before a map tile's minimum cache lifetime.
    for modified, path, size in sorted(entries, key=lambda item: (item[1].parent.name == "osm-", item[0])):
        age = time.time() - modified
        keep = path in protected or (path.parent.name == "osm-" and age < 7 * 86400)
        lifetime = 30 * 86400 if path.parent.name == "osm-" else 86400
        if not keep and (age > lifetime or total > MAX_CACHE_BYTES):
            try:
                path.unlink()
                total -= size
            except OSError:
                pass


def dwd_area(lat, lon):
    return DWD_BOX[0] <= lat <= DWD_BOX[2] and DWD_BOX[1] <= lon <= DWD_BOX[3]


def city_zone(city):
    zone = city.get("timezone") if isinstance(city, dict) else None
    if isinstance(zone, str) and 0 < len(zone) <= 80:
        try:
            ZoneInfo(zone)
            return zone
        except (ValueError, ZoneInfoNotFoundError, OSError):
            pass
    return "Europe/Berlin"


def dwd_timeline(city, now):
    """Bright Sky returns the DWD composite timeline: five minute steps,
    observed frames behind now and RV predictions ahead of it."""
    url = (BRIGHT_SKY_HOST + "/radar?lat=" + quote(f"{city['latitude']:.5f}")
           + "&lon=" + quote(f"{city['longitude']:.5f}") + "&distance=1000"
           + "&tz=" + quote(city_zone(city))
           + "&date=" + quote(iso_offset(now - WINDOW_SECONDS))
           + "&last_date=" + quote(iso_offset(now + WINDOW_SECONDS)))
    parsed = json.loads(download(url, JSON_LIMIT))
    records = parsed.get("radar") if isinstance(parsed, dict) else None
    if not isinstance(records, list) or not records or len(records) > 200:
        raise ValueError("Invalid DWD radar timeline")
    found = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            stamp = epoch_of(record.get("timestamp"))
        except ValueError:
            continue
        if not now - WINDOW_SECONDS - 300 <= stamp <= now + WINDOW_SECONDS + 300:
            continue
        source = record.get("source")
        reference = iso_utc(epoch_of(source.split("::")[-1])) if isinstance(source, str) and source else iso_utc(stamp)
        found[stamp] = reference
    if not found:
        raise ValueError("No DWD radar frames")
    stamps = sorted(found)
    now_index = max((index for index, stamp in enumerate(stamps) if stamp <= now), default=-1)
    frames = [{"time": stamp, "kind": "past" if stamp <= now else "future",
               "reference": found[stamp],
               **local_frame_time(stamp, city)} for stamp in stamps]
    return frames, now_index


def dwd_frame_url(ext, stamp, reference):
    bbox = ",".join(f"{ext[key]:.4f}" for key in ("west", "south", "east", "north"))
    return (DWD_WMS_HOST + "?service=WMS&version=1.1.1&request=GetMap"
            + "&layers=" + quote("dwd:Niederschlagsradar", safe="") + "&styles="
            + "&bbox=" + quote(bbox, safe=",") + "&width=" + str(VIEW_WIDTH) + "&height=" + str(VIEW_HEIGHT)
            + "&srs=EPSG:4326&format=image/png&transparent=true"
            + "&time=" + quote(iso_utc(stamp)) + "&DIM_REFERENCE_TIME=" + quote(reference))


def rainviewer_timeline(ext, city, now):
    """RainViewer composites worldwide; predictions exist only for part of the world."""
    value, stale = manifest()
    layout = tile_layout(ext["latitude"], ext["longitude"], ext["tile_zoom"],
                         ext["circumference"] / 2 ** ext["tile_zoom"] * VIEW_WIDTH / (2 * ext["radius_km"]))
    frames, paths = [], []
    for group, kind in (("past", "past"), ("nowcast", "future")):
        for frame in value["radar"][group]:
            if kind == "future" and frame["time"] <= now:
                continue
            paths.append((frame["time"], kind, frame["path"]))
    paths.sort(key=lambda item: (item[1] != "past", item[0]))
    for index, (stamp, kind, path) in enumerate(paths):
        frames.append({"time": stamp, "kind": kind, **local_frame_time(stamp, city),
                       "tiles": [dict(piece, source="") for piece in layout]})
    now_index = max((index for index, frame in enumerate(frames) if frame["time"] <= now), default=-1)
    jobs = [(index, tile_index, f"{RADAR_HOST}{frame_path}/512/{ext['tile_zoom']}/{tile['x']}/{tile['y']}/2/1_0.png")
            for index, (_, _, frame_path) in enumerate(paths)
            for tile_index, tile in enumerate(layout)]
    return frames, now_index, jobs, stale


def wind_grid(ext, now):
    """One Open-Meteo request for the whole vector grid; cached for ten minutes."""
    lat_radius = ext["north"] - ext["latitude"]
    lon_radius = ext["east"] - ext["longitude"]
    latitudes, longitudes = [], []
    for row in range(5):
        row_lat = ext["latitude"] + lat_radius - 2 * lat_radius * row / 4
        for column in range(7):
            latitudes.append(f"{row_lat:.4f}")
            longitudes.append(f"{ext['longitude'] - lon_radius + 2 * lon_radius * column / 6:.4f}")
    url = (OPEN_METEO_HOST + "/v1/forecast?latitude=" + quote(",".join(latitudes), safe=",")
           + "&longitude=" + quote(",".join(longitudes), safe=",")
           + "&minutely_15=wind_speed_10m,wind_direction_10m,wind_gusts_10m"
           + "&wind_speed_unit=kmh&timezone=UTC&past_days=1&forecast_days=1")
    parsed = json.loads(download(url, JSON_LIMIT))
    rows = parsed if isinstance(parsed, list) else [parsed]
    if len(rows) != 35:
        raise ValueError("Incomplete wind grid")
    low, high = now - 3 * 3600, now + 4 * 3600
    series = []
    for row in rows:
        block = row.get("minutely_15") if isinstance(row, dict) else None
        times = block.get("time") if isinstance(block, dict) else None
        speed = block.get("wind_speed_10m") if isinstance(block, dict) else None
        direction = block.get("wind_direction_10m") if isinstance(block, dict) else None
        gust = block.get("wind_gusts_10m") if isinstance(block, dict) else None
        if not all(isinstance(values, list) for values in (times, speed, direction, gust)):
            raise ValueError("Incomplete wind grid")
        keep = [index for index, stamp in enumerate(times)
                if isinstance(stamp, str) and low <= epoch_of(stamp) <= high]
        if len(keep) < 4:
            raise ValueError("Wind window unavailable")
        series.append({"latitude": round(float(row.get("latitude")), 4), "longitude": round(float(row.get("longitude")), 4),
                       "time": [times[index] for index in keep],
                       "speed": [speed[index] for index in keep],
                       "direction": [direction[index] for index in keep],
                       "gust": [gust[index] for index in keep]})
    return series


def number(values, index, digits=1):
    try:
        value = float(values[index])
    except (ValueError, TypeError, IndexError):
        return None
    if not math.isfinite(value):
        return None
    return round(value, digits)


def wind_timeline(ext, city, now):
    meta = {"provider_name": "Open-Meteo", "source_url": "https://open-meteo.com/",
            "step_minutes": WIND_SECONDS // 60, "now_index": -1, "stale": False, "frames": []}
    # The wind frames sit on the wall-clock 15 minute grid, so "now" snaps to
    # that grid as well: the timeline then opens on a frame that reads "now"
    # instead of one 5 or 10 minutes earlier.
    wind_now = (int(now) + WIND_SECONDS // 2) // WIND_SECONDS * WIND_SECONDS
    key = f"{ext['latitude']:.2f},{ext['longitude']:.2f},{ext['radius_km']:.0f}"
    path = CACHE / "wind.json"
    cached = read_json(path, {})
    fresh = isinstance(cached, dict) and cached.get("key") == key and now - cached.get("epoch", 0) < WIND_MAX_AGE
    series = cached.get("series") if isinstance(cached, dict) else None
    if not fresh:
        try:
            series = wind_grid(ext, now)
            save_json(path, {"key": key, "epoch": now, "series": series})
        except (OSError, ValueError):
            if cached.get("key") == key and isinstance(series, list) and series:
                meta["stale"] = True
            else:
                series = None
    if not series:
        return meta
    clocks = [epoch_of(stamp) for stamp in series[0]["time"]]
    index_of = {stamp: index for index, stamp in enumerate(clocks)}
    start = (wind_now - WINDOW_SECONDS) // WIND_SECONDS * WIND_SECONDS
    points, stamps = [], []
    for target in range(start, wind_now + WINDOW_SECONDS + 1, WIND_SECONDS):
        index = index_of.get(float(target))
        if index is None:
            continue
        stamps.append(target)
        points.append([[row["latitude"], row["longitude"],
                        number(row["speed"], index), number(row["direction"], index, 0),
                        number(row["gust"], index)]
                       for row in series])
    for index, (stamp, points_at) in enumerate(zip(stamps, points)):
        meta["frames"].append({"time": int(stamp), "kind": "past" if stamp <= wind_now else "future",
                               "points": points_at, **local_frame_time(stamp, city)})
    meta["now_index"] = max((index for index, stamp in enumerate(stamps) if stamp <= wind_now), default=-1)
    return meta


@request_budget()
def load(city):
    wanted = city.get("modes") if isinstance(city, dict) else None
    wanted = [mode for mode in wanted if mode in ("rain", "wind")] if isinstance(wanted, list) else ["rain", "wind"]
    prefs = settings()
    lat, lon = coordinates(city)
    if abs(lat) > MERCATOR_MAX_LATITUDE:
        emit({"kind": "meta", "settings": prefs, "latitude": lat, "longitude": lon,
              "tiles": [], "width": VIEW_WIDTH, "height": VIEW_HEIGHT,
              "rain": {"provider_name": "", "source_url": "", "step_minutes": 0, "now_index": -1, "frames": []},
              "wind": {"provider_name": "", "source_url": "", "step_minutes": 0, "now_index": -1, "frames": []},
              "status": "unsupported", "reason": "projection_limit",
              "error": "Radar map projection is unavailable beyond 85.05° latitude. The selected location has not moved."})
        emit({"kind": "done", "partial": False, "message": ""})
        return
    # Round to the nearest five minutes: frame leads then read in whole
    # timeline steps (5, 10, 15 min) instead of 8, 13, 18.
    now = (int(time.time()) + 150) // 300 * 300
    ext = extent(lat, lon, prefs["zoom_level"])
    pixels_per_km = VIEW_WIDTH / (2 * ext["radius_km"])
    base_zoom = clamp(ext["tile_zoom"] + 1, 2, 9)
    base_layout = tile_layout(lat, lon, base_zoom, ext["circumference"] / 2 ** base_zoom * pixels_per_km)
    deadline = _deadline
    stale = {"value": False}

    # The basemap comes first: the interface paints it while frames download.
    def fetch_base(index):
        piece = base_layout[index]
        url = f"{OSM_HOST}/{base_zoom}/{piece['x']}/{piece['y']}.png"
        return tile(url, True, True, deadline)

    with ThreadPoolExecutor(max_workers=8) as pool:
        base_sources = list(pool.map(fetch_base, range(len(base_layout))))
        base_tiles = [dict(piece, source=source) for piece, source in zip(base_layout, base_sources)]
        protected = {piece["source"] for piece in base_tiles if piece["source"]}

        rain = {"provider_name": "", "source_url": "", "step_minutes": 0, "now_index": -1,
                "stale": False, "frames": []}
        rain_off = "rain" not in wanted or not prefs["rain_enabled"]
        rain["disabled"] = rain_off
        rain_jobs = []
        if not rain_off:
            if dwd_area(lat, lon):
                rain["provider_name"], rain["source_url"], rain["step_minutes"] = "DWD", "https://www.dwd.de/", 5
                try:
                    frames, now_index = dwd_timeline(city, now)
                    rain["frames"] = [dict(frame, tiles=[{"left": 0, "top": 0, "width": VIEW_WIDTH, "height": VIEW_HEIGHT, "source": ""}]) for frame in frames]
                    rain["now_index"] = now_index
                    # Newest first: the interface paints the present conditions, then
                    # predictions, then the past.
                    order = sorted(range(len(frames)),
                                   key=lambda index: 0 if index == now_index else 1 + abs(index - now_index))
                    rain_jobs = [(index, 0, dwd_frame_url(ext, frames[index]["time"], frames[index]["reference"]))
                                 for index in order]
                except (OSError, ValueError):
                    rain = {"provider_name": "", "source_url": "", "step_minutes": 0, "now_index": -1,
                            "stale": False, "frames": []}
            if not rain["frames"]:
                try:
                    frames, now_index, jobs, stale["value"] = rainviewer_timeline(ext, city, now)
                    rain.update({"provider_name": "RainViewer", "source_url": "https://www.rainviewer.com/",
                                 "step_minutes": 10, "frames": frames, "now_index": now_index})
                    rain_jobs = jobs
                except (OSError, ValueError):
                    rain["stale"] = stale["value"]
                    rain["provider_name"] = ""
                    rain["source_url"] = ""
                    rain["step_minutes"] = 0
            elif stale["value"]:
                rain["stale"] = True

        if "wind" in wanted and prefs["wind_enabled"]:
            wind = wind_timeline(ext, city, now)
        else:
            wind = {"provider_name": "", "source_url": "", "step_minutes": 0,
                    "now_index": -1, "frames": [], "disabled": True}

        emit({"kind": "meta", "settings": prefs, "latitude": lat, "longitude": lon,
              "zoom_level": ext["zoom_level"], "radius_km": ext["radius_km"], "now": int(now),
              "west": ext["west"], "east": ext["east"], "south": ext["south"], "north": ext["north"],
              "width": VIEW_WIDTH, "height": VIEW_HEIGHT, "tiles": base_tiles,
              "rain": rain, "wind": wind})

        def fetch_rain(job):
            index, tile_index, url = job
            return tile(url, False, not stale["value"], deadline)

        pending = {pool.submit(fetch_rain, job): job for job in rain_jobs}
        finished = {}
        remaining = {}
        for frame_index, frame in enumerate(rain["frames"]):
            remaining[frame_index] = len(frame["tiles"])
        emitted = set()

        def complete(index):
            pieces = [dict(piece, source=finished.get((index, piece_index), ""))
                      for piece_index, piece in enumerate(rain["frames"][index]["tiles"])]
            rain["frames"][index]["tiles"] = pieces
            emit({"kind": "frame", "index": index, "tiles": pieces})

        for future in as_completed(pending):
            index, tile_index, _ = pending[future]
            try:
                source = future.result()
            except Exception:
                source = ""
            finished[index, tile_index] = source
            if source:
                protected.add(source)
            remaining[index] -= 1
            if remaining[index] <= 0 and index not in emitted:
                emitted.add(index)
                complete(index)

        # One second pass for frames the first pass could not render; the DWD
        # WMS renders each requested timestep on demand and may need longer
        # than the shared budget allowed on a cold cache.
        failed = [job for job in rain_jobs if not finished.get((job[0], job[1]))]
        retry = {pool.submit(fetch_rain, job): job for job in failed}
        for future in as_completed(retry):
            index, tile_index, _ = retry[future]
            try:
                source = future.result()
            except Exception:
                continue
            if not source:
                continue
            finished[index, tile_index] = source
            protected.add(source)
            if all(finished.get((index, piece_index)) for piece_index in range(len(rain["frames"][index]["tiles"]))):
                complete(index)

    partial = (any(not piece["source"] for piece in base_tiles)
               or any(not piece["source"] for frame in rain["frames"] for piece in frame["tiles"])
               or (prefs["rain_enabled"] and "rain" in wanted and not rain["frames"]))
    message = ""
    if prefs["rain_enabled"] and "rain" in wanted and rain_jobs and any(not piece["source"] for frame in rain["frames"] for piece in frame["tiles"]):
        message = "Some radar images are unavailable."
    elif prefs["rain_enabled"] and "rain" in wanted and not rain["frames"]:
        message = "Radar unavailable. Try again in a minute."
    emit({"kind": "done", "partial": partial, "message": message, "stale": stale["value"]})
    prune_cache(protected)


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
    def expired(signum, frame):
        emit({"kind": "done", "error": "Map request timed out. Please try again.",
              "partial": True, "message": ""})
        os._exit(124)
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, REQUEST_SECONDS)
    try:
        output = main(sys.argv[1:])
        # `load` streams its own lines; settings and configure answer once.
        if output is not None:
            emit(output)
    except Exception:
        emit({"kind": "done", "error": "Radar connection unavailable. Please try again.",
              "partial": True, "message": ""})
        raise SystemExit(0)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
