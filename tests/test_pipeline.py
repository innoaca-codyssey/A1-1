"""고정 거래와 독립 계산으로 분석 로직을 검증한다."""

import unittest
import numpy as np
import pandas as pd
from src.pipeline import DataAnalyzer


class PipelineTests(unittest.TestCase):
    """파이프라인의 주요 경계와 집계 기준을 검사한다."""

    def analyzer(self):
        """독립적인 4행 거래 fixture를 만든다."""
        a = DataAnalyzer("unused", min_rows=0)
        a.df = pd.DataFrame(
            {
                "customer_id": ["a", "a", "b", "b"],
                "order_date": pd.to_datetime(
                    ["2024-01-01", "2024-02-01", "2024-02-01", "2024-02-01"]
                ),
                "price": [10.0, 20.0, 5.0, 15.0],
                "category": ["x", "x", "y", "y"],
            }
        )
        return a

    def test_vector_features(self):
        """이미지별 독립 계산과 배치 벡터 연산을 비교한다."""
        images = np.random.default_rng(42).random((4, 8, 9, 3))
        result = DataAnalyzer.image_statistics(images)
        np.testing.assert_allclose(result["image_mean"], [a.mean() for a in images])
        np.testing.assert_allclose(result["image_std"], [a.std() for a in images])
        np.testing.assert_allclose(result["histogram"].sum(axis=1), 1.0)
        flat = np.ones((2, 8, 8, 3)) * 0.5
        np.testing.assert_array_equal(
            DataAnalyzer.image_statistics(flat)["image_edge"], 0
        )

    def test_group_imputation_and_fallback(self):
        """그룹 통계와 전체 통계 보완의 실제 값을 확인한다."""
        a = self.analyzer()
        a.df["value"] = [2.0, np.nan, np.nan, np.nan]
        result = a.handle_missing_values(columns=["value"])
        self.assertEqual(result["before"]["value"], 3)
        self.assertEqual(result["after"]["value"], 0)
        np.testing.assert_array_equal(a.df["value"], 2)

    def test_all_missing_rejected(self):
        """모든 값이 결측이면 임의 숫자를 만들지 않는다."""
        a = self.analyzer()
        a.df["empty"] = np.nan
        with self.assertRaises(ValueError):
            a.handle_missing_values(columns=["empty"])

    def test_iqr(self):
        """IQR 이상치와 원본 불변을 확인한다."""
        a = self.analyzer()
        a.df = pd.DataFrame({"value": [1, 2, 2, 3, 100]})
        found, bounds = a.detect_outliers("value")
        self.assertEqual(found["value"].tolist(), [100])
        self.assertEqual(len(a.df), 5)
        self.assertEqual(bounds, (0.5, 4.5))

    def test_rfm_purchase_days(self):
        """Frequency를 같은 날 구매한 상품 수와 혼동하지 않는다."""
        result = self.analyzer().calculate_rfm(reference_date="2024-02-02")
        self.assertEqual(result.loc["a", "frequency"], 2)
        self.assertEqual(result.loc["b", "frequency"], 1)
        self.assertEqual(result.loc["a", "monetary"], 30)
        self.assertEqual(result.loc["b", "monetary"], 20)
        self.assertEqual(result.loc["a", "recency"], 1)

    def test_cohort_right_censoring(self):
        """관측되지 않은 미래 월을 재구매 0으로 채우지 않는다."""
        result = self.analyzer().cohort_retention()
        self.assertEqual(result.loc[pd.Period("2024-01"), 1], 1.0)
        self.assertTrue(pd.isna(result.loc[pd.Period("2024-02"), 1]))

    def test_bad_image_shapes(self):
        """잘못된 차원과 비유한 값을 거절한다."""
        with self.assertRaises(ValueError):
            DataAnalyzer.image_statistics(np.zeros((8, 8, 3)))
        with self.assertRaises(ValueError):
            DataAnalyzer.image_statistics(np.full((1, 4, 4, 3), np.nan))

    def test_cohort_keeps_observed_empty_months(self):
        """재구매가 전혀 없는 관측 가능한 달도 0으로 남긴다."""
        analyzer = self.analyzer()
        analyzer.df = pd.DataFrame({
            "customer_id": ["a", "b"],
            "order_date": pd.to_datetime(["2024-01-01", "2024-03-01"]),
        })
        result = analyzer.cohort_retention()
        self.assertEqual(result.columns.tolist(), [0, 1, 2])
        self.assertEqual(result.loc[pd.Period("2024-01"), 2], 0.)
        self.assertTrue(pd.isna(result.loc[pd.Period("2024-03"), 2]))


if __name__ == "__main__":
    unittest.main()
