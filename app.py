import traceback

from flask import Flask, jsonify, render_template, request

import analyzer
import sec_client
from valuation.reverse_dcf import calculate_reverse_dcf


app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "status": "healthy"})


@app.route("/api/analyze", methods=["GET", "POST"])
def analyze():
    try:
        payload = request.get_json(silent=True) or {}
        ticker = payload.get("ticker") or request.args.get("ticker")
        years = _years(payload.get("years") or request.args.get("years"))
        if not ticker:
            return jsonify({"ok": False, "error": "Vui lòng nhập ticker, ví dụ AAPL."}), 400
        result = analyzer.analyze_ticker(ticker, years=years)
        return jsonify({"ok": True, "result": result})
    except sec_client.DataError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"Lỗi khi phân tích: {exc}"}), 500


@app.route("/api/compare", methods=["GET", "POST"])
def compare():
    try:
        payload = request.get_json(silent=True) or {}
        ticker_a = payload.get("ticker_a") or payload.get("ticker1") or request.args.get("ticker_a") or request.args.get("ticker1")
        ticker_b = payload.get("ticker_b") or payload.get("ticker2") or request.args.get("ticker_b") or request.args.get("ticker2")
        years = _years(payload.get("years") or request.args.get("years"))
        if not ticker_a or not ticker_b:
            return jsonify({"ok": False, "error": "Vui lòng nhập đủ 2 ticker để so sánh."}), 400
        if sec_client.canonical_ticker(ticker_a) == sec_client.canonical_ticker(ticker_b):
            return jsonify({"ok": False, "error": "Hai ticker phải khác nhau."}), 400
        result = analyzer.compare_tickers(ticker_a, ticker_b, years=years)
        return jsonify({"ok": True, "result": result})
    except sec_client.DataError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"Lỗi khi so sánh: {exc}"}), 500

@app.route("/api/reverse-dcf", methods=["GET", "POST"])
def reverse_dcf():
    try:
        payload = request.get_json(silent=True) or {}
        ticker = payload.get("ticker") or request.args.get("ticker")
        request_data = {**request.args.to_dict(), **payload}
        input_data, defaults, data_warnings = _reverse_dcf_input(ticker, request_data)
        result = calculate_reverse_dcf(input_data)
        result["defaults"] = defaults
        result["warnings"] = data_warnings + result.get("warnings", [])
        return jsonify({"ok": True, "result": result})
    except sec_client.DataError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"Lỗi khi tính Reverse DCF: {exc}"}), 500


def _years(value) -> int:
    try:
        years = int(value or 10)
    except (TypeError, ValueError):
        years = 10
    return max(5, min(years, 15))

def _reverse_dcf_input(ticker: str | None, payload: dict) -> tuple[dict, dict, list[str]]:
    defaults: dict = {}
    warnings: list[str] = []
    if ticker:
        analysis = analyzer.analyze_ticker(ticker, years=10)
        latest = (analysis.get("annuals") or [{}])[-1]
        market_data = analysis.get("market_data") or analysis.get("price") or {}
        defaults = {
            "ticker": analysis["company"].get("ticker"),
            "company_name": analysis["company"].get("name"),
            "market_cap": analysis.get("summary", {}).get("market_cap"),
            "share_price": market_data.get("price"),
            "shares_outstanding": analysis.get("shares_outstanding"),
            "total_debt": latest.get("debt"),
            "cash_and_equivalents": latest.get("cash"),
            "current_fcf": latest.get("free_cash_flow"),
        }
        missing = [label for label, key in (("market cap", "market_cap"), ("debt", "total_debt"), ("cash", "cash_and_equivalents"), ("FCF", "current_fcf")) if defaults.get(key) is None]
        if missing:
            warnings.append("Không tự lấy được " + ", ".join(missing) + "; vui lòng nhập thủ công nếu cần.")

    input_data = {
        "ticker": _first_value(payload, defaults, "ticker"),
        "company_name": _first_value(payload, defaults, "company_name", "companyName"),
        "market_cap": _first_value(payload, defaults, "market_cap", "marketCap"),
        "share_price": _first_value(payload, defaults, "share_price", "sharePrice"),
        "shares_outstanding": _first_value(payload, defaults, "shares_outstanding", "sharesOutstanding"),
        "total_debt": _first_value(payload, defaults, "total_debt", "totalDebt"),
        "cash_and_equivalents": _first_value(payload, defaults, "cash_and_equivalents", "cashAndEquivalents"),
        "current_fcf": _first_value(payload, defaults, "current_fcf", "currentFcf"),
        "projection_years": _first_value(payload, defaults, "projection_years", "projectionYears") or 10,
        "discount_rate": _first_value(payload, defaults, "discount_rate", "discountRate") or 0.10,
        "terminal_growth_rate": _first_value(payload, defaults, "terminal_growth_rate", "terminalGrowthRate") or 0.025,
    }
    return input_data, defaults, warnings

def _first_value(payload: dict, defaults: dict, snake_key: str, camel_key: str | None = None):
    for key in (snake_key, camel_key):
        if key and key in payload and payload[key] not in (None, ""):
            return payload[key]
    return defaults.get(snake_key)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8866, debug=True)
