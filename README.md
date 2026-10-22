# 이커머스 멀티 모달 데이터 분석 및 RFM 비즈니스 인사이트 파이프라인 구축

상품 이미지/텍스트/가격과 실제 거래를 연결하고 EDA, RFM, 코호트, 인터랙티브 시각화를 수행합니다.

## 실행 환경

미션 전용 격리 환경에서 수행합니다. 실제 버전과 데이터 출처는 준비 후 기록합니다.

## 진행 상태

데이터 확보와 환경 준비 중입니다. 실제 실행 결과를 항목별로 추가합니다.

## 거래와 상품 데이터

H&M Personalized Fashion Recommendations 공개 미러의 커밋 `acde210b0090be673abdba5f989c48925c856f78`에서 상품 메타데이터와 실제 거래를 확보했습니다. 3.49GB 거래 전체 중 일정한 바이트 간격의 1MiB 구간 32개를 읽고 경계의 불완전한 레코드를 제거했습니다. 표본은 시간 구간을 분산한 것이며 고객 전체 거래 이력이라고 해석하지 않습니다.

```text
range 0 rows 9554
range 1 rows 9556
range 2 rows 9555
range 3 rows 9558
range 4 rows 9549
range 5 rows 9550
range 6 rows 9556
range 7 rows 9548
range 8 rows 9547
range 9 rows 9558
range 10 rows 9555
range 11 rows 9549
range 12 rows 9553
range 13 rows 9551
range 14 rows 9555
range 15 rows 9557
range 16 rows 9558
range 17 rows 9555
range 18 rows 9562
range 19 rows 9559
range 20 rows 9563
range 21 rows 9562
range 22 rows 9565
range 23 rows 9563
range 24 rows 9550
range 25 rows 9557
range 26 rows 9554
range 27 rows 9555
range 28 rows 9549
range 29 rows 9552
range 30 rows 9552
range 31 rows 9554
DONE 305761 transactions 36127865 article bytes
```

출처: [원 데이터 안내](https://data.hmgroup.com/), [공개 미러](https://huggingface.co/datasets/einrafh/hnm-fashion-recommendations-data). 이미지와의 연결 및 결측/분포 분석은 이어서 수행합니다. 원본 표본과 Range별 SHA-256은 실습 데이터에 보존합니다.
