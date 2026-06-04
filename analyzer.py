from __future__ import annotations

import math
from statistics import mean, median
from typing import Any

import sec_client


REVENUE = [
    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    ("us-gaap", "SalesRevenueNet"),
    ("us-gaap", "Revenues"),
]
GROSS_PROFIT = [("us-gaap", "GrossProfit")]
OPERATING_INCOME = [("us-gaap", "OperatingIncomeLoss")]
NET_INCOME = [
    ("us-gaap", "NetIncomeLoss"),
    ("us-gaap", "ProfitLoss"),
]
ASSETS = [("us-gaap", "Assets")]
LIABILITIES = [("us-gaap", "Liabilities")]
EQUITY = [
    ("us-gaap", "StockholdersEquity"),
    ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
]
CASH = [
    ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
    ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
]
TOTAL_DEBT = [
    ("us-gaap", "DebtAndFinanceLeaseObligations"),
]
LONG_TERM_DEBT = [
    ("us-gaap", "LongTermDebtAndFinanceLeaseObligationsCurrentAndNoncurrent"),
    ("us-gaap", "LongTermDebtAndFinanceLeaseObligations"),
    ("us-gaap", "LongTermDebt"),
]
DEBT_PARTS = [
    ("us-gaap", "ShortTermBorrowings"),
    ("us-gaap", "ShortTermDebt"),
    ("us-gaap", "LongTermDebtCurrent"),
    ("us-gaap", "LongTermDebtNoncurrent"),
    ("us-gaap", "FinanceLeaseLiabilityCurrent"),
    ("us-gaap", "FinanceLeaseLiabilityNoncurrent"),
]
OPERATING_CASH_FLOW = [("us-gaap", "NetCashProvidedByUsedInOperatingActivities")]
CAPEX = [
    ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
    ("us-gaap", "PaymentsToAcquireProductiveAssets"),
]
DEPRECIATION_AMORTIZATION = [
    ("us-gaap", "DepreciationDepletionAndAmortization"),
    ("us-gaap", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment"),
    ("us-gaap", "DepreciationAmortizationAndAccretionNet"),
    ("us-gaap", "DepreciationAndAmortization"),
]
EPS_DILUTED = [("us-gaap", "EarningsPerShareDiluted")]
SHARES_DILUTED = [("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding")]
SHARES_OUTSTANDING = [("dei", "EntityCommonStockSharesOutstanding")]


def analyze_ticker(ticker: str, years: int = 10) -> dict[str, Any]:
    company = sec_client.lookup_company(ticker)
    facts = sec_client.fetch_company_facts(company["cik_padded"])
    submissions = sec_client.fetch_submissions(company["cik_padded"])
    company.update(_company_profile(submissions))

    annuals = _build_annuals(facts)
    if not annuals:
        raise sec_client.DataError(f"Không đọc được dữ liệu tài chính nhiều năm cho {company['ticker']}.")

    annuals = annuals[-years:]
    price = sec_client.fetch_latest_price(company["ticker"])
    shares_outstanding = sec_client.extract_latest_series_value(facts, SHARES_OUTSTANDING)
    if not shares_outstanding:
        shares = [row.get("diluted_shares") for row in annuals if row.get("diluted_shares")]
        shares_outstanding = shares[-1] if shares else None

    summary = _summarize(annuals, price=price, shares_outstanding=shares_outstanding)
    valuation = _estimate_intrinsic_value(annuals, price=price, shares_outstanding=shares_outstanding)
    score = _score(annuals, summary, valuation)
    narrative = _narrative(company, annuals, summary, valuation, score)

    return {
        "company": company,
        "annuals": annuals,
        "summary": summary,
        "valuation": valuation,
        "score": score,
        "narrative": narrative,
        "price": price,
        "shares_outstanding": shares_outstanding,
        "data_source": {
            "financials": "SEC Company Facts XBRL",
            "price": price["source"] if price else None,
            "latest_period_end": sec_client.latest_period_from_facts(facts),
        },
        "disclaimer": "Dữ liệu và phân tích chỉ để tham khảo, không phải khuyến nghị đầu tư.",
    }


def compare_tickers(ticker_a: str, ticker_b: str, years: int = 10) -> dict[str, Any]:
    first = analyze_ticker(ticker_a, years=years)
    second = analyze_ticker(ticker_b, years=years)
    comparison = _compare(first, second)
    return {
        "stocks": [first, second],
        "comparison": comparison,
        "disclaimer": "So sánh chỉ để tham khảo, không phải khuyến nghị mua/bán.",
    }


def _company_profile(submissions: dict[str, Any] | None) -> dict[str, Any]:
    if not submissions:
        return {}
    return {
        "sic": submissions.get("sic"),
        "sic_description": submissions.get("sicDescription"),
        "fiscal_year_end": submissions.get("fiscalYearEnd"),
        "exchanges": submissions.get("exchanges") or [],
    }


def _build_annuals(facts: dict[str, Any]) -> list[dict[str, Any]]:
    revenue = sec_client.extract_annual_series(facts, REVENUE)
    gross_profit = sec_client.extract_annual_series(facts, GROSS_PROFIT)
    operating_income = sec_client.extract_annual_series(facts, OPERATING_INCOME)
    net_income = sec_client.extract_annual_series(facts, NET_INCOME)
    assets = sec_client.extract_annual_series(facts, ASSETS, duration=False)
    liabilities = sec_client.extract_annual_series(facts, LIABILITIES, duration=False)
    equity = sec_client.extract_annual_series(facts, EQUITY, duration=False)
    cash = sec_client.extract_annual_series(facts, CASH, duration=False)
    debt = _debt_series(facts)
    operating_cash_flow = sec_client.extract_annual_series(facts, OPERATING_CASH_FLOW)
    capex = sec_client.extract_annual_series(facts, CAPEX)
    depreciation = sec_client.extract_annual_series(facts, DEPRECIATION_AMORTIZATION)
    eps = sec_client.extract_annual_series(facts, EPS_DILUTED, units=("USD/shares",))
    diluted_shares = sec_client.extract_annual_series(facts, SHARES_DILUTED, units=("shares",))

    all_years = sorted(
        set().union(
            revenue,
            gross_profit,
            operating_income,
            net_income,
            assets,
            liabilities,
            equity,
            cash,
            debt,
            operating_cash_flow,
            capex,
            depreciation,
            eps,
            diluted_shares,
        )
    )

    records: list[dict[str, Any]] = []
    for year in all_years:
        capex_outflow = abs(capex[year]) if year in capex else None
        fcf = _sub(operating_cash_flow.get(year), capex_outflow)
        owner_earnings = _owner_earnings(net_income.get(year), depreciation.get(year), capex_outflow, fcf)
        avg_equity = _avg_pair(equity.get(year - 1), equity.get(year))
        invested_capital = _invested_capital(debt.get(year), equity.get(year), cash.get(year))
        nopat = operating_income.get(year) * 0.79 if operating_income.get(year) is not None else None

        record = {
            "year": year,
            "revenue": revenue.get(year),
            "gross_profit": gross_profit.get(year),
            "operating_income": operating_income.get(year),
            "net_income": net_income.get(year),
            "assets": assets.get(year),
            "liabilities": liabilities.get(year),
            "equity": equity.get(year),
            "cash": cash.get(year),
            "debt": debt.get(year),
            "operating_cash_flow": operating_cash_flow.get(year),
            "capex": capex_outflow,
            "free_cash_flow": fcf,
            "depreciation_amortization": depreciation.get(year),
            "owner_earnings": owner_earnings,
            "eps_diluted": eps.get(year),
            "diluted_shares": diluted_shares.get(year),
        }
        record.update(
            {
                "gross_margin": _div(record["gross_profit"], record["revenue"]),
                "operating_margin": _div(record["operating_income"], record["revenue"]),
                "net_margin": _div(record["net_income"], record["revenue"]),
                "fcf_margin": _div(record["free_cash_flow"], record["revenue"]),
                "roe": _div(record["net_income"], avg_equity or record["equity"]),
                "roic": _div(nopat, invested_capital),
                "debt_to_equity": _div(record["debt"], record["equity"]),
                "debt_to_fcf": _div(record["debt"], record["free_cash_flow"]),
                "equity_to_assets": _div(record["equity"], record["assets"]),
            }
        )
        records.append(record)

    return [row for row in records if _has_core_data(row)]


def _debt_series(facts: dict[str, Any]) -> dict[int, float]:
    all_debt = sec_client.extract_annual_series(facts, TOTAL_DEBT, duration=False)
    if all_debt:
        return all_debt
    long_term = sec_client.extract_annual_series(facts, LONG_TERM_DEBT, duration=False)
    short_term_parts = [sec_client.extract_annual_series(facts, [concept], duration=False) for concept in DEBT_PARTS[:2]]
    if long_term:
        years = sorted(set().union(long_term, *short_term_parts))
        return {
            year: long_term.get(year, 0) + sum(series.get(year, 0) for series in short_term_parts)
            for year in years
            if long_term.get(year, 0) + sum(series.get(year, 0) for series in short_term_parts)
        }
    parts = [sec_client.extract_annual_series(facts, [concept], duration=False) for concept in DEBT_PARTS]
    years = sorted(set().union(*parts)) if parts else []
    output: dict[int, float] = {}
    for year in years:
        total = sum(series.get(year, 0) for series in parts)
        if total:
            output[year] = total
    return output


def _summarize(
    annuals: list[dict[str, Any]],
    price: dict[str, Any] | None,
    shares_outstanding: float | None,
) -> dict[str, Any]:
    latest = annuals[-1]
    lookback = annuals[-5:] if len(annuals) >= 5 else annuals
    revenue_cagr = _cagr([row.get("revenue") for row in annuals])
    net_income_cagr = _cagr([row.get("net_income") for row in annuals])
    fcf_cagr = _cagr([row.get("free_cash_flow") for row in annuals])
    owner_earnings_cagr = _cagr([row.get("owner_earnings") for row in annuals])
    market_cap = price["price"] * shares_outstanding if price and shares_outstanding else None

    return {
        "years": [row["year"] for row in annuals],
        "latest_year": latest["year"],
        "revenue_cagr": revenue_cagr,
        "net_income_cagr": net_income_cagr,
        "fcf_cagr": fcf_cagr,
        "owner_earnings_cagr": owner_earnings_cagr,
        "avg_roe_5y": _avg_metric(lookback, "roe"),
        "avg_roic_5y": _avg_metric(lookback, "roic"),
        "avg_gross_margin_5y": _avg_metric(lookback, "gross_margin"),
        "avg_net_margin_5y": _avg_metric(lookback, "net_margin"),
        "avg_fcf_margin_5y": _avg_metric(lookback, "fcf_margin"),
        "positive_earnings_years": _count_positive(annuals, "net_income"),
        "positive_fcf_years": _count_positive(annuals, "free_cash_flow"),
        "revenue_up_years": _count_growth_years(annuals, "revenue"),
        "latest_debt_to_equity": latest.get("debt_to_equity"),
        "latest_debt_to_fcf": latest.get("debt_to_fcf"),
        "latest_equity_to_assets": latest.get("equity_to_assets"),
        "latest_revenue": latest.get("revenue"),
        "latest_net_income": latest.get("net_income"),
        "latest_fcf": latest.get("free_cash_flow"),
        "latest_owner_earnings": latest.get("owner_earnings"),
        "market_cap": market_cap,
        "pe": _div(market_cap, latest.get("net_income")),
        "p_fcf": _div(market_cap, latest.get("free_cash_flow")),
        "earnings_yield": _div(latest.get("net_income"), market_cap),
        "fcf_yield": _div(latest.get("free_cash_flow"), market_cap),
    }


def _estimate_intrinsic_value(
    annuals: list[dict[str, Any]],
    price: dict[str, Any] | None,
    shares_outstanding: float | None,
) -> dict[str, Any]:
    recent = annuals[-3:] if len(annuals) >= 3 else annuals
    owner_values = [row.get("owner_earnings") for row in recent if _positive(row.get("owner_earnings"))]
    if not owner_values:
        owner_values = [row.get("free_cash_flow") for row in recent if _positive(row.get("free_cash_flow"))]
    if not owner_values:
        return {
            "available": False,
            "reason": "Không đủ owner earnings/free cash flow dương để ước tính.",
        }

    base_owner_earnings = mean(owner_values)
    growth_candidates = [
        _cagr([row.get("revenue") for row in annuals]),
        _cagr([row.get("owner_earnings") for row in annuals]),
        _cagr([row.get("free_cash_flow") for row in annuals]),
    ]
    valid_growth = [value for value in growth_candidates if value is not None and math.isfinite(value)]
    raw_growth = median(valid_growth) if valid_growth else 0.03
    growth_rate = min(max(raw_growth, 0.0), 0.10)
    discount_rate = 0.10
    terminal_growth = 0.025
    horizon_years = 10

    present_value = 0.0
    owner_earnings = base_owner_earnings
    for year in range(1, horizon_years + 1):
        owner_earnings *= 1 + growth_rate
        present_value += owner_earnings / ((1 + discount_rate) ** year)
    terminal_value = owner_earnings * (1 + terminal_growth) / (discount_rate - terminal_growth)
    present_value += terminal_value / ((1 + discount_rate) ** horizon_years)

    intrinsic_per_share = _div(present_value, shares_outstanding)
    current_price = price["price"] if price else None
    margin_of_safety = _div(intrinsic_per_share, current_price)
    if margin_of_safety is not None:
        margin_of_safety -= 1

    return {
        "available": True,
        "base_owner_earnings": base_owner_earnings,
        "growth_rate": growth_rate,
        "discount_rate": discount_rate,
        "terminal_growth": terminal_growth,
        "horizon_years": horizon_years,
        "intrinsic_value": present_value,
        "intrinsic_per_share": intrinsic_per_share,
        "margin_of_safety": margin_of_safety,
        "method": "DCF chủ sở hữu: owner earnings 3 năm gần nhất, tăng trưởng bảo thủ, chiết khấu 10%.",
    }


def _score(annuals: list[dict[str, Any]], summary: dict[str, Any], valuation: dict[str, Any]) -> dict[str, Any]:
    years_count = len(annuals)
    profitability = _points(summary.get("avg_roe_5y"), [(0.20, 15), (0.15, 12), (0.10, 8), (0.05, 4)])
    profitability += _points(summary.get("avg_roic_5y"), [(0.15, 15), (0.10, 11), (0.07, 7), (0.04, 3)])

    consistency = 0
    consistency += 10 * summary["positive_earnings_years"] / years_count
    consistency += 7 * summary["positive_fcf_years"] / years_count
    consistency += 3 * summary["revenue_up_years"] / max(years_count - 1, 1)

    moat = _points(summary.get("avg_gross_margin_5y"), [(0.50, 7), (0.35, 5), (0.25, 3)])
    moat += _points(summary.get("avg_net_margin_5y"), [(0.20, 5), (0.12, 4), (0.08, 2)])
    moat += _points(summary.get("avg_fcf_margin_5y"), [(0.18, 3), (0.10, 2), (0.05, 1)])

    balance_sheet = _lower_is_better(summary.get("latest_debt_to_fcf"), [(3, 9), (5, 6), (8, 3)])
    balance_sheet += _lower_is_better(summary.get("latest_debt_to_equity"), [(0.5, 4), (1.0, 3), (2.0, 1)])
    balance_sheet += _points(summary.get("latest_equity_to_assets"), [(0.45, 2), (0.30, 1)])

    growth = _points(summary.get("revenue_cagr"), [(0.12, 4), (0.08, 3), (0.04, 2), (0.01, 1)])
    growth += _points(summary.get("owner_earnings_cagr"), [(0.12, 6), (0.08, 4), (0.04, 2), (0.01, 1)])

    valuation_score = _points(summary.get("fcf_yield"), [(0.08, 4), (0.05, 3), (0.03, 1)])
    valuation_score += _points(valuation.get("margin_of_safety"), [(0.30, 6), (0.15, 4), (0.00, 2)])

    buckets = {
        "profitability": round(min(profitability, 30), 1),
        "consistency": round(min(consistency, 20), 1),
        "moat_margins": round(min(moat, 15), 1),
        "balance_sheet": round(min(balance_sheet, 15), 1),
        "growth": round(min(growth, 10), 1),
        "valuation": round(min(valuation_score, 10), 1),
    }
    total = round(sum(buckets.values()), 1)
    return {
        "total": total,
        "max": 100,
        "verdict": _verdict(total),
        "buckets": buckets,
        "checklist": _checklist(summary, valuation, annuals),
    }


def _narrative(
    company: dict[str, Any],
    annuals: list[dict[str, Any]],
    summary: dict[str, Any],
    valuation: dict[str, Any],
    score: dict[str, Any],
) -> dict[str, Any]:
    strengths: list[str] = []
    concerns: list[str] = []

    if (summary.get("avg_roic_5y") or 0) >= 0.10:
        strengths.append("ROIC bình quân cao, dấu hiệu doanh nghiệp có lợi thế cạnh tranh hoặc tài sản nhẹ.")
    else:
        concerns.append("ROIC chưa đủ cao/thiếu dữ liệu, cần kiểm tra chất lượng lợi thế cạnh tranh.")

    if summary["positive_fcf_years"] >= max(3, len(annuals) - 1):
        strengths.append("Free cash flow dương trong hầu hết các năm, phù hợp tư duy owner earnings.")
    else:
        concerns.append("Free cash flow thiếu ổn định; nên xem kỹ chu kỳ vốn lưu động và capex.")

    debt_to_fcf = summary.get("latest_debt_to_fcf")
    if debt_to_fcf is not None and debt_to_fcf <= 3:
        strengths.append("Nợ có vẻ dễ trả bằng FCF hiện tại.")
    elif debt_to_fcf is not None:
        concerns.append("Nợ/FCF khá cao; Buffett thường tránh doanh nghiệp cần đòn bẩy lớn.")
    else:
        concerns.append("Không đủ dữ liệu nợ/FCF để đánh giá bảng cân đối.")

    if valuation.get("available") and valuation.get("margin_of_safety") is not None:
        if valuation["margin_of_safety"] >= 0.15:
            strengths.append("Ước tính DCF bảo thủ cho thấy có biên an toàn dương.")
        elif valuation["margin_of_safety"] < 0:
            concerns.append("Giá thị trường cao hơn ước tính giá trị nội tại bảo thủ.")
    else:
        concerns.append("Không đủ dữ liệu giá/cổ phiếu lưu hành để tính biên an toàn.")

    return {
        "headline": f"{company['ticker']} đạt {score['total']}/100: {score['verdict']}.",
        "buffett_view": _buffett_view(summary, valuation, score),
        "strengths": strengths[:5],
        "concerns": concerns[:5],
        "what_to_verify": [
            "Đọc 10-K mới nhất: mô hình kinh doanh, rủi ro cạnh tranh, chất lượng ban lãnh đạo.",
            "So sánh ROIC/margin với đối thủ cùng ngành, không chỉ nhìn tuyệt đối.",
            "Kiểm tra các khoản one-off, mua lại cổ phiếu, SBC và thay đổi vốn lưu động.",
            "Chỉ cân nhắc mua khi có biên an toàn đủ lớn so với giả định bảo thủ.",
        ],
    }


def _compare(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    rows = [
        _compare_metric("Điểm tổng", first, second, "score.total", higher=True),
        _compare_metric("ROIC bình quân 5 năm", first, second, "summary.avg_roic_5y", higher=True),
        _compare_metric("ROE bình quân 5 năm", first, second, "summary.avg_roe_5y", higher=True),
        _compare_metric("FCF dương", first, second, "summary.positive_fcf_years", higher=True),
        _compare_metric("Tăng trưởng doanh thu CAGR", first, second, "summary.revenue_cagr", higher=True),
        _compare_metric("Tăng trưởng owner earnings CAGR", first, second, "summary.owner_earnings_cagr", higher=True),
        _compare_metric("Nợ/FCF mới nhất", first, second, "summary.latest_debt_to_fcf", higher=False),
        _compare_metric("FCF yield", first, second, "summary.fcf_yield", higher=True),
        _compare_metric("Biên an toàn DCF", first, second, "valuation.margin_of_safety", higher=True),
    ]
    tickers = [first["company"]["ticker"], second["company"]["ticker"]]
    wins = {tickers[0]: 0, tickers[1]: 0}
    for row in rows:
        if row["winner"] in wins:
            wins[row["winner"]] += 1

    total_diff = first["score"]["total"] - second["score"]["total"]
    if abs(total_diff) < 5:
        overall = "Hòa tương đối"
        summary = "Hai cổ phiếu có điểm tổng gần nhau; quyết định phụ thuộc nhiều vào định giá và hiểu biết ngành."
    else:
        overall = tickers[0] if total_diff > 0 else tickers[1]
        summary = f"{overall} nổi trội hơn theo bộ lọc Buffett-style hiện tại."

    return {
        "rows": rows,
        "wins": wins,
        "overall_winner": overall,
        "summary": summary,
    }


def _compare_metric(label: str, first: dict[str, Any], second: dict[str, Any], path: str, higher: bool) -> dict[str, Any]:
    first_value = _path(first, path)
    second_value = _path(second, path)
    first_ticker = first["company"]["ticker"]
    second_ticker = second["company"]["ticker"]
    winner = "Không đủ dữ liệu"
    if first_value is not None and second_value is not None:
        diff = first_value - second_value
        if abs(diff) <= max(abs(first_value), abs(second_value), 1) * 0.03:
            winner = "Hòa"
        elif (diff > 0 and higher) or (diff < 0 and not higher):
            winner = first_ticker
        else:
            winner = second_ticker
    return {
        "label": label,
        "first": first_value,
        "second": second_value,
        "winner": winner,
        "higher_is_better": higher,
    }


def _buffett_view(summary: dict[str, Any], valuation: dict[str, Any], score: dict[str, Any]) -> str:
    quality = "rất mạnh" if score["buckets"]["profitability"] >= 24 else "cần kiểm chứng thêm"
    valuation_note = "chưa đủ dữ liệu định giá"
    if valuation.get("margin_of_safety") is not None:
        mos = valuation["margin_of_safety"]
        valuation_note = "có biên an toàn" if mos >= 0.15 else "biên an toàn mỏng hoặc âm"
    return (
        "Theo checklist Buffett-style, ưu tiên doanh nghiệp dễ hiểu, lợi nhuận trên vốn cao, "
        f"FCF bền vững và ít nợ. Hồ sơ hiện tại có chất lượng {quality}; {valuation_note}. "
        "Nếu không hiểu rõ moat và không có biên an toàn, nên bỏ qua dù doanh nghiệp tốt."
    )


def _checklist(summary: dict[str, Any], valuation: dict[str, Any], annuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    years_count = len(annuals)
    return [
        {
            "label": "ROE/ROIC cao và ổn định",
            "passed": (summary.get("avg_roe_5y") or 0) >= 0.15 and (summary.get("avg_roic_5y") or 0) >= 0.10,
            "value": {"roe": summary.get("avg_roe_5y"), "roic": summary.get("avg_roic_5y")},
        },
        {
            "label": "Lợi nhuận và FCF dương nhiều năm",
            "passed": summary["positive_earnings_years"] >= years_count - 1 and summary["positive_fcf_years"] >= years_count - 1,
            "value": {"earnings_years": summary["positive_earnings_years"], "fcf_years": summary["positive_fcf_years"]},
        },
        {
            "label": "Nợ không phụ thuộc vào tăng trưởng",
            "passed": summary.get("latest_debt_to_fcf") is not None and summary["latest_debt_to_fcf"] <= 3,
            "value": {"debt_to_fcf": summary.get("latest_debt_to_fcf"), "debt_to_equity": summary.get("latest_debt_to_equity")},
        },
        {
            "label": "Owner earnings tăng trưởng",
            "passed": (summary.get("owner_earnings_cagr") or 0) > 0.04,
            "value": {"owner_earnings_cagr": summary.get("owner_earnings_cagr")},
        },
        {
            "label": "Có biên an toàn khi mua",
            "passed": valuation.get("margin_of_safety") is not None and valuation["margin_of_safety"] >= 0.15,
            "value": {"margin_of_safety": valuation.get("margin_of_safety")},
        },
    ]


def _verdict(total: float) -> str:
    if total >= 80:
        return "Doanh nghiệp chất lượng cao, chỉ cần chờ giá hợp lý"
    if total >= 65:
        return "Khá hấp dẫn nhưng cần xác minh moat và định giá"
    if total >= 50:
        return "Trung bình, cần biên an toàn lớn"
    return "Rủi ro/thiếu chất lượng theo bộ lọc Buffett-style"


def _points(value: float | None, tiers: list[tuple[float, int]]) -> int:
    if value is None or not math.isfinite(value):
        return 0
    for threshold, points in tiers:
        if value >= threshold:
            return points
    return 0


def _lower_is_better(value: float | None, tiers: list[tuple[float, int]]) -> int:
    if value is None or not math.isfinite(value) or value < 0:
        return 0
    for threshold, points in tiers:
        if value <= threshold:
            return points
    return 0


def _path(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _avg_metric(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row.get(key) for row in rows if row.get(key) is not None and math.isfinite(row[key])]
    return mean(values) if values else None


def _count_positive(rows: list[dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if _positive(row.get(key)))


def _count_growth_years(rows: list[dict[str, Any]], key: str) -> int:
    count = 0
    for previous, current in zip(rows, rows[1:]):
        if current.get(key) is not None and previous.get(key) is not None and current[key] > previous[key]:
            count += 1
    return count


def _cagr(values: list[float | None]) -> float | None:
    clean = [(index, value) for index, value in enumerate(values) if _positive(value)]
    if len(clean) < 2:
        return None
    start_index, start_value = clean[0]
    end_index, end_value = clean[-1]
    years = end_index - start_index
    if years <= 0:
        return None
    return (end_value / start_value) ** (1 / years) - 1


def _owner_earnings(
    net_income: float | None,
    depreciation: float | None,
    capex: float | None,
    fallback_fcf: float | None,
) -> float | None:
    if net_income is not None and capex is not None:
        return net_income + (depreciation or 0) - capex
    return fallback_fcf


def _invested_capital(debt: float | None, equity: float | None, cash: float | None) -> float | None:
    if debt is None and equity is None:
        return None
    return (debt or 0) + (equity or 0) - (cash or 0)


def _avg_pair(first: float | None, second: float | None) -> float | None:
    values = [value for value in (first, second) if value is not None]
    return mean(values) if values else None


def _div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    try:
        value = numerator / denominator
    except ZeroDivisionError:
        return None
    return value if math.isfinite(value) else None


def _sub(first: float | None, second: float | None) -> float | None:
    if first is None or second is None:
        return None
    return first - second


def _positive(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def _has_core_data(row: dict[str, Any]) -> bool:
    return any(row.get(key) is not None for key in ("revenue", "net_income", "assets", "equity", "free_cash_flow"))
