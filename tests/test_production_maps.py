import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zlib

import image_validation
import radar
from test_radar import png


def chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)


class ProductionMapTests(unittest.TestCase):
    def test_png_rejects_fake_headers_invalid_raster_and_decompression_bombs(self):
        bad = (radar.PNG + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 256, 256)
               + bytes(13) + bytes(4) + b"IEND" + bytes(4))
        self.assertFalse(radar.valid_png(bad))
        header = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        for raw in (b"\x05" + bytes(4), bytes(1_000_000)):
            data = radar.PNG + header + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
            with self.assertRaises(ValueError):
                image_validation.png_size(data)

    def test_palette_and_adam7_images_remain_supported(self):
        palette = chunk(b"PLTE", b"\x00\x00\x00\xff\xff\xff")
        for depth, colour, interlace, table in ((1, 3, 0, palette), (8, 0, 1, b"")):
            data = (radar.PNG + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, depth, colour, 0, 0, interlace))
                    + table + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"IEND", b""))
            self.assertEqual(image_validation.png_size(data), (1, 1))

    def test_radar_cache_expires_but_serves_offline_until_pruned(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(radar, "CACHE", Path(directory)):
            url = radar.RADAR_HOST + "/v2/radar/sample/512/6/32/32/2/1_0.png"
            path = Path(directory) / "radar-" / (hashlib.sha256(url.encode()).hexdigest() + ".png")
            radar.save_bytes(path, png())
            os.utime(path, (time.time() - 2 * 86400,) * 2)
            self.assertEqual(radar.tile(url, network=False), path.as_uri())
            radar.prune_cache()
            self.assertFalse(path.exists())
        with tempfile.TemporaryDirectory() as directory, patch.object(radar, "CACHE", Path(directory)):
            fresh = Path(directory) / "radar-" / "fresh.png"
            base = Path(directory) / "osm-" / "base.png"
            radar.save_bytes(fresh, png())
            radar.save_bytes(base, png())
            with patch.object(radar, "MAX_CACHE_BYTES", len(png()) + 1):
                radar.prune_cache({base})
                self.assertTrue(base.exists())
                self.assertFalse(fresh.exists())

    def test_slow_drip_shares_the_total_budget_instead_of_resetting_socket_timeout(self):
        clock = [0.0]
        class SlowResponse:
            def read1(self, count):
                clock[0] += 2
                return b"x"
            read = read1
        with patch.object(radar.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(radar, "REQUEST_SECONDS", 4), radar.request_budget():
            budget = radar.REQUEST_SECONDS
            with self.assertRaises(TimeoutError):
                radar.read_response(SlowResponse(), 100)
        self.assertEqual(clock[0], budget)

    def test_cli_deadline_stops_a_completely_stalled_request_with_valid_json(self):
        code = ("import radar,time;radar.REQUEST_SECONDS=0.1;"
                "radar.bounded_cli(lambda:time.sleep(10),lambda:{'frames':[]})")
        result = subprocess.run([sys.executable, "-B", "-c", code],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 124)
        self.assertIn("timed out", json.loads(result.stdout)["error"])
        self.assertTrue(json.loads(result.stdout)["stale"])


if __name__ == "__main__":
    unittest.main()
