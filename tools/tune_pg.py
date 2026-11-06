"""PostgreSQL 튜닝 실험 전체를 처음부터 재현한다: 인덱스 제거 -> 기준선 측정 -> 인덱스 생성(시간·크기) -> 재측정 -> 쓰기 비용 측정.

사용: python tools/tune_pg.py
"""
import json
import re
import statistics
import subprocess
import sys
import time

from common import RESULTS, ROOT, psql

PY = sys.executable
IDX = ["idx_donations_created", "idx_listens_user_joined", "idx_listens_live", "idx_donations_broadcast"]


def bench(label):
    subprocess.run([PY, str(ROOT / "tools" / "bench.py"), "pg", label], check=True)


def timed_statements(sqlfile):
    """CREATE INDEX 문을 하나씩 실행하며 걸린 시간을 잰다."""
    stmts = [s.strip() for s in re.sub(r"--.*", "", sqlfile.read_text(encoding="utf-8")).split(";") if s.strip()]
    out = {}
    for s in stmts:
        t = time.perf_counter()
        psql(s)
        ms = (time.perf_counter() - t) * 1000
        m = re.match(r"CREATE INDEX (\w+)", s)
        if m:
            out[m.group(1)] = round(ms)
    return out


def write_cost(n=300_000, rounds=3):
    """같은 행 수를 인덱스 없는 테이블/인덱스 2개 있는 테이블에 넣는 시간 비교 (인덱스 = 읽기 이득의 대가)."""
    gen = f"""INSERT INTO {{t}}
        SELECT g, 1 + floor(100000 * power(random(),1.8))::bigint, 1 + floor(200000*random())::bigint, 1,
               10, timestamptz '2026-01-01' + random() * interval '300 days'
        FROM generate_series(1, {n}) g"""
    res = {"PK만": [], "PK+인덱스2개": []}
    for _ in range(rounds):
        for label, extra in (("PK만", ""), ("PK+인덱스2개",
                             "CREATE INDEX ON {t} (created_at) INCLUDE (broadcast_id, points); "
                             "CREATE INDEX ON {t} (broadcast_id) INCLUDE (sender_id, points);")):
            psql("DROP TABLE IF EXISTS wc_t; CREATE TABLE wc_t (LIKE donations INCLUDING DEFAULTS); "
                 "ALTER TABLE wc_t ADD PRIMARY KEY (donation_id);" + extra.format(t="wc_t"))
            out = psql("EXPLAIN (ANALYZE) " + gen.format(t="wc_t"))
            res[label].append(float(re.search(r"Execution Time: ([\d.]+) ms", out).group(1)))
    psql("DROP TABLE IF EXISTS wc_t")
    return {k: round(statistics.median(v)) for k, v in res.items()} | {"rows": n}


def main():
    for i in IDX:
        psql(f"DROP INDEX IF EXISTS {i}")
    psql("VACUUM (ANALYZE) donations; ")
    psql("VACUUM (ANALYZE) listens; ")
    bench("before")
    build = timed_statements(ROOT / "sql" / "pg" / "04_indexes.sql")
    sizes = {r.split("|")[0]: r.split("|")[1] for r in psql(
        "SELECT indexrelid::regclass, pg_size_pretty(pg_relation_size(indexrelid)) FROM pg_index "
        "WHERE indrelid IN ('donations'::regclass,'listens'::regclass) ORDER BY 1").strip().splitlines()}
    bench("after")
    wc = write_cost()
    info = {"index_build_ms": build, "index_sizes": sizes, "write_cost_ms": wc}
    (RESULTS / "pg_tuning_extra.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
