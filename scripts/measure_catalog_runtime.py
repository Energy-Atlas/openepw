"""Measure the hosted server's catalog costs: memory and time at start, first page, browsing.

Read-only: it uses an existing data root (default ``.local/openepw``) and changes nothing on
disk. Memory is the process working set on Windows and the resident set (VmRSS/VmHWM) on
Linux. Two parts:

    python scripts/measure_catalog_runtime.py memory  [--data-root DIR] [--rounds 4]
    python scripts/measure_catalog_runtime.py http    [--port 18765]

``memory`` runs the app in-process (TestClient): service, catalog index, app start, then
rounds of map loads, map hover lookups and product lists, printing memory after each step.
``http`` launches ``openepw serve`` on a local port and times the first page's requests
(start to /health, chat session, first and later /v1/catalog/map, hover lookups) and the
map's size as sent. See docs/validation/2026-10-13-catalog-memory.md for earlier results.
"""

from __future__ import annotations

import argparse
import gc
import random
import subprocess
import sys
import time
from pathlib import Path


def memory_mb() -> tuple[float, float]:
    """(current, peak) resident or working-set memory of this process, in MB."""
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as w

        class Counters(ctypes.Structure):
            _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]

        kernel, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), w.DWORD]
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return counters.WorkingSetSize / 2**20, counters.PeakWorkingSetSize / 2**20
    values = {}
    for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
        name, _, rest = line.partition(":")
        if name in ("VmRSS", "VmHWM"):
            values[name] = int(rest.split()[0]) / 1024
    return values.get("VmRSS", 0.0), values.get("VmHWM", 0.0)


def report(label: str, started: float) -> None:
    gc.collect()
    current, peak = memory_mb()
    print(f"{label:44} memory {current:7.0f} MB  peak {peak:7.0f} MB  t={time.perf_counter() - started:6.1f} s",
          flush=True)


def measure_memory(data_root: Path, rounds: int) -> None:
    import logging

    started = time.perf_counter()
    report("python", started)
    from fastapi.testclient import TestClient

    from openepw.api.app import create_app
    from openepw.chat.coordinator import OfflineParser
    from openepw.config import RuntimeConfig
    from openepw.service import WeatherService

    logging.disable(logging.INFO)
    report("imports", started)
    service = WeatherService(RuntimeConfig.load(data_root=data_root))
    service.catalog_store.active()
    report("catalog index loaded", started)
    random.seed(1)
    with TestClient(create_app(service, chat_parser=OfflineParser())) as client:
        report("app started (warm-up included)", started)
        for round_ in range(rounds):
            for _ in range(5):
                client.get("/v1/catalog/map")
            report(f"round {round_}: 5 x catalog map", started)
            for _ in range(150):
                client.get("/v1/catalog/point", params={"lat": round(random.uniform(-60, 70), 3),
                                                        "lon": round(random.uniform(-180, 180), 3)})
            report(f"round {round_}: 150 x map hover lookup", started)
            for _ in range(10):
                points = [{"lat": random.uniform(-60, 70), "lon": random.uniform(-180, 180)}
                          for _ in range(random.choice([1, 5, 25]))]
                service.product_offers(points, years=[2018])
            report(f"round {round_}: 10 x product list", started)


def measure_http(port: int, data_root: Path) -> None:
    import httpx

    started = time.perf_counter()
    server = subprocess.Popen([sys.executable, "-m", "openepw.cli.main", "--data-root", str(data_root),
                               "serve", "--port", str(port)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(timeout=120) as client:
            while True:
                try:
                    if client.get(base + "/health").status_code == 200:
                        break
                except httpx.TransportError:
                    time.sleep(0.05)
            print(f"{'launch -> /health 200':44} {time.perf_counter() - started:6.2f} s")

            def timed(label, method, path, **options):
                begun = time.perf_counter()
                response = client.request(method, base + path, **options)
                print(f"{label:44} {time.perf_counter() - begun:6.2f} s  {response.status_code}  "
                      f"{len(response.content) / 1e6:6.2f} MB  {response.headers.get('content-encoding', '-')}")
                return response

            timed("POST /v1/chat/sessions", "POST", "/v1/chat/sessions")
            first = timed("GET /v1/catalog/map (first)", "GET", "/v1/catalog/map")
            timed("GET /v1/catalog/map (second)", "GET", "/v1/catalog/map")
            etag = first.headers.get("etag")
            if etag:
                timed("GET /v1/catalog/map (If-None-Match)", "GET", "/v1/catalog/map",
                      headers={"If-None-Match": etag})
            timed("GET /v1/catalog/point (first)", "GET", "/v1/catalog/point", params={"lat": 1.29, "lon": 103.85})
            timed("GET /v1/catalog/point (another)", "GET", "/v1/catalog/point", params={"lat": 42.44, "lon": -76.5})
            raw = client.get(base + "/v1/catalog/map", headers={"Accept-Encoding": "identity"}).content
            sent = len(first.content) if first.headers.get("content-encoding") != "gzip" else int(
                first.headers.get("content-length") or 0)
            print(f"map JSON {len(raw) / 1e6:.2f} MB; sent {sent / 1e6:.2f} MB")
    finally:
        server.terminate()
        server.wait(timeout=30)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("part", choices=["memory", "http"])
    parser.add_argument("--data-root", type=Path, default=Path(".local/openepw"))
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    if args.part == "memory":
        measure_memory(args.data_root, args.rounds)
    else:
        measure_http(args.port, args.data_root)


if __name__ == "__main__":
    main()
