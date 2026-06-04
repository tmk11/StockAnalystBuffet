from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MIN_GROWTH = -0.50
MAX_GROWTH = 1.00
DEFAULT_PROJECTION_YEARS = 10
DEFAULT_DISCOUNT_RATE = 0.10
DEFAULT_TERMINAL_GROWTH = 0.025
TOLERANCE = 0.001
MAX_ITERATIONS = 100


@dataclass(frozen=True)
class ReverseDCFInput:
    ticker: str | None = None
    company_name: str | None = None
    market_cap: float | None = None
    share_price: float | None = None
    shares_outstanding: float | None = None
    total_debt: float | None = None
    cash_and_equivalents: float | None = None
    current_fcf: float | None = None
    projection_years: int = DEFAULT_PROJECTION_YEARS
    discount_rate: float = DEFAULT_DISCOUNT_RATE
    terminal_growth_rate: float = DEFAULT_TERMINAL_GROWTH


def calculate_reverse_dcf(raw_input: dict[str, Any] | ReverseDCFInput) -> dict[str, Any]:
    input_data = _coerce_input(raw_input)
    warnings = _input_warnings(input_data)
    errors = _input_errors(input_data)
    if errors:
        return _error_result(input_data, warnings, errors)

    enterprise_value = _enterprise_value(input_data)
    low = MIN_GROWTH
    high = MAX_GROWTH
    low_value = _dcf_components(input_data.current_fcf, low, input_data.projection_years, input_data.discount_rate, input_data.terminal_growth_rate)["calculated_dcf_value"]
    high_value = _dcf_components(input_data.current_fcf, high, input_data.projection_years, input_data.discount_rate, input_data.terminal_growth_rate)["calculated_dcf_value"]

    if enterprise_value <= low_value:
        implied_growth = low
        warnings.append("Enterprise Value thấp hơn hoặc bằng DCF ở mức tăng trưởng tối thiểu -50%; kết quả bị chặn tại biên dưới.")
        iterations = 0
    elif enterprise_value >= high_value:
        implied_growth = high
        warnings.append("Enterprise Value cao hơn hoặc bằng DCF ở mức tăng trưởng tối đa 100%; kết quả bị chặn tại biên trên.")
        iterations = 0
    else:
        implied_growth, iterations = _solve_growth(input_data, enterprise_value)

    components = _dcf_components(
        input_data.current_fcf,
        implied_growth,
        input_data.projection_years,
        input_data.discount_rate,
        input_data.terminal_growth_rate,
    )
    margin_of_error = _safe_div(components["calculated_dcf_value"] - enterprise_value, enterprise_value)
    return {
        "ok": True,
        "input": _input_to_dict(input_data),
        "impliedGrowthRate": implied_growth,
        "enterpriseValue": enterprise_value,
        "calculatedDcfValue": components["calculated_dcf_value"],
        "pvForecastFcf": components["pv_forecast_fcf"],
        "pvTerminalValue": components["pv_terminal_value"],
        "terminalValue": components["terminal_value"],
        "projectionTable": components["projection_table"],
        "sensitivityTable": _sensitivity_table(input_data),
        "marginOfError": margin_of_error,
        "iterations": iterations,
        "commentary": _commentary(implied_growth),
        "warnings": warnings,
        "errors": [],
        "disclaimer": (
            "Reverse DCF không dự đoán chắc chắn giá trị thật của cổ phiếu. Nó chỉ cho biết thị trường hiện tại "
            "đang kỳ vọng mức tăng trưởng FCF bao nhiêu. Kết quả phụ thuộc mạnh vào FCF hiện tại, discount rate, "
            "terminal growth và chất lượng dữ liệu đầu vào."
        ),
    }


def _solve_growth(input_data: ReverseDCFInput, enterprise_value: float) -> tuple[float, int]:
    low = MIN_GROWTH
    high = MAX_GROWTH
    midpoint = 0.0
    iterations = 0
    for iterations in range(1, MAX_ITERATIONS + 1):
        midpoint = (low + high) / 2
        dcf_value = _dcf_components(
            input_data.current_fcf,
            midpoint,
            input_data.projection_years,
            input_data.discount_rate,
            input_data.terminal_growth_rate,
        )["calculated_dcf_value"]
        error = abs(dcf_value - enterprise_value) / enterprise_value
        if error < TOLERANCE:
            break
        if dcf_value < enterprise_value:
            low = midpoint
        else:
            high = midpoint
    return midpoint, iterations


def _dcf_components(
    current_fcf: float,
    growth_rate: float,
    projection_years: int,
    discount_rate: float,
    terminal_growth_rate: float,
) -> dict[str, Any]:
    projection_table = []
    pv_forecast_fcf = 0.0
    last_fcf = current_fcf
    for year in range(1, projection_years + 1):
        projected_fcf = current_fcf * ((1 + growth_rate) ** year)
        discount_factor = 1 / ((1 + discount_rate) ** year)
        present_value = projected_fcf * discount_factor
        pv_forecast_fcf += present_value
        last_fcf = projected_fcf
        projection_table.append(
            {
                "year": year,
                "projectedFcf": projected_fcf,
                "discountFactor": discount_factor,
                "presentValueOfFcf": present_value,
            }
        )

    terminal_value = last_fcf * (1 + terminal_growth_rate) / (discount_rate - terminal_growth_rate)
    pv_terminal_value = terminal_value / ((1 + discount_rate) ** projection_years)
    calculated_dcf_value = pv_forecast_fcf + pv_terminal_value
    return {
        "calculated_dcf_value": calculated_dcf_value,
        "pv_forecast_fcf": pv_forecast_fcf,
        "pv_terminal_value": pv_terminal_value,
        "terminal_value": terminal_value,
        "projection_table": projection_table,
    }


def _sensitivity_table(input_data: ReverseDCFInput) -> list[dict[str, Any]]:
    rows = []
    enterprise_value = _enterprise_value(input_data)
    for discount_rate in (0.08, 0.10, 0.12):
        for terminal_growth_rate in (0.02, 0.03):
            if discount_rate <= terminal_growth_rate:
                implied_growth = None
            else:
                adjusted_input = ReverseDCFInput(
                    **{**_input_to_dict(input_data), "discount_rate": discount_rate, "terminal_growth_rate": terminal_growth_rate}
                )
                if enterprise_value <= _dcf_components(input_data.current_fcf, MIN_GROWTH, adjusted_input.projection_years, discount_rate, terminal_growth_rate)["calculated_dcf_value"]:
                    implied_growth = MIN_GROWTH
                elif enterprise_value >= _dcf_components(input_data.current_fcf, MAX_GROWTH, adjusted_input.projection_years, discount_rate, terminal_growth_rate)["calculated_dcf_value"]:
                    implied_growth = MAX_GROWTH
                else:
                    implied_growth, _ = _solve_growth(adjusted_input, enterprise_value)
            rows.append(
                {
                    "discountRate": discount_rate,
                    "terminalGrowthRate": terminal_growth_rate,
                    "impliedGrowthRate": implied_growth,
                }
            )
    return rows


def _coerce_input(raw_input: dict[str, Any] | ReverseDCFInput) -> ReverseDCFInput:
    if isinstance(raw_input, ReverseDCFInput):
        return raw_input
    return ReverseDCFInput(
        ticker=_string(raw_input.get("ticker")),
        company_name=_string(raw_input.get("company_name") or raw_input.get("companyName")),
        market_cap=_number(_pick(raw_input, "market_cap", "marketCap")),
        share_price=_number(_pick(raw_input, "share_price", "sharePrice")),
        shares_outstanding=_number(_pick(raw_input, "shares_outstanding", "sharesOutstanding")),
        total_debt=_number(_pick(raw_input, "total_debt", "totalDebt")),
        cash_and_equivalents=_number(_pick(raw_input, "cash_and_equivalents", "cashAndEquivalents")),
        current_fcf=_number(_pick(raw_input, "current_fcf", "currentFcf")),
        projection_years=_integer(_pick(raw_input, "projection_years", "projectionYears"), DEFAULT_PROJECTION_YEARS),
        discount_rate=_rate(_pick(raw_input, "discount_rate", "discountRate"), DEFAULT_DISCOUNT_RATE),
        terminal_growth_rate=_rate(_pick(raw_input, "terminal_growth_rate", "terminalGrowthRate"), DEFAULT_TERMINAL_GROWTH),
    )


def _input_errors(input_data: ReverseDCFInput) -> list[str]:
    errors = []
    if input_data.market_cap is None or input_data.market_cap <= 0:
        errors.append("Market cap thiếu hoặc <= 0.")
    if input_data.current_fcf is None:
        errors.append("Current free cash flow thiếu.")
    elif input_data.current_fcf <= 0:
        errors.append("Reverse DCF với FCF âm hoặc bằng 0 không đáng tin.")
    if input_data.discount_rate <= input_data.terminal_growth_rate:
        errors.append("Discount rate/WACC phải lớn hơn terminal growth rate.")
    if input_data.projection_years <= 0:
        errors.append("Projection years phải lớn hơn 0.")
    if input_data.market_cap is not None and input_data.market_cap > 0 and _enterprise_value(input_data) <= 0:
        errors.append("Current Enterprise Value phải lớn hơn 0.")
    return errors


def _input_warnings(input_data: ReverseDCFInput) -> list[str]:
    warnings = []
    if input_data.total_debt is None:
        warnings.append("Total debt thiếu; app dùng 0 cho debt.")
    if input_data.cash_and_equivalents is None:
        warnings.append("Cash and equivalents thiếu; app dùng 0 cho cash.")
    if input_data.shares_outstanding is None:
        warnings.append("Shares outstanding thiếu; kết quả vẫn dùng Enterprise Value nhưng không kiểm tra được dữ liệu/cổ phiếu.")
    return warnings


def _error_result(input_data: ReverseDCFInput, warnings: list[str], errors: list[str]) -> dict[str, Any]:
    return {
        "ok": False,
        "input": _input_to_dict(input_data),
        "impliedGrowthRate": None,
        "enterpriseValue": _enterprise_value(input_data) if (input_data.market_cap or 0) > 0 else None,
        "calculatedDcfValue": None,
        "pvForecastFcf": None,
        "pvTerminalValue": None,
        "terminalValue": None,
        "projectionTable": [],
        "sensitivityTable": [],
        "marginOfError": None,
        "warnings": warnings,
        "errors": errors,
    }


def _enterprise_value(input_data: ReverseDCFInput) -> float:
    return (input_data.market_cap or 0) + (input_data.total_debt or 0) - (input_data.cash_and_equivalents or 0)


def _commentary(implied_growth: float) -> str:
    if implied_growth < 0:
        return "Thị trường đang kỳ vọng FCF giảm hoặc cổ phiếu có thể đang rất rẻ, cần kiểm tra rủi ro."
    if implied_growth <= 0.05:
        return "Kỳ vọng tăng trưởng thấp, phù hợp với doanh nghiệp trưởng thành."
    if implied_growth <= 0.10:
        return "Kỳ vọng tăng trưởng vừa phải, cần công ty có chất lượng ổn."
    if implied_growth <= 0.20:
        return "Thị trường đang kỳ vọng tăng trưởng khá cao, cần kiểm tra doanh thu, margin, moat và lịch sử tăng trưởng."
    return "Kỳ vọng rất cao, cổ phiếu có thể đang đắt trừ khi công ty tăng trưởng cực mạnh."


def _input_to_dict(input_data: ReverseDCFInput) -> dict[str, Any]:
    return {
        "ticker": input_data.ticker,
        "company_name": input_data.company_name,
        "market_cap": input_data.market_cap,
        "share_price": input_data.share_price,
        "shares_outstanding": input_data.shares_outstanding,
        "total_debt": input_data.total_debt,
        "cash_and_equivalents": input_data.cash_and_equivalents,
        "current_fcf": input_data.current_fcf,
        "projection_years": input_data.projection_years,
        "discount_rate": input_data.discount_rate,
        "terminal_growth_rate": input_data.terminal_growth_rate,
    }


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip().replace("$", "").replace(",", "")
        if not text:
            return None
        suffix = text[-1].upper()
        multiplier = 1.0
        if suffix in {"K", "M", "B", "T"}:
            multiplier = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[suffix]
            text = text[:-1]
        try:
            return float(text) * multiplier
        except (TypeError, ValueError):
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rate(value: Any, default: float) -> float:
    number = _number(value)
    if number is None:
        return default
    if abs(number) > 1:
        return number / 100
    return number


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator
