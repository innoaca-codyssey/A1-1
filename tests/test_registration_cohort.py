"""첫 구매 대체 없이 가입월을 사용하고 미관측 월을 분리한다."""

import unittest
import pandas as pd
from src.registration_cohort import signup_retention


class RegistrationCohortTests(unittest.TestCase):
    def test_actual_signup_and_conditional_denominator(self):
        registrations = pd.Series(
            pd.to_datetime(["2020-01-10", "2020-01-11", "2020-02-15"]),
            index=["a", "b", "c"],
        )
        jan = pd.Period("2020-01").ordinal
        feb = jan + 1
        mar = jan + 2
        pairs = pd.DataFrame(
            [("a", jan), ("a", jan), ("a", feb), ("b", feb), ("c", feb), ("c", mar)],
            columns=["client_id", "month"],
        )
        table, conversion = signup_retention(registrations, pairs, [jan, feb, mar])
        self.assertEqual(table.loc["2020-01", 0], 1)
        self.assertEqual(table.loc["2020-01", 1], 1)
        self.assertEqual(table.loc["2020-01", 2], 0)
        self.assertEqual(table.loc["2020-02", 1], 1)
        self.assertTrue(pd.isna(table.loc["2020-02", 2]))
        self.assertEqual(conversion[0]["registrations"], 2)
        self.assertEqual(conversion[0]["initial_conversion"], 0.5)

    def test_partial_or_missing_calendar_month_is_not_zero(self):
        registry = pd.Series(pd.to_datetime(["2020-01-05"]), index=["a"])
        jan = pd.Period("2020-01").ordinal
        pairs = pd.DataFrame([("a", jan)], columns=["client_id", "month"])
        table, _ = signup_retention(registry, pairs, [jan, jan + 2])
        self.assertTrue(pd.isna(table.loc["2020-01", 1]))
        self.assertEqual(table.loc["2020-01", 2], 0)
