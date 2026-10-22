"""최초 멤버십 카드 발급월 기준의 실제 재구매 코호트."""

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

REVISION = "7744156a4f89f4828607921e8c9668f04801f4de"
FILES = {
    "clients.csv.gz": "b8985170e03dc65fa532fb6b8ca6dd70ea5c30c35ea7c1019ee6ea2034d04099",
    "purchases.csv.gz": "1342e14e1aa9d39dc242f1b66c903f0576fd184af9dc5a3bbe932607dc2d8aba",
}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(root, download=False):
    """고정 원본의 크기와 해시를 확인한 뒤 분석을 허용한다."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        path = root / name
        if not path.exists() and download:
            part = path.with_suffix(path.suffix + ".part")
            url = f"https://huggingface.co/datasets/pytorch-lifestream/retailhero-uplift/resolve/{REVISION}/data/{name}"
            with (
                urllib.request.urlopen(url, timeout=180) as response,
                part.open("wb") as output,
            ):
                while chunk := response.read(1 << 20):
                    output.write(chunk)
            if digest(part) != expected:
                raise ValueError("원본 다운로드 해시 불일치")
            part.replace(path)
        if digest(path) != expected:
            raise ValueError("원본 해시 불일치: " + name)


def signup_retention(registrations, pairs, complete_months):
    """가입월에 첫 결제를 마친 집단의 이후 월별 재구매율을 계산한다."""
    registry = registrations.copy()
    registry.index = registry.index.astype(str)
    cohort = registry.dt.to_period("M").map(lambda value: value.ordinal)
    rows = pairs.drop_duplicates(["client_id", "month"]).copy()
    rows["signup_month"] = rows.client_id.map(cohort)
    rows = rows[rows.signup_month.notna() & (rows.month >= rows.signup_month)]
    complete = sorted(set(int(m) for m in complete_months))
    bases = rows[
        (rows.month == rows.signup_month) & rows.month.isin(complete)
    ].client_id.unique()
    eligible = rows[rows.client_id.isin(bases)]
    counts = eligible.groupby(["signup_month", "month"]).client_id.nunique()
    signup_counts = cohort[cohort.isin(complete)].value_counts().sort_index()
    initial = cohort.loc[bases].value_counts().sort_index()
    if initial.empty:
        raise ValueError("가입월 결제를 관측한 코호트가 없습니다")
    width = complete[-1] - int(initial.index.min()) + 1
    table = pd.DataFrame(
        np.nan,
        index=[str(pd.Period(ordinal=int(m), freq="M")) for m in initial.index],
        columns=range(width),
    )
    conversion = []
    for month, total in signup_counts.items():
        first = int(initial.get(month, 0))
        conversion.append(
            {
                "signup_month": str(pd.Period(ordinal=int(month), freq="M")),
                "registrations": int(total),
                "signup_month_payers": first,
                "initial_conversion": first / int(total),
            }
        )
    for month, size in initial.items():
        label = str(pd.Period(ordinal=int(month), freq="M"))
        for age in range(width):
            calendar = int(month) + age
            if calendar in complete:
                table.loc[label, age] = int(counts.get((month, calendar), 0)) / int(
                    size
                )
    return table, conversion


def analyze(root, output):
    """45백만 상품행을 청크로 읽고 고객-월 중복을 제거한다."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    registry = pd.read_csv(
        root / "clients.csv.gz",
        usecols=["client_id", "first_issue_date"],
        dtype={"client_id": str},
    )
    registry["first_issue_date"] = pd.to_datetime(
        registry.first_issue_date, errors="coerce"
    )
    invalid = int(registry.first_issue_date.isna().sum())
    registry = registry.dropna()
    if registry.client_id.duplicated().any():
        raise ValueError("가입 ID 중복을 확인해야 합니다")
    dates = registry.set_index("client_id").first_issue_date
    monthly_cache = root / "valid-customer-months.csv.gz"
    meta_cache = root / "stream-profile.json"
    if monthly_cache.exists() and meta_cache.exists():
        pairs = pd.read_csv(monthly_cache, dtype={"client_id": str})
        profile = json.loads(meta_cache.read_text())
    else:
        pairs_set = set()
        days = set()
        read = 0
        unknown = 0
        before = 0
        invalid_dates = 0
        non_purchase = 0
        for chunk in pd.read_csv(
            root / "purchases.csv.gz",
            usecols=[
                "client_id",
                "transaction_datetime",
                "product_quantity",
                "purchase_sum",
            ],
            dtype={"client_id": str},
            chunksize=250000,
        ):
            timestamps = pd.to_datetime(chunk.transaction_datetime, errors="coerce")
            invalid_dates += int(timestamps.isna().sum())
            day_values = timestamps.dropna().to_numpy().astype("datetime64[D]")
            days.update(np.unique(day_values).tolist())
            signup = chunk.client_id.map(dates)
            unknown += int(signup.isna().sum())
            early = timestamps < signup
            before += int(early.sum())
            is_purchase = (chunk.product_quantity > 0) & (chunk.purchase_sum >= 0)
            non_purchase += int((~is_purchase).sum())
            valid = signup.notna() & timestamps.notna() & (~early) & is_purchase
            months = (
                timestamps[valid].to_numpy().astype("datetime64[M]").astype(np.int64)
            )
            unique = pd.DataFrame(
                {"client_id": chunk.loc[valid, "client_id"].to_numpy(), "month": months}
            ).drop_duplicates()
            pairs_set.update(unique.itertuples(index=False, name=None))
            read += len(chunk)
            if read % 5000000 == 0:
                print(
                    json.dumps(
                        {
                            "processed_item_rows": read,
                            "unique_customer_months": len(pairs_set),
                        }
                    ),
                    flush=True,
                )
        pairs = pd.DataFrame(sorted(pairs_set), columns=["client_id", "month"])
        counts = (
            pd.Series(pd.to_datetime(sorted(days)))
            .dt.to_period("M")
            .value_counts()
            .sort_index()
        )
        complete = [
            int(month.ordinal)
            for month, n in counts.items()
            if n == month.days_in_month
        ]
        profile = {
            "item_rows": read,
            "unique_customer_months": len(pairs),
            "unknown_registration_rows": unknown,
            "before_registration_rows": before,
            "invalid_transaction_dates": invalid_dates,
            "non_purchase_rows": non_purchase,
            "observed_start": str(min(days)),
            "observed_end": str(max(days)),
            "observed_days_per_month": {str(k): int(v) for k, v in counts.items()},
            "complete_month_numbers": complete,
        }
        pairs.to_csv(monthly_cache, index=False, lineterminator="\n")
        meta_cache.write_text(json.dumps(profile, indent=2) + "\n")
    table, conversion = signup_retention(
        dates, pairs, profile["complete_month_numbers"]
    )
    table.to_csv(output / "retention.csv", lineterminator="\n")
    fig, ax = plt.subplots(
        figsize=(max(7, table.shape[1] * 1.5), max(3, table.shape[0] * 0.8))
    )
    sns.heatmap(
        table,
        annot=True,
        fmt=".1%",
        vmin=0,
        vmax=1,
        cmap="Blues",
        mask=table.isna(),
        ax=ax,
    )
    ax.set_facecolor('#d9d9d9')
    ax.set(
        xlabel="months since membership signup",
        ylabel="membership signup month",
        title="Repeat purchase after signup-month purchase",
    )
    fig.tight_layout()
    fig.savefig(output / "retention.png", dpi=160)
    plt.close(fig)
    report = {
        **profile,
        "registrations": len(dates),
        "invalid_registration_dates": invalid,
        "conversion": conversion,
        "retention": {
            index: {
                str(age): None if pd.isna(value) else float(value)
                for age, value in row.items()
            }
            for index, row in table.iterrows()
        },
        "signup_definition": "first_issue_date: first membership card issue; not first observed purchase",
        "denominator": "registered members purchasing in their signup month; conversion reported separately",
        "observation": "only calendar months with every date present globally; later/partial months are NaN",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/registration"))
    parser.add_argument("--output", type=Path, default=Path("outputs/registration"))
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    prepare(args.data, args.download)
    analyze(args.data, args.output)


if __name__ == "__main__":
    main()
