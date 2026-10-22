"""분석 파이프라인 실행과 시각화."""

import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .pipeline import DataAnalyzer


def load_analyzer(data, images):
    """이미지 결측 표시를 보존하고 그룹 통계로 피처를 대치한다."""
    analyzer = DataAnalyzer(data, images)
    analyzer.load_data()
    analyzer.df["image_available"] = analyzer.df["article_id"].isin(analyzer.image_ids)
    missing = analyzer.df.isna().sum().to_dict()
    imputation = analyzer.handle_missing_values(
        columns=["image_mean", "image_std", "image_edge"]
    )
    return analyzer, missing, imputation


def eda(analyzer, output):
    """원본 분포, 이상치 비교와 여섯 종류의 차트를 만든다."""
    import matplotlib.pyplot as plt
    import seaborn as sns

    df = analyzer.df
    outliers, bounds = analyzer.detect_outliers("price")
    mask = (df.price >= bounds[0]) & (df.price <= bounds[1])
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].hist(df.price, bins=40)
    axes[0].set(
        xlabel="normalized item price",
        ylabel="line items",
        title="Sample price distribution",
    )
    axes[1].boxplot(
        [df.price, df.loc[mask, "price"]], tick_labels=["original", "IQR filtered"]
    )
    axes[1].set(ylabel="normalized item price", title="Outlier sensitivity")
    fig.tight_layout()
    fig.savefig(output / "price-distributions.png", dpi=150)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 4))
    df.category.value_counts().head(10).plot.bar(ax=ax)
    ax.set(xlabel="category", ylabel="line items", title="Sample category frequency")
    fig.tight_layout()
    fig.savefig(output / "categories.png", dpi=150)
    plt.close(fig)
    numeric = [
        "price",
        "name_length",
        "word_count",
        "image_mean",
        "image_std",
        "image_edge",
    ]
    observed = df.loc[df.image_available, numeric]
    correlations = observed.corr()
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(
        correlations, annot=True, fmt=".2f", vmin=-1, vmax=1, cmap="coolwarm", ax=ax
    )
    ax.set(
        title="Observed-image feature correlations", xlabel="feature", ylabel="feature"
    )
    fig.tight_layout()
    fig.savefig(output / "correlations.png", dpi=150)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.scatter(observed.image_mean, observed.price, s=8, alpha=0.2)
    ax.set(
        xlabel="image brightness mean",
        ylabel="normalized item price",
        title="Price and observed image brightness",
    )
    fig.tight_layout()
    fig.savefig(output / "scatter.png", dpi=150)
    plt.close(fig)
    monthly = df.set_index("order_date").resample("MS")["price"].sum()
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(monthly.index, monthly.values, "o-")
    ax.set(
        xlabel="month",
        ylabel="sample normalized monetary sum",
        title="Sampled monthly monetary sum",
    )
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output / "monthly.png", dpi=150)
    plt.close(fig)
    brightness_outliers, brightness_bounds = analyzer.detect_outliers("image_mean")
    brightness_kept = df.image_mean.between(*brightness_bounds)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].hist(df.image_mean, bins=30, alpha=0.6, label="before")
    axes[0].hist(
        df.loc[brightness_kept, "image_mean"], bins=30, alpha=0.6, label="after"
    )
    axes[0].set(
        xlabel="image mean", ylabel="line items", title="Brightness IQR sensitivity"
    )
    axes[0].legend()
    axes[1].boxplot(
        [df.image_mean, df.loc[brightness_kept, "image_mean"]],
        tick_labels=["before", "after"],
    )
    axes[1].set(ylabel="image mean", title="Brightness before/after")
    fig.tight_layout()
    fig.savefig(output / "image-outliers.png", dpi=150)
    plt.close(fig)
    stats = df[numeric].describe().to_dict()
    return {
        "rows": len(df),
        "columns": len(df.columns),
        "products": df.article_id.nunique(),
        "customers": df.customer_id.nunique(),
        "first_date": str(df.order_date.min().date()),
        "last_date": str(df.order_date.max().date()),
        "images_observed": len(analyzer.image_ids),
        "image_missing_rows": int((~df.image_available).sum()),
        "iqr_bounds": bounds,
        "outlier_count": len(outliers),
        "brightness_outlier_count": len(brightness_outliers),
        "brightness_iqr_bounds": brightness_bounds,
        "statistics": stats,
        "correlations": {
            "price_word_count": float(correlations.loc["price", "word_count"]),
            "price_image_mean": float(correlations.loc["price", "image_mean"]),
        },
        "monthly_sample_monetary": {
            str(k.date()): float(v) for k, v in monthly.items()
        },
    }


def rfm_analysis(analyzer, output, interactive=False):
    """고객별 RFM을 세분화하고 그룹별 지표를 저장한다."""
    import matplotlib.pyplot as plt
    import seaborn as sns

    rfm = analyzer.calculate_rfm()
    summary = rfm.groupby("segment").agg(
        customers=("monetary", "size"),
        mean_recency=("recency", "mean"),
        mean_frequency=("frequency", "mean"),
        mean_monetary=("monetary", "mean"),
        total_monetary=("monetary", "sum"),
    )
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    summary.customers.plot.bar(ax=axes[0])
    axes[0].set(xlabel="segment", ylabel="customers", title="RFM segments")
    sns.heatmap(
        rfm.groupby(["R", "F"]).size().unstack(fill_value=0),
        annot=True,
        fmt="d",
        ax=axes[1],
    )
    axes[1].set(title="R and F score counts", xlabel="F score", ylabel="R score")
    fig.tight_layout()
    fig.savefig(output / "rfm-segments.png", dpi=150)
    plt.close(fig)
    summary.to_csv(output / "segment-summary.csv")
    if interactive:
        import plotly.express as px

        chart = px.scatter_3d(
            rfm.reset_index(drop=True),
            x="recency",
            y="frequency",
            z="monetary",
            color="segment",
            title="RFM customer segments (sample observations)",
        )
        chart.write_html(output / "rfm-interactive.html", include_plotlyjs=True)
    return {
        "reference_date": str(analyzer.reference_date.date()),
        "customer_count": len(rfm),
        "frequency_definition": "distinct observed purchase dates, not line-item count",
        "segments": summary.to_dict(orient="index"),
    }


def cohort_analysis(analyzer, output):
    """최초 관측 구매월 코호트의 재구매율을 표시한다."""
    import matplotlib.pyplot as plt
    import seaborn as sns

    retention = analyzer.cohort_retention()
    retention.to_csv(output / "cohort-retention.csv")
    fig, ax = plt.subplots(figsize=(14, 9))
    sns.heatmap(retention, mask=retention.isna(), cmap="Blues", vmin=0, vmax=1, ax=ax)
    ax.set(
        xlabel="months since first observed purchase",
        ylabel="first observed purchase month",
        title="Purchase cohort retention (right-censored)",
    )
    fig.tight_layout()
    fig.savefig(output / "cohort.png", dpi=150)
    plt.close(fig)
    return {
        "cohorts": len(retention),
        "periods": len(retention.columns),
        "first_purchase_definition": "first observed purchase in sampled time ranges; account signup dates unavailable",
        "right_censored_cells": int(retention.isna().sum().sum()),
        "period_zero_min": float(retention[0].min()),
        "period_zero_max": float(retention[0].max()),
    }


def main():
    """선택한 분석을 실행해 실제 결과를 출력한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("section", choices=["eda", "rfm", "cohort"])
    parser.add_argument(
        "--data", type=Path, default=Path("data/analysis_transactions.csv")
    )
    parser.add_argument("--images", type=Path, default=Path("data/images"))
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    np.random.seed(42)
    analyzer, missing, imputation = load_analyzer(args.data, args.images)
    if args.section == "eda":
        result = eda(analyzer, args.output)
        result.update(missing_before=missing, imputation=imputation)
    elif args.section == "rfm":
        result = rfm_analysis(analyzer, args.output, args.interactive)
    else:
        result = cohort_analysis(analyzer, args.output)
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    (args.output / (args.section + ".json")).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
