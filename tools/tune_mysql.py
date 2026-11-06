"""MySQL 튜닝 실험: 적재(PG 와 동일 데이터) -> 기준선 -> 인덱스 생성(시간·크기) -> 재측정 -> 쓰기 비용.

사용: python tools/tune_mysql.py [--skip-load]
"""
import json
import re
import statistics
import subprocess
import sys
import time

from common import RESULTS, ROOT, mysql

PY = sys.executable
IDX = [("donations", "idx_donations_created"), ("listens", "idx_listens_user_joined"),
       ("listens", "idx_listens_live"), ("donations", "idx_donations_broadcast")]


def run(script, *args):
    subprocess.run([PY, str(ROOT / "tools" / script), *args], check=True)


def timed_statements(sqlfile):
    stmts = [s.strip() for s in re.sub(r"--.*", "", sqlfile.read_text(encoding="utf-8")).split(";") if s.strip()]
    out = {}
    for s in stmts:
        t = time.perf_counter()
        mysql(s)
        m = re.match(r"CREATE INDEX (\w+)", s)
        if m:
            out[m.group(1)] = round((time.perf_counter() - t) * 1000)
    return out


def index_sizes():
    rows = mysql("SELECT table_name, index_name, ROUND(stat_value*@@innodb_page_size/1024/1024,1) "
                 "FROM mysql.innodb_index_stats WHERE database_name='lab' AND table_name IN ('listens','donations') "
                 "AND stat_name='size' ORDER BY 1,2").strip().splitlines()
    return {f"{r.split(chr(9))[0]}.{r.split(chr(9))[1]}": f"{r.split(chr(9))[2]} MB" for r in rows}


def write_cost(n=300_000, rounds=3):
    """PostgreSQL 실험과 같은 조건: PK 만 vs PK + 보조 인덱스 2개로 n 행 삽입."""
    # 재귀 CTE 로 행을 만들어 넣는다. 데이터 '생성' 시간은 SELECT COUNT(*) 로 따로 재서 삽입 시간에서 뺀다.
    sel = (f"SELECT seq, 1 + FLOOR(100000*POW(RAND(),1.8)), 1 + FLOOR(200000*RAND()), 1, 10, "
           f"TIMESTAMP('2026-01-01') + INTERVAL FLOOR(RAND()*300*86400) SECOND "
           f"FROM (WITH RECURSIVE s(seq) AS (SELECT 1 UNION ALL SELECT seq+1 FROM s WHERE seq < {n}) SELECT seq FROM s) x")
    ins = "INSERT INTO wc_t " + sel
    t = time.perf_counter()
    mysql("SET SESSION cte_max_recursion_depth=1000000; SELECT COUNT(*) FROM (" + sel + ") y")
    gen_ms = (time.perf_counter() - t) * 1000
    res = {"PK만": [], "PK+인덱스2개": []}
    for _ in range(rounds):
        for label, extra in (("PK만", ""), ("PK+인덱스2개",
                             "CREATE INDEX i1 ON wc_t (created_at, broadcast_id, points); "
                             "CREATE INDEX i2 ON wc_t (broadcast_id, sender_id, points);")):
            mysql("DROP TABLE IF EXISTS wc_t; CREATE TABLE wc_t (donation_id BIGINT PRIMARY KEY, broadcast_id BIGINT NOT NULL, "
                  "sender_id BIGINT NOT NULL, gift_id INT NOT NULL, points INT NOT NULL, created_at DATETIME(6) NOT NULL); " + extra)
            t = time.perf_counter()
            mysql("SET SESSION cte_max_recursion_depth=1000000; " + ins)
            res[label].append((time.perf_counter() - t) * 1000 - gen_ms)
    mysql("DROP TABLE IF EXISTS wc_t")
    return {k: round(statistics.median(v)) for k, v in res.items()} | {"rows": n}


def main():
    if "--skip-load" not in sys.argv:
        run("load_mysql.py")
    for t, i in IDX:  # 재실행 대비: 있으면 지운다
        exists = mysql(f"SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema='lab' AND index_name='{i}'").strip()
        if exists != "0":
            mysql(f"DROP INDEX {i} ON {t}")
    mysql("ANALYZE TABLE donations, listens")
    run("bench.py", "mysql", "before")
    build = timed_statements(ROOT / "sql" / "mysql" / "04_indexes.sql")
    sizes = index_sizes()
    run("bench.py", "mysql", "after")
    wc = write_cost()
    info = {"index_build_ms": build, "index_sizes": sizes, "write_cost_ms": wc}
    (RESULTS / "mysql_tuning_extra.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
