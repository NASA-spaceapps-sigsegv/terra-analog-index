"""Download the NASA Earthdata products for steps 03 and 04 (TAI-04).

Looks up the granules of each product in CMR (public) and downloads them with
an Earthdata Login account. Products and versions are the ones confirmed
in data/raw/README.md; the year is DATA_YEAR from tai/constants.py.

Credentials, first match wins:
  - EARTHDATA_USERNAME and EARTHDATA_PASSWORD environment variables
  - ~/.netrc (Windows: ~/_netrc) with a line
        machine urs.earthdata.nasa.gov login <user> password <pass>

Usage:
  python pipeline/fetch_earthdata.py                  # all products
  python pipeline/fetch_earthdata.py mod11c3 imerg    # some products
  python pipeline/fetch_earthdata.py --dry-run        # list URLs and sizes, no login

Files already on disk are skipped; downloads go to <file>.part and are renamed
when complete, so an interrupted run can just be started again.

Standard library only, so it runs before the geospatial stack is installed.
"""

import argparse
import http.cookiejar
import json
import netrc
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tai.constants import DATA_YEAR  # noqa: E402  (tai/constants.py has no dependencies)

RAW = ROOT / "data" / "raw"
CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.json"
URS_HOST = "urs.earthdata.nasa.gov"
CHUNK = 1 << 20


@dataclass(frozen=True)
class Product:
    short_name: str
    version: str
    start: str  # inclusive, YYYY-MM-DD
    end: str  # inclusive, YYYY-MM-DD
    dest: str  # folder under data/raw/
    suffix: str  # extension of the data file among the granule links
    expected: int  # granules expected in the window


# Every product covers the calendar year DATA_YEAR (2024: the IMERG Final run
# ends at 2025-09, so 2025 is not complete for precipitation).
START, END = f"{DATA_YEAR}-01-01", f"{DATA_YEAR}-12-31"
PRODUCTS = {
    "mod11c3": Product("MOD11C3", "061", START, END, "03_temperature", ".hdf", 12),
    "imerg": Product("GPM_3IMERGM", "07", START, END, "04_water_ice/imerg", ".HDF5", 12),
    "mod10cm": Product("MOD10CM", "61", START, END, "04_water_ice/mod10cm", ".hdf", 12),
    "mcd12c1": Product("MCD12C1", "061", START, END, "04_water_ice/mcd12c1", ".hdf", 1),
}


def granules(p: Product) -> list[tuple[str, float]]:
    """(url, size_mb) of every granule of p in its window, oldest first."""
    query = urllib.parse.urlencode(
        {
            "short_name": p.short_name,
            "version": p.version,
            "temporal": f"{p.start}T00:00:00Z,{p.end}T23:59:59Z",
            "page_size": 100,
            "sort_key": "start_date",
        }
    )
    with urllib.request.urlopen(f"{CMR_GRANULES}?{query}", timeout=60) as r:
        entries = json.load(r)["feed"]["entry"]
    out = []
    for e in entries:
        urls = [
            link["href"]
            for link in e.get("links", [])
            if link.get("rel", "").endswith("/data#")
            and link["href"].startswith("https://")
            and link["href"].endswith(p.suffix)
        ]
        if not urls:
            raise RuntimeError(f"{p.short_name}: granule {e.get('title')} has no {p.suffix} link")
        out.append((urls[0], float(e.get("granule_size") or 0)))
    return out


def credentials() -> tuple[str, str]:
    user, password = os.environ.get("EARTHDATA_USERNAME"), os.environ.get("EARTHDATA_PASSWORD")
    if user and password:
        return user, password
    for name in (".netrc", "_netrc"):
        path = Path.home() / name
        if path.exists():
            auth = netrc.netrc(path).authenticators(URS_HOST)
            if auth:
                return auth[0], auth[2]
    sys.exit(
        "No Earthdata credentials. Set EARTHDATA_USERNAME and EARTHDATA_PASSWORD, "
        f"or add 'machine {URS_HOST} login <user> password <pass>' to ~/.netrc"
    )


def opener(user: str, password: str) -> urllib.request.OpenerDirector:
    """Opener that answers the Earthdata Login challenge and keeps its cookies."""
    passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    passwords.add_password(None, f"https://{URS_HOST}", user, password)
    return urllib.request.build_opener(
        urllib.request.HTTPBasicAuthHandler(passwords),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )


def download(op: urllib.request.OpenerDirector, url: str, dest: Path) -> None:
    part = dest.with_name(dest.name + ".part")
    with op.open(url, timeout=120) as r:
        if "html" in r.headers.get("Content-Type", ""):
            raise RuntimeError(
                f"{url} returned a web page instead of data: check the password, and for "
                "GPM_3IMERGM authorize 'NASA GESDISC DATA ARCHIVE' in your Earthdata profile"
            )
        with open(part, "wb") as f:
            while chunk := r.read(CHUNK):
                f.write(chunk)
    part.replace(dest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("products", nargs="*", help=f"any of {', '.join(PRODUCTS)} (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="list what would be downloaded")
    args = parser.parse_args()
    if unknown := set(args.products) - set(PRODUCTS):
        parser.error(f"unknown product {', '.join(sorted(unknown))}; choose from {', '.join(PRODUCTS)}")
    names = args.products or list(PRODUCTS)

    op = None if args.dry_run else opener(*credentials())
    failed = 0
    for name in names:
        p = PRODUCTS[name]
        found = granules(p)
        total = sum(size for _, size in found)
        print(f"{p.short_name} v{p.version} {p.start}..{p.end}: {len(found)} files, {total:,.0f} MB")
        if len(found) != p.expected:
            print(f"  warning: expected {p.expected} files")
        folder = RAW / p.dest
        for url, size in found:
            dest = folder / url.rsplit("/", 1)[1]
            if args.dry_run:
                print(f"  {size:8.1f} MB  {url}")
                continue
            if dest.exists():
                print(f"  have {dest.name}")
                continue
            folder.mkdir(parents=True, exist_ok=True)
            print(f"  downloading {dest.name} ({size:.0f} MB)", flush=True)
            try:
                download(op, url, dest)
            except Exception as e:  # keep going: the next run retries what failed
                failed += 1
                print(f"  FAILED {dest.name}: {e}", file=sys.stderr)
    if failed:
        sys.exit(f"{failed} downloads failed; run again to retry them")


if __name__ == "__main__":
    main()
