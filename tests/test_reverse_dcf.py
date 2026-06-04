import unittest

from valuation.reverse_dcf import calculate_reverse_dcf


def dcf_value(fcf0, growth, years=10, discount_rate=0.10, terminal_growth=0.025):
    pv_forecast = 0.0
    last_fcf = fcf0
    for year in range(1, years + 1):
        last_fcf = fcf0 * ((1 + growth) ** year)
        pv_forecast += last_fcf / ((1 + discount_rate) ** year)
    terminal_value = last_fcf * (1 + terminal_growth) / (discount_rate - terminal_growth)
    return pv_forecast + terminal_value / ((1 + discount_rate) ** years)


class ReverseDCFTest(unittest.TestCase):
    def test_positive_fcf_solves_reasonable_growth(self):
        target_growth = 0.08
        debt = 50.0
        cash = 20.0
        enterprise_value = dcf_value(100.0, target_growth)
        result = calculate_reverse_dcf(
            {
                "market_cap": enterprise_value - debt + cash,
                "total_debt": debt,
                "cash_and_equivalents": cash,
                "current_fcf": 100.0,
                "projection_years": 10,
                "discount_rate": 0.10,
                "terminal_growth_rate": 0.025,
            }
        )
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["impliedGrowthRate"], target_growth, delta=0.001)

    def test_fcf_non_positive_returns_error(self):
        result = calculate_reverse_dcf({"market_cap": 1000, "current_fcf": 0, "total_debt": 0, "cash_and_equivalents": 0})
        self.assertFalse(result["ok"])
        self.assertTrue(any("FCF" in error for error in result["errors"]))

    def test_discount_rate_must_exceed_terminal_growth(self):
        result = calculate_reverse_dcf(
            {"market_cap": 1000, "current_fcf": 100, "total_debt": 0, "cash_and_equivalents": 0, "discount_rate": 0.03, "terminal_growth_rate": 0.03}
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any("Discount rate" in error for error in result["errors"]))

    def test_market_cap_must_be_positive(self):
        result = calculate_reverse_dcf({"market_cap": 0, "current_fcf": 100, "total_debt": 0, "cash_and_equivalents": 0})
        self.assertFalse(result["ok"])
        self.assertTrue(any("Market cap" in error for error in result["errors"]))

    def test_solver_converges_to_enterprise_value(self):
        result = calculate_reverse_dcf({"market_cap": 1800, "total_debt": 200, "cash_and_equivalents": 100, "current_fcf": 120})
        self.assertTrue(result["ok"])
        relative_error = abs(result["calculatedDcfValue"] - result["enterpriseValue"]) / result["enterpriseValue"]
        self.assertLessEqual(relative_error, 0.001)

    def test_sensitivity_table_has_six_rows(self):
        result = calculate_reverse_dcf({"market_cap": 1800, "total_debt": 200, "cash_and_equivalents": 100, "current_fcf": 120})
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["sensitivityTable"]), 6)


if __name__ == "__main__":
    unittest.main()
