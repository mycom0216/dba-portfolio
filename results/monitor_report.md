# PostgreSQL 점검 리포트

## 요약

| 항목 | 값 | 상태 |
| --- | --- | --- |
| 연결 사용률 | 1/100 (1%) | OK |
| 버퍼 캐시 적중률 | 100.0% | OK |
| 누적 데드락 | 1895건 (롤백 9748 / 커밋 79712) | WARN |
| 가장 오래 열린 트랜잭션 | 0초 | OK |

## 슬로우 쿼리 TOP 5 (총 실행시간 기준)

| 쿼리(앞 70자) | 호출 | 평균(ms) | 총(ms) | 캐시 미스 블록 |
| --- | ---: | ---: | ---: | ---: |
| `SELECT pg_sleep($1)` | 71357 | 12.74 | 909154 | 0 |
| `SELECT $1 FROM wallets WHERE user_id IN ($2, $3) ORDER BY user_id FOR ` | 2000 | 82.65 | 165294 | 0 |
| `UPDATE wallets SET balance_points = balance_points - $1 WHERE user_id ` | 3666 | 44.47 | 163019 | 0 |
| `UPDATE wallets SET balance_points = balance_points - $1 WHERE user_id ` | 3691 | 43.15 | 159258 | 0 |
| `SELECT $1 FROM wallets WHERE user_id IN ($2, $3) ORDER BY user_id FOR ` | 2000 | 75.97 | 151934 | 0 |

## 사용되지 않는 인덱스 (idx_scan = 0, PK/유니크 제외)

- 없음

## dead tuple 비율 상위

| 테이블 | live | dead | dead % | 마지막 autovacuum | 상태 |
| --- | ---: | ---: | ---: | --- | --- |
| wallets | 200000 | 728 | 0.4 | 11-06 04:42 | OK |
| listens | 3000000 | 0 | 0.0 | - | OK |
| users | 200000 | 0 | 0.0 | 11-06 04:42 | OK |
| gifts | 5 | 0 | 0.0 | - | OK |
| donations | 1000000 | 0 | 0.0 | 11-06 04:43 | OK |

**종합: WARN**