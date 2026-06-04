import csv
import hashlib
import json
import os
import time
from datetime import datetime
from io import StringIO
from typing import Any

import requests


BASE_DIR = os.path.dirname(__file__)
CACHE_DIR = os.path.join(BASE_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "us-stock-buffett-app/1.0 contact@example.com",
)

SEC_HEADERS = {
    "User-Agent": SEC_USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json,text/plain,*/*",
}

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}


class DataError(RuntimeError):
    pass


def _cache_path(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return os.path.join(CACHE_DIR, f"{digest}.json")


def _read_cache(key: str, ttl_seconds: int) -> Any | None:
    path = _cache_path(key)
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
        if time.time() - payload.get("saved_at", 0) <= ttl_seconds:
            return payload.get("data")
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return None


def _write_cache(key: str, data: Any) -> None:
    path = _cache_path(key)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump({"saved_at": time.time(), "data": data}, file, ensure_ascii=False)
    os.replace(tmp, path)


def _get_json(url: str, ttl_seconds: int = 24 * 3600, headers: dict[str, str] | None = None) -> Any:
    cached = _read_cache(url, ttl_seconds)
    if cached is not None:
        return cached

    response = requests.get(url, headers=headers or SEC_HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()
    _write_cache(url, data)
    time.sleep(0.12)
    return data


def _get_text(url: str, ttl_seconds: int = 6 * 3600) -> str:
    cached = _read_cache(url, ttl_seconds)
    if cached is not None:
        return cached

    response = requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=20)
    response.raise_for_status()
    text = response.text
    _write_cache(url, text)
    return text


def lookup_company(ticker: str) -> dict[str, Any]:
    normalized = normalize_ticker(ticker)
    aliases = _ticker_aliases(normalized)
    url = "https://www.sec.gov/files/company_tickers.json"
    companies = _get_json(url, ttl_seconds=7 * 24 * 3600)
    for row in companies.values():
        row_ticker = str(row.get("ticker", "")).upper()
        if row_ticker in aliases:
            cik = int(row["cik_str"])
            return {
                "ticker": row_ticker,
                "cik": cik,
                "cik_padded": f"{cik:010d}",
                "name": row.get("title", normalized),
            }
    raise DataError(f"Không tìm thấy mã {normalized} trong SEC company tickers.")


def fetch_company_facts(cik_padded: str) -> dict[str, Any]:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    return _get_json(url, ttl_seconds=24 * 3600)


def fetch_submissions(cik_padded: str) -> dict[str, Any] | None:
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    try:
        return _get_json(url, ttl_seconds=24 * 3600)
    except requests.RequestException:
        return None


def fetch_latest_price(ticker: str) -> dict[str, Any] | None:
    symbol = ticker.lower().replace("-", ".")
    url = f"https://stooq.com/q/l/?s={symbol}.us&i=d"
    try:
        text = _get_text(url, ttl_seconds=30 * 60)
    except requests.RequestException:
        return None

    rows = list(csv.DictReader(StringIO(text)))
    if not rows:
        return None
    row = rows[0]
    close = row.get("Close")
    if not close or close == "N/D":
        return None
    try:
        price = float(close)
    except ValueError:
        return None
    return {
        "price": price,
        "date": row.get("Date"),
        "source": "stooq",
    }


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper().replace(" ", "").replace("/", ".")


def canonical_ticker(ticker: str) -> str:
    return normalize_ticker(ticker).replace(".", "-")


def _ticker_aliases(ticker: str) -> set[str]:
    return {ticker, ticker.replace(".", "-"), ticker.replace("-", ".")}


def latest_period_from_facts(facts: dict[str, Any]) -> str | None:
    ends: list[str] = []
    for namespace in facts.get("facts", {}).values():
        for concept in namespace.values():
            for unit_values in concept.get("units", {}).values():
                for item in unit_values:
                    if item.get("form") in ANNUAL_FORMS and item.get("end"):
                        ends.append(item["end"])
    return max(ends) if ends else None


def extract_annual_series(
    facts: dict[str, Any],
    concepts: list[tuple[str, str]],
    units: tuple[str, ...] = ("USD",),
    duration: bool = True,
) -> dict[int, float]:
    output: dict[int, float] = {}
    for namespace, concept_name in concepts:
        concept = facts.get("facts", {}).get(namespace, {}).get(concept_name)
        if not concept:
            continue
        for unit in units:
            rows = concept.get("units", {}).get(unit, [])
            candidates_by_year: dict[int, list[dict[str, Any]]] = {}
            for row in rows:
                if not _is_annual_row(row, duration=duration):
                    continue
                fiscal_year = _safe_int(row.get("fy"))
                value = _safe_float(row.get("val"))
                if fiscal_year is None or value is None:
                    continue
                candidates_by_year.setdefault(fiscal_year, []).append(row)
            for fiscal_year, candidates in candidates_by_year.items():
                if fiscal_year in output:
                    continue
                best = max(candidates, key=_fact_score)
                value = _safe_float(best.get("val"))
                if value is not None:
                    output[fiscal_year] = value
    return dict(sorted(output.items()))


def extract_latest_series_value(
    facts: dict[str, Any],
    concepts: list[tuple[str, str]],
    units: tuple[str, ...] = ("shares",),
) -> float | None:
    candidates: list[dict[str, Any]] = []
    for namespace, concept_name in concepts:
        concept = facts.get("facts", {}).get(namespace, {}).get(concept_name)
        if not concept:
            continue
        for unit in units:
            for row in concept.get("units", {}).get(unit, []):
                value = _safe_float(row.get("val"))
                if value is None:
                    continue
                candidates.append(row)
    if not candidates:
        return None
    best = max(candidates, key=_fact_score)
    return _safe_float(best.get("val"))


def _is_annual_row(row: dict[str, Any], duration: bool) -> bool:
    if row.get("form") not in ANNUAL_FORMS:
        return False
    if row.get("fp") and row.get("fp") != "FY":
        return False
    if duration:
        start = row.get("start")
        end = row.get("end")
        if not start or not end:
            return False
        days = _days_between(start, end)
        return days is None or 300 <= days <= 450
    return bool(row.get("end"))


def _fact_score(row: dict[str, Any]) -> tuple[str, str, int, int]:
    form_score = 1 if str(row.get("form", "")).endswith("/A") else 0
    frame_score = 1 if row.get("frame") else 0
    filed = row.get("filed") or ""
    end = row.get("end") or ""
    return filed, end, frame_score, form_score


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _days_between(start: str, end: str) -> int | None:
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    return (end_date - start_date).days
