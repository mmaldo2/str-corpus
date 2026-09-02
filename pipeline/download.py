"""Download static.case.law volume zips for the target jurisdictions.

Volume-level archives only (never per-case JSON) — kinder to the host and
faster for us. Resumable: a volume already present with the expected size is
skipped, so re-running after an interruption is a no-op for completed files.
Every completed download appends a manifest row; the manifest is the
reproducibility record of exactly what was ingested.

Usage:
    python pipeline/download.py [--dry-run] [--concurrency 4]
"""

import argparse
import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

BASE = "https://static.case.law"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from corpus_engine.domain import load_domain  # noqa: E402
_DOMAIN = load_domain()
TARGET_JURISDICTIONS = set(_DOMAIN.jurisdictions)
TARGET_REPORTER_SLUGS = set(_DOMAIN.reporter_slugs)
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
MANIFEST = RAW_DIR / "manifest.jsonl"

_manifest_lock = threading.Lock()
_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def fetch_json(client: httpx.Client, url: str):
    for attempt in range(5):
        try:
            r = client.get(url)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            if attempt == 4:
                raise
            time.sleep(2**attempt)
            log(f"  retry {attempt + 1} for {url}: {e}")


def select_reporters(client: httpx.Client) -> list[dict]:
    reporters = fetch_json(client, f"{BASE}/ReportersMetadata.json")
    return sorted(
        (
            r
            for r in reporters
            if r["slug"] in TARGET_REPORTER_SLUGS
            or any(j["name"] in TARGET_JURISDICTIONS for j in r["jurisdictions"])
        ),
        key=lambda r: r["slug"],
    )


def manifest_done() -> set[str]:
    done = set()
    if MANIFEST.exists():
        with MANIFEST.open(encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    done.add(row["key"])
                except (json.JSONDecodeError, KeyError):
                    continue
    return done


def download_volume(client: httpx.Client, slug: str, vol: str) -> dict:
    url = f"{BASE}/{slug}/{vol}.zip"
    dest = RAW_DIR / slug / f"{vol}.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".zip.part")

    # Trust a completed file already on disk (e.g. manifest rows lost in a
    # crash): hash it locally instead of re-downloading.
    if dest.exists() and dest.stat().st_size > 0:
        sha = hashlib.sha256()
        with dest.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                sha.update(chunk)
        return {
            "key": f"{slug}/{vol}", "url": url, "bytes": dest.stat().st_size,
            "sha256": sha.hexdigest(), "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": "already-on-disk",
        }

    for attempt in range(5):
        try:
            sha = hashlib.sha256()
            with client.stream("GET", url) as r:
                r.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        f.write(chunk)
                        sha.update(chunk)
            # Windows: AV can hold a transient lock on the .part file
            for rename_try in range(6):
                try:
                    tmp.replace(dest)
                    break
                except (PermissionError, FileNotFoundError):
                    # AV can hold a transient lock on, or briefly quarantine,
                    # the .part file. If the destination already landed, the
                    # rename raced with itself and we are done.
                    if dest.exists() and dest.stat().st_size > 0:
                        break
                    if rename_try == 5:
                        raise
                    time.sleep(1 + rename_try)
            return {
                "key": f"{slug}/{vol}",
                "url": url,
                "bytes": dest.stat().st_size,
                "sha256": sha.hexdigest(),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"key": f"{slug}/{vol}", "url": url, "error": "404"}
            time.sleep(2 + 2**attempt)
        except httpx.HTTPError:
            time.sleep(2 + 2**attempt)
    return {"key": f"{slug}/{vol}", "url": url, "error": "failed-after-retries"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "str-corpus-research/0.1 (legal-history pipeline; polite bulk fetch)"}
    with httpx.Client(headers=headers, timeout=120, follow_redirects=True) as client:
        reporters = select_reporters(client)
        log(f"{len(reporters)} reporters cover {sorted(TARGET_JURISDICTIONS)} + {sorted(TARGET_REPORTER_SLUGS)}")

        work: list[tuple[str, str]] = []
        for rep in reporters:
            slug = rep["slug"]
            vols = fetch_json(client, f"{BASE}/{slug}/VolumesMetadata.json")
            for v in vols:
                work.append((slug, v["volume_number"]))
        log(f"{len(work)} volumes total")

        done = manifest_done()
        todo = [(s, v) for s, v in work if f"{s}/{v}" not in done]
        log(f"{len(done)} already in manifest; {len(todo)} to download")
        if args.dry_run:
            return 0

        errors = 0
        with MANIFEST.open("a", encoding="utf-8") as mf, ThreadPoolExecutor(
            max_workers=args.concurrency
        ) as pool:
            futures = {
                pool.submit(download_volume, client, s, v): (s, v) for s, v in todo
            }
            for i, fut in enumerate(as_completed(futures), 1):
                try:
                    row = fut.result()
                except Exception as e:  # one volume must not end the run
                    s, v = futures[fut]
                    row = {"key": f"{s}/{v}", "url": f"{BASE}/{s}/{v}.zip",
                           "error": f"{type(e).__name__}: {e}"[:200]}
                with _manifest_lock:
                    mf.write(json.dumps(row) + "\n")
                    mf.flush()
                if "error" in row:
                    errors += 1
                    log(f"[{i}/{len(todo)}] ERROR {row['key']}: {row['error']}")
                elif i % 100 == 0 or i == len(todo):
                    log(f"[{i}/{len(todo)}] {row['key']} ({row['bytes']:,} B)")

        log(f"done; {errors} errors")
        return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
