import traceback

from flask import Flask, jsonify, render_template, request

import analyzer
import sec_client


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


def _years(value) -> int:
    try:
        years = int(value or 10)
    except (TypeError, ValueError):
        years = 10
    return max(5, min(years, 15))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8866, debug=True)
