"""Recorded depth snapshots shared by quote replay and spread calibration."""
import csv
import fcntl
import io
import gzip
import json
from decimal import Decimal
from pathlib import Path


def resolve_quote_path(path=None):
    from .config import PROJECT_ROOT, QUOTE_DATA_DIR
    if path is None or str(Path(path)) == "data/quotes":
        path = QUOTE_DATA_DIR
    path = Path(path).expanduser()
    return path if path.is_absolute() else Path(PROJECT_ROOT) / path


def read_quotes(path, symbol):
    if not path:
        raise ValueError("A quote file or directory is required")
    path = resolve_quote_path(path)
    files = sorted(path.glob("*.csv.gz")) + sorted(path.glob("*.csv")) if path.is_dir() else [path]
    if not files or any(not p.is_file() for p in files):
        raise ValueError(
            f"No recorded quotes found at {path}. The backend records quotes while running "
            "and connected to the exchanges. Allow at least 60 minutes of recording, "
            "then select dates within that recorded period. Past order books cannot be "
            "downloaded here; use Candles for earlier dates."
        )
    rows = {}
    for file in files:
        with file.open("rb") as source:
            fcntl.flock(source, fcntl.LOCK_SH)
            snapshot = source.read()
        contents = gzip.decompress(snapshot) if file.suffix == ".gz" else snapshot
        with io.StringIO(contents.decode("utf-8"), newline="") as stream:
            for raw in csv.DictReader(stream):
                if raw.get("market") != symbol:
                    continue
                ts = int(raw["ts_ms"])
                books = {}
                fresh = True
                for venue in ("bs", "bn", "eurusdt"):
                    received = int(raw[f"{venue}_received_ts_ms"])
                    fresh &= 0 <= ts - received <= 5000
                    book = {side: {Decimal(p): Decimal(q) for p, q in json.loads(raw[f"{venue}_{side}"])}
                            for side in ("bids", "asks")}
                    if any(not book[side] for side in book):
                        raise ValueError(f"Empty {venue} book at {ts}")
                    if any(not p.is_finite() or not q.is_finite() or p <= 0 or q <= 0
                           for side in book.values() for p, q in side.items()):
                        raise ValueError(f"Invalid {venue} level at {ts}")
                    if max(book["bids"]) > min(book["asks"]):
                        raise ValueError(f"Crossed {venue} book at {ts}")
                    books[venue] = book
                fx = books["eurusdt"]
                books["b"] = {
                    "bids": {p / min(fx["asks"]): q for p, q in books["bn"]["bids"].items()},
                    "asks": {p / max(fx["bids"]): q for p, q in books["bn"]["asks"].items()},
                }
                rows[ts] = {"ts": ts, "a": books["bs"], "b": books["b"], "fresh": fresh}
    return [rows[ts] for ts in sorted(rows)]


def midpoint(book):
    return float((max(book["bids"]) + min(book["asks"])) / 2)


def vwap(book, side, amount):
    levels = book["asks" if side == "buy" else "bids"]
    remaining, cost = amount, 0.0
    for price in sorted(levels, reverse=side == "sell"):
        taken = min(remaining, float(levels[price]))
        cost += taken * float(price)
        remaining -= taken
        if remaining <= 1e-10:
            return cost / amount
    return None
