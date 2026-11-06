# 라이브 오디오 서비스 DB 운영 실험 (PostgreSQL · MySQL)

스푼랩스 DBA(신입/경력) 공고의 업무 — **스키마 설계, 쿼리 튜닝과 부하 검증, 트랜잭션 동시성, 모니터링, 운영 자동화, 파티셔닝·복제·복구** — 을
가상의 라이브 오디오 서비스(청취·후원·포인트)로 실험한 프로젝트입니다.

> **먼저 읽어야 할 한계**: 데이터는 전부 직접 만든 합성 데이터(약 450만 행)이고, 스푼랩스의 실제 스키마·트래픽과 무관합니다.
> 수치는 개인 PC 1대에서 잰 값이라 '튜닝 전/후의 상대 비교'로만 읽어야 합니다. AWS 운영은 다루지 않았습니다.

## 구성
| 경로 | 내용 |
|---|---|
| `sql/pg/`, `sql/mysql/` | 스키마, 시드(setseed 로 재현 가능) + 분포 검증, 튜닝 대상 쿼리, 인덱스, 재작성 쿼리, pgbench 동시성 스크립트 |
| `tools/setup_pg.py`, `tools/setup_mysql.py` | 포터블 DB 초기화·기동 (PG 는 시간대 UTC 고정) |
| `tools/bench.py`, `tune_pg.py`, `tune_mysql.py`, `load_mysql.py` | 튜닝 전/후 측정, PG→MySQL 동일 데이터 적재·검증 |
| `tools/concurrency.py`, `mysql_concurrency.py` | lost update / 격리수준 / 데드락 (PG: pgbench, MySQL: PyMySQL) |
| `tools/monitor_report.py`, `backup_verify.py` | 점검 리포트(임계값, 종료 코드), 백업→복구→대조 |
| `tools/partition_exp.py` | 월 단위 range 파티션: 프루닝, DELETE vs DROP PARTITION |
| `tools/replication_exp.py`, `cluster.py` | 스트리밍 복제, 비동기/동기 장애 조치 5라운드 (유실·전환 시간) |
| `tools/pitr_exp.py` | WAL 아카이브 + 베이스 백업으로 시점 복구 |
| `tools/planner_cost.py` | 소스(costsize.c)의 Seq Scan 비용 공식을 EXPLAIN 과 대조, 인덱스↔풀스캔 교차점 |
| `tools/orm_exp.py` | SQLAlchemy N+1, ORM 의 non-sargable 필터 |
| `tools/run_all.py` | `core` / `extra` / 전체 실험 직렬 재실행 |
| `results/` | 실측 결과(JSON/MD) |
| `SETUP.md` | 재현 방법과 직접 겪은 함정 |

## 핵심 결과
| 주제 | 결과 |
|---|---|
| 쿼리 튜닝 (PG) | 5개 쿼리 54~94ms → 0.2~7ms. 함수로 감싼 조건(Q4)은 인덱스로 안 풀려 범위 조건으로 재작성 |
| 동시성 | 읽고-계산-쓰기: PG READ COMMITTED 에서 차감 49.6% 소실, **MySQL 은 기본 REPEATABLE READ 에서도 약 52% 소실(오류 없음)**, PG RR 은 직렬화 실패로 반려 |
| 데드락 | 잠금 순서 고정으로 PG 955→0건, MySQL 513→0건 |
| 파티셔닝 | 인덱스 없을 때 조회 약 4배, 인덱스 있으면 이득 없음. 이득은 오래된 데이터 삭제(dead tuple·VACUUM 없음) |
| 복제·장애 조치 | 5회 장애 조치, 커밋 응답받은 행 유실 0. 동기 복제 TPS 약 43% 감소. 같은 PC라 비동기 RPO 위험은 재현 못 함 |
| PITR | 지운 75,000행을 사고 직전 시각으로 전부 복구 (복구 4.4초) |
| 소스 분석 | Seq Scan 비용 공식 계산값 23,334 = EXPLAIN 23,334 |
| ORM | N+1 쿼리 1,146개(350ms) → selectinload 5개(26ms) |
| 재현 | DB 재설치 후 전체 재실행 통과, 시간대 설정 누락 버그 발견·수정 |

자세한 해석과 면접 예상 질문은 포트폴리오 문서에 있습니다.
