"""NumPy/Pandas 기반 멀티모달 분석 파이프라인."""

from pathlib import Path
import numpy as np
import pandas as pd


class DataAnalyzer:
    """원본 거래와 상품 이미지를 읽고 전처리/RFM/코호트를 계산한다."""

    def __init__(self, data_path, image_dir=None, min_rows=1000):
        """입력 경로와 최소 데이터 크기를 설정한다."""
        self.data_path = Path(data_path)
        self.image_dir = Path(image_dir) if image_dir else None
        self.min_rows = min_rows
        self.df = None
        self.image_ids = []
        self.images = None
        self.image_failures = []

    @staticmethod
    def image_statistics(images, bins=16):
        """이미지 배치의 통계/히스토그램/엣지 특징을 벡터 연산한다."""
        a = np.asarray(images, dtype=float)
        if a.ndim != 4 or a.shape[0] == 0 or min(a.shape[1:3]) < 2:
            raise ValueError("N,H,W,C 이미지 배치가 필요합니다")
        if np.any(~np.isfinite(a)):
            raise ValueError("이미지에 유한하지 않은 값이 있습니다")
        flat = a.reshape(len(a), -1)
        quantized = np.clip((flat * bins).astype(int), 0, bins - 1)
        offsets = np.arange(len(a))[:, None] * bins
        hist = (
            np.bincount((quantized + offsets).ravel(), minlength=len(a) * bins).reshape(
                len(a), bins
            )
            / flat.shape[1]
        )
        edge = (
            np.abs(np.diff(a, axis=1)).mean(axis=(1, 2, 3))
            + np.abs(np.diff(a, axis=2)).mean(axis=(1, 2, 3))
        ) / 2
        return {
            "image_mean": a.mean(axis=(1, 2, 3)),
            "image_std": a.std(axis=(1, 2, 3)),
            "image_edge": edge,
            "histogram": hist,
        }

    def load_data(self):
        """명시적 dtype으로 거래를 읽고 텍스트/이미지 피처를 연결한다."""
        self.image_ids = []
        self.image_failures = []
        self.images = None
        self.df = pd.read_csv(
            self.data_path, dtype={"customer_id": str, "article_id": str}
        )
        required = {
            "customer_id",
            "order_date",
            "article_id",
            "price",
            "product_name",
            "category",
        }
        if not required.issubset(self.df):
            raise ValueError(f"필수 컬럼 누락: {required - set(self.df)}")
        if len(self.df) < self.min_rows or len(self.df.columns) < 8:
            raise ValueError("1,000건/8컬럼 조건을 확인하세요")
        self.df["order_date"] = pd.to_datetime(self.df["order_date"], errors="raise")
        self.df["price"] = pd.to_numeric(self.df["price"], errors="raise")
        if (self.df["price"] < 0).any():
            raise ValueError("음수 가격을 먼저 확인하세요")
        self.df["name_length"] = self.df["product_name"].fillna("").str.len()
        self.df["word_count"] = self.df["product_name"].fillna("").str.split().str.len()
        if self.image_dir:
            from matplotlib.image import imread

            arrays = []
            for article in sorted(self.df["article_id"].unique()):
                path = self.image_dir / (article + ".jpg")
                if not path.is_file():
                    self.image_failures.append(article)
                    continue
                try:
                    a = imread(path).astype(float)
                    if a.max() > 1:
                        a /= 255
                    if a.ndim == 2:
                        a = np.repeat(a[..., None], 3, axis=2)
                    a = a[
                        :: int(np.ceil(a.shape[0] / 32)),
                        :: int(np.ceil(a.shape[1] / 32)),
                        :3,
                    ][:32, :32]
                    a = np.pad(
                        a,
                        ((0, 32 - a.shape[0]), (0, 32 - a.shape[1]), (0, 0)),
                        mode="edge",
                    )
                    arrays.append(a)
                    self.image_ids.append(article)
                except (ValueError, OSError):
                    self.image_failures.append(article)
            if not arrays:
                raise ValueError("읽을 수 있는 이미지가 없습니다")
            self.images = np.stack(arrays)
            features = self.image_statistics(self.images)
            frame = pd.DataFrame(
                {k: v for k, v in features.items() if k != "histogram"},
                index=self.image_ids,
            )
            self.df = self.df.join(frame, on="article_id", validate="many_to_one")
            self.histograms = features["histogram"]
        return self.df

    def handle_missing_values(
        self, strategy="group_mean", group_col="category", columns=None
    ):
        """그룹 평균/중앙값으로 대치하고 불가능한 그룹은 전체 통계로 보완한다."""
        if self.df is None:
            raise RuntimeError("데이터를 먼저 로드하세요")
        if strategy not in ("group_mean", "group_median"):
            raise ValueError("지원하지 않는 대치 전략")
        stat = "mean" if strategy == "group_mean" else "median"
        columns = columns or self.df.select_dtypes(include="number").columns.tolist()
        before = self.df[columns].isna().sum().to_dict()
        for col in columns:
            global_value = getattr(self.df[col], stat)()
            if pd.isna(global_value):
                raise ValueError(f"{col} 전체가 결측입니다")
            values = self.df.groupby(group_col, dropna=False)[col].transform(stat)
            self.df[col] = self.df[col].fillna(values).fillna(global_value)
        return {"before": before, "after": self.df[columns].isna().sum().to_dict()}

    def detect_outliers(self, column, threshold=1.5):
        """IQR 경계 밖의 원본 행과 경계값을 반환한다. 데이터를 삭제하지 않는다."""
        if threshold < 0:
            raise ValueError("임계값은 0 이상이어야 합니다")
        series = self.df[column].dropna()
        q1, q3 = series.quantile([0.25, 0.75])
        iqr = q3 - q1
        lower, upper = q1 - threshold * iqr, q3 + threshold * iqr
        return self.df[(self.df[column] < lower) | (self.df[column] > upper)].copy(), (
            float(lower),
            float(upper),
        )

    def calculate_rfm(
        self,
        customer_col="customer_id",
        date_col="order_date",
        amount_col="price",
        reference_date=None,
    ):
        """최종 관측일 다음 날을 기준으로 구매일 빈도/행 금액 합을 집계한다."""
        df = self.df.copy()
        df[date_col] = pd.to_datetime(df[date_col])
        reference = (
            pd.Timestamp(reference_date)
            if reference_date
            else df[date_col].max().normalize() + pd.Timedelta(days=1)
        )
        if reference < df[date_col].max():
            raise ValueError("기준일이 관측 거래보다 빠릅니다")
        grouped = df.groupby(customer_col)
        rfm = grouped.agg(
            last_date=(date_col, "max"),
            frequency=(date_col, "nunique"),
            monetary=(amount_col, "sum"),
        )
        rfm["recency"] = (reference - rfm["last_date"]).dt.days
        for col, ascending in [
            ("recency", False),
            ("frequency", True),
            ("monetary", True),
        ]:
            percentile = rfm[col].rank(method="average", pct=True, ascending=ascending)
            rfm[col[0].upper()] = np.ceil(percentile * 4).clip(1, 4).astype(int)
        vip = (rfm["R"] >= 3) & (rfm["F"] >= 3) & (rfm["M"] >= 3)
        loyal = rfm["F"] >= 3
        recent = rfm["R"] >= 3
        rfm["segment"] = np.select(
            [vip, loyal, recent], ["VIP", "Loyal", "New"], default="Churned"
        )
        self.reference_date = reference
        return rfm

    def cohort_retention(self):
        """최초 관측 구매월 코호트의 월별 재구매율과 우측 절단을 계산한다."""
        data = self.df[["customer_id", "order_date"]].copy()
        data["month"] = data["order_date"].dt.to_period("M")
        data["cohort"] = data.groupby("customer_id")["month"].transform("min")
        data["period"] = (
            (data["month"].dt.year - data["cohort"].dt.year) * 12
            + data["month"].dt.month
            - data["cohort"].dt.month
        )
        counts = data.groupby(["cohort", "period"])["customer_id"].nunique().unstack()
        result = counts.div(counts[0], axis=0)
        last = data["month"].max()
        for cohort in result.index:
            available = (last.year - cohort.year) * 12 + last.month - cohort.month
            result.loc[cohort, result.columns <= available] = result.loc[
                cohort, result.columns <= available
            ].fillna(0)
        return result
