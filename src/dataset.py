"""고정 공개 revision에서 재현 가능한 거래/상품/이미지 표본을 준비한다."""

import argparse
import collections
import concurrent.futures
import csv
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

REVISION = "acde210b0090be673abdba5f989c48925c856f78"
BASE = f"https://huggingface.co/datasets/einrafh/hnm-fashion-recommendations-data/resolve/{REVISION}/data/raw/"
TOTAL_BYTES = 3488002253
CHUNK_BYTES = 1048576


def sha256(path):
    """파일의 SHA-256을 반환한다."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_range(index, count, output, cache=None):
    """완전한 원본 행만 남긴 검증된 HTTP Range 하나를 읽는다."""
    start = (TOTAL_BYTES - CHUNK_BYTES) * index // max(count - 1, 1)
    end = start + CHUNK_BYTES - 1
    path = output / f"part-{index:02d}.csv"
    cached = cache / path.name if cache else None
    use_cache = False
    if cached and cached.is_file() and (cache / "source-manifest.json").is_file():
        manifest = json.loads((cache / "source-manifest.json").read_text())
        records = manifest.get("ranges", [])
        use_cache = (
            manifest.get("revision") == REVISION
            and index < len(records)
            and records[index]["start"] == start
            and sha256(cached) == records[index]["sha256"]
        )
    if use_cache:
        shutil.copyfile(cached, path)
    else:
        request = urllib.request.Request(
            BASE + f"transactions_train.csv?offset={start}",
            headers={"Range": f"bytes={start}-{end}"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            if response.status != 206 or not response.headers.get(
                "Content-Range", ""
            ).startswith(f"bytes {start}-"):
                raise ValueError("서버가 요청한 Range를 반환하지 않았습니다")
            body = response.read(CHUNK_BYTES + 1)
        if len(body) != CHUNK_BYTES:
            raise ValueError("거래 표본 바이트 수가 다릅니다")
        path.write_bytes(body)
    lines = path.read_text().splitlines()[1:-1]
    rows = [
        r
        for r in csv.reader(lines)
        if len(r) == 5 and len(r[1]) == 64 and len(r[2]) == 10
    ]
    return rows, {
        "part": index,
        "start": start,
        "end": end,
        "sha256": sha256(path),
        "rows": len(rows),
    }


def fetch_image(article, output, cache=None):
    """거래와 같은 상품 ID의 원본 사진만 받는다. 실패를 별도 기록한다."""
    if len(article) != 10 or not article.isdecimal():
        raise ValueError("잘못된 상품 ID")
    url = BASE + f"images/{article[:3]}/{article}.jpg"
    path = output / (article + ".jpg")
    cached = cache / "images" / path.name if cache else None
    try:
        if cached and cached.is_file():
            shutil.copyfile(cached, path)
        else:
            with urllib.request.urlopen(url, timeout=40) as response:
                path.write_bytes(response.read())
        return {
            "article_id": article,
            "url": url,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "status": "downloaded",
        }
    except (OSError, ValueError) as error:
        return {
            "article_id": article,
            "url": url,
            "status": "failed",
            "error": str(error),
        }


def prepare(output, parts=32, top_products=128, cache=None):
    """시간 구간 표본과 인기 상품의 교집합을 구성하고 원본 출처를 남긴다."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    images = output / "images"
    images.mkdir(exist_ok=True)
    cache = Path(cache) if cache else None
    if not 1 <= parts <= 128 or top_products < 1:
        raise ValueError("표본 수/상품 수 범위를 확인하세요")
    rows = []
    ranges = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for part, record in pool.map(
            lambda i: fetch_range(i, parts, output, cache), range(parts)
        ):
            rows.extend(part)
            ranges.append(record)
    article_path = output / "articles.csv"
    if cache and (cache / "articles.csv").is_file():
        shutil.copyfile(cache / "articles.csv", article_path)
    else:
        with (
            urllib.request.urlopen(BASE + "articles.csv", timeout=90) as response,
            article_path.open("wb") as stream,
        ):
            shutil.copyfileobj(response, stream)
    ids = [
        article
        for article, _ in collections.Counter(r[2] for r in rows).most_common(
            top_products
        )
    ]
    with article_path.open() as stream:
        articles = {
            r["article_id"]: r
            for r in csv.DictReader(stream)
            if r["article_id"] in set(ids)
        }
    fields = [
        "order_date",
        "customer_id",
        "article_id",
        "price",
        "sales_channel_id",
        "product_name",
        "category",
        "colour",
        "department",
        "detail_desc",
    ]
    selected = []
    for row in rows:
        if row[2] not in articles:
            continue
        article = articles[row[2]]
        selected.append(
            dict(
                zip(
                    fields,
                    row
                    + [
                        article["prod_name"],
                        article["product_type_name"],
                        article["colour_group_name"],
                        article["department_name"],
                        article["detail_desc"],
                    ],
                )
            )
        )
    with (output / "analysis_transactions.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(selected)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        photos = list(
            pool.map(lambda article: fetch_image(article, images, cache), ids)
        )
    result = {
        "revision": REVISION,
        "raw_rows": len(rows),
        "selected_rows": len(selected),
        "products": len(ids),
        "images_downloaded": sum(p["status"] == "downloaded" for p in photos),
        "images_failed": sum(p["status"] == "failed" for p in photos),
        "ranges": ranges,
        "articles_sha256": sha256(article_path),
        "selected_csv_sha256": sha256(output / "analysis_transactions.csv"),
    }
    if not result["images_downloaded"]:
        raise ValueError("읽을 수 있는 사진을 확보하지 못했습니다")
    (output / "source-manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    (output / "image-manifest.json").write_text(json.dumps(photos, indent=2) + "\n")
    return result


def main():
    """분석 입력을 준비하는 CLI."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data"))
    parser.add_argument("--parts", type=int, default=32)
    parser.add_argument("--top-products", type=int, default=128)
    parser.add_argument("--cache", type=Path)
    args = parser.parse_args()
    result = prepare(args.output, args.parts, args.top_products, args.cache)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "ranges"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
