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
ALPHAVANTAGE_API_KEY = os.environ.get("ALPHAVANTAGE_API_KEY")

SEC_HEADERS = {
    "User-Agent": SEC_USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json,text/plain,*/*",
}

MARKET_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/market-activity/stocks",
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


def fetch_alpha_vantage_fundamentals(ticker: str) -> dict[str, Any] | None:
    if not ALPHAVANTAGE_API_KEY:
        return None

    symbol = canonical_ticker(ticker)
    try:
        overview_url = (
            "https://www.alphavantage.co/query?function=OVERVIEW"
            f"&symbol={symbol}&apikey={ALPHAVANTAGE_API_KEY}&datatype=json"
        )
        estimates_url = (
            "https://www.alphavantage.co/query?function=EARNINGS_ESTIMATES"
            f"&symbol={symbol}&apikey={ALPHAVANTAGE_API_KEY}&datatype=json"
        )
        overview = _get_json(overview_url, ttl_seconds=12 * 3600, headers=MARKET_HEADERS)
        time.sleep(1.1)
        estimates = _get_json(estimates_url, ttl_seconds=12 * 3600, headers=MARKET_HEADERS)
    except requests.RequestException:
        return None

    if not _alpha_payload_ok(overview):
        overview = None
    if not _alpha_payload_ok(estimates):
        estimates = None
    if not overview and not estimates:
        return None

    annual_estimates = []
    for row in (estimates or {}).get("estimates", []):
        if str(row.get("horizon", "")).lower() != "fiscal year":
            continue
        annual_estimates.append(
            {
                "date": row.get("date"),
                "eps_estimate_average": _safe_float(row.get("eps_estimate_average")),
                "eps_estimate_high": _safe_float(row.get("eps_estimate_high")),
                "eps_estimate_low": _safe_float(row.get("eps_estimate_low")),
                "eps_estimate_analyst_count": _safe_float(row.get("eps_estimate_analyst_count")),
                "revenue_estimate_average": _safe_float(row.get("revenue_estimate_average")),
                "revenue_estimate_high": _safe_float(row.get("revenue_estimate_high")),
                "revenue_estimate_low": _safe_float(row.get("revenue_estimate_low")),
                "revenue_estimate_analyst_count": _safe_float(row.get("revenue_estimate_analyst_count")),
            }
        )
    annual_estimates.sort(key=lambda item: item.get("date") or "")

    overview = overview or {}
    return {
        "source": "alpha_vantage",
        "overview": {
            "pe_ratio": _safe_float(overview.get("PERatio")),
            "trailing_pe": _safe_float(overview.get("TrailingPE")),
            "forward_pe": _safe_float(overview.get("ForwardPE")),
            "peg_ratio": _safe_float(overview.get("PEGRatio")),
            "eps": _safe_float(overview.get("EPS") or overview.get("DilutedEPSTTM")),
            "quarterly_earnings_growth_yoy": _safe_float(overview.get("QuarterlyEarningsGrowthYOY")),
            "quarterly_revenue_growth_yoy": _safe_float(overview.get("QuarterlyRevenueGrowthYOY")),
            "analyst_target_price": _safe_float(overview.get("AnalystTargetPrice")),
        },
        "annual_estimates": annual_estimates,
    }


def _alpha_payload_ok(payload: Any) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    if payload.get("Note") or payload.get("Information") or payload.get("Error Message"):
        return False
    return True

def fetch_market_data(ticker: str) -> dict[str, Any] | None:
    normalized = normalize_ticker(ticker)
    market_data: dict[str, Any] = {"ticker": normalized, "sources": []}

    nasdaq_data = _fetch_nasdaq_market_data(normalized)
    if nasdaq_data:
        market_data.update({key: value for key, value in nasdaq_data.items() if value is not None})
        market_data["sources"].append("nasdaq")

    if not market_data.get("price"):
        yahoo_data = _fetch_yahoo_chart_price(normalized)
        if yahoo_data:
            market_data.update({key: value for key, value in yahoo_data.items() if value is not None})
            market_data["sources"].append("yahoo_chart")

    if not market_data.get("price"):
        stooq_data = _fetch_stooq_price(normalized)
        if stooq_data:
            market_data.update({key: value for key, value in stooq_data.items() if value is not None})
            market_data["sources"].append("stooq")

    if market_data.get("market_cap") and market_data.get("price") and not market_data.get("shares_outstanding"):
        market_data["shares_outstanding"] = market_data["market_cap"] / market_data["price"]
        market_data["shares_source"] = "market_cap_divided_by_price"

    if not market_data.get("price") and not market_data.get("market_cap"):
        return None
    market_data["source"] = "+".join(market_data["sources"])
    return market_data


def fetch_latest_price(ticker: str) -> dict[str, Any] | None:
    market_data = fetch_market_data(ticker)
    if not market_data or not market_data.get("price"):
        return None
    return {
        "price": market_data.get("price"),
        "date": market_data.get("date"),
        "source": market_data.get("source"),
    }


def _fetch_nasdaq_market_data(ticker: str) -> dict[str, Any] | None:
    symbol = _nasdaq_symbol(ticker)
    output: dict[str, Any] = {}
    try:
        info_url = f"https://api.nasdaq.com/api/quote/{symbol}/info?assetclass=stocks"
        info = _get_json(info_url, ttl_seconds=15 * 60, headers=MARKET_HEADERS)
        info_data = info.get("data") or {}
        primary = info_data.get("primaryData") or {}
        price = _parse_market_number(primary.get("lastSalePrice"))
        if price:
            output.update(
                {
                    "price": price,
                    "date": primary.get("lastTradeTimestamp"),
                    "currency": primary.get("currency") or "USD",
                    "market_status": info_data.get("marketStatus"),
                    "company_name": info_data.get("companyName"),
                    "price_source": "nasdaq",
                }
            )

        summary_url = f"https://api.nasdaq.com/api/quote/{symbol}/summary?assetclass=stocks"
        summary = _get_json(summary_url, ttl_seconds=30 * 60, headers=MARKET_HEADERS)
        summary_data = ((summary.get("data") or {}).get("summaryData") or {})
        market_cap = _parse_market_number((summary_data.get("MarketCap") or {}).get("value"))
        previous_close = _parse_market_number((summary_data.get("PreviousClose") or {}).get("value"))
        if market_cap:
            output["market_cap"] = market_cap
            output["market_cap_source"] = "nasdaq"
        if previous_close and not output.get("price"):
            output["price"] = previous_close
            output["price_source"] = "nasdaq_previous_close"
        return output or None
    except requests.RequestException:
        return None
    except (KeyError, TypeError, ValueError):
        return None


def _fetch_yahoo_chart_price(ticker: str) -> dict[str, Any] | None:
    symbol = canonical_ticker(ticker)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"
    try:
        payload = _get_json(url, ttl_seconds=15 * 60, headers=MARKET_HEADERS)
        result = (payload.get("chart", {}).get("result") or [None])[0]
        meta = (result or {}).get("meta") or {}
        price = _safe_float(meta.get("regularMarketPrice"))
        if not price:
            price = _safe_float(meta.get("chartPreviousClose"))
        if not price:
            return None
        return {
            "price": price,
            "date": meta.get("regularMarketTime"),
            "currency": meta.get("currency") or "USD",
            "company_name": meta.get("longName") or meta.get("shortName"),
            "price_source": "yahoo_chart",
        }
    except requests.RequestException:
        return None
    except (KeyError, TypeError, ValueError):
        return None


def _fetch_stooq_price(ticker: str) -> dict[str, Any] | None:
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
        "price_source": "stooq",
    }


def _nasdaq_symbol(ticker: str) -> str:
    return normalize_ticker(ticker).replace("-", ".")


def _parse_market_number(value: Any) -> float | None:
    if value in (None, "", "N/A", "--"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("$", "").replace(",", "").replace("%", "")
    if not text or text.upper() in {"N/A", "NA", "--"}:
        return None
    multiplier = 1.0
    suffix = text[-1].upper()
    if suffix in {"T", "B", "M", "K"}:
        multiplier = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}[suffix]
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


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
