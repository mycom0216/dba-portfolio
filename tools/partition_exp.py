"""파티셔닝 실험: donations 를 월 단위 range 파티션으로 나눴을 때 (1) 조회 (2) 오래된 데이터 삭제가 어떻게 달라지는가.

비교 대상은 같은 데이터를 담은 두 복사본이다 (원본 donations 는 건드리지 않는다).
  donations_np : 비분할 (PK 만)
  donations_p  : 월 단위 range 파티션 10개 (PK = donation_id, created_at -- 파티션 키를 PK 에 포함해야 한다)

사용: python tools/partition_exp.py       (PostgreSQL 기동 + 시드 완료 상태)
"""
import json
import re
import statistics
import time

from common import RESULTS, psql

RUNS = 5
MONTHS = [(2026, m) for m in range(1, 11)]  # 데이터 범위: 2026-01-01 ~ 2026-10-27 (UTC) -> 월 파티션 10개

Q = {
    "Q1 최근 7일 후원 합계 상위 방송": "SELECT broadcast_id, SUM(points) AS t FROM {t} WHERE created_at >= '2026-10-01' AND created_at < '2026-10-08' "
                                  "GROUP BY broadcast_id ORDER BY t DESC, broadcast_id LIMIT 10",
    "Q6 6월 한 달 건수·합계": "SELECT count(*), sum(points) FROM {t} WHERE created_at >= '2026-06-01' AND created_at < '2026-07-01'",
}


def month_bounds(y, m):
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y}-{m:02d}-01", f"{ny}-{nm:02d}-01"


def timed(sql):
    t = time.perf_counter()
    psql(sql)
    return round((time.perf_counter() - t) * 1000)


def explain(sql):
    out = psql("EXPLAIN (ANALYZE, BUFFERS) " + sql)
    ms = float(re.search(r"Execution Time: ([\d.]+) ms", out).group(1))
    parts = set(re.findall(r"donations_p_\d{4}_\d{2}", out))
    return ms, len(parts)


def measure(table):
    res = {}
    for name, tpl in Q.items():
        sql = tpl.format(t=table)
        explain(sql)  # warm-up
        runs = [explain(sql) for _ in range(RUNS)]
        res[name] = {"ms": round(statistics.median(r[0] for r in runs), 2), "partitions_scanned": runs[-1][1]}
    return res


def main():
    out = {}
    psql("DROP TABLE IF EXISTS donations_np, donations_p CASCADE")
    psql("CREATE TABLE donations_np (LIKE donations INCLUDING DEFAULTS); ALTER TABLE donations_np ADD PRIMARY KEY (donation_id)")
    psql("CREATE TABLE donations_p (LIKE donations INCLUDING DEFAULTS) PARTITION BY RANGE (created_at)")
    for y, m in MONTHS:
        lo, hi = month_bounds(y, m)
        psql(f"CREATE TABLE donations_p_{y}_{m:02d} PARTITION OF donations_p FOR VALUES FROM ('{lo}') TO ('{hi}')")
    psql("ALTER TABLE donations_p ADD PRIMARY KEY (donation_id, created_at)")

    out["load_ms"] = {"비분할": timed("INSERT INTO donations_np SELECT * FROM donations"),
                      "파티션": timed("INSERT INTO donations_p SELECT * FROM donations")}
    psql("VACUUM (ANALYZE) donations_np"); psql("VACUUM (ANALYZE) donations_p")
    out["rows"] = {"비분할": int(psql("SELECT count(*) FROM donations_np")), "파티션": int(psql("SELECT count(*) FROM donations_p"))}
    assert out["rows"]["비분할"] == out["rows"]["파티션"]
    out["partition_rows"] = {r.split("|")[0]: int(r.split("|")[1]) for r in psql(
        "SELECT tableoid::regclass::text, count(*) FROM donations_p GROUP BY 1 ORDER BY 1").strip().splitlines()}

    out["no_index"] = {"비분할": measure("donations_np"), "파티션": measure("donations_p")}

    out["index_build_ms"] = {
        "비분할": timed("CREATE INDEX idx_np_created ON donations_np (created_at) INCLUDE (broadcast_id, points)"),
        "파티션": timed("CREATE INDEX idx_p_created ON donations_p (created_at) INCLUDE (broadcast_id, points)")}
    psql("VACUUM (ANALYZE) donations_np"); psql("VACUUM (ANALYZE) donations_p")
    out["with_index"] = {"비분할": measure("donations_np"), "파티션": measure("donations_p")}

    # 오래된 2개월(2026-01, 2026-02) 삭제: DELETE vs 파티션 DETACH+DROP
    purge_rows = int(psql("SELECT count(*) FROM donations_np WHERE created_at < '2026-03-01'"))
    del_ms = timed("DELETE FROM donations_np WHERE created_at < '2026-03-01'")
    dead = int(psql("SELECT n_dead_tup FROM pg_stat_user_tables WHERE relname='donations_np'"))
    size_after_delete = psql("SELECT pg_size_pretty(pg_total_relation_size('donations_np'))").strip()
    vac_ms = timed("VACUUM donations_np")
    t = time.perf_counter()
    for part in ("donations_p_2026_01", "donations_p_2026_02"):
        psql(f"ALTER TABLE donations_p DETACH PARTITION {part}; DROP TABLE {part}")
    drop_ms = round((time.perf_counter() - t) * 1000)
    out["purge"] = {"rows_removed": purge_rows, "DELETE_ms": del_ms, "dead_tuples_after_delete": dead,
                    "size_after_delete(공간 회수 전)": size_after_delete, "VACUUM_ms": vac_ms, "DETACH_DROP_ms": drop_ms,
                    "rows_left": {"비분할": int(psql("SELECT count(*) FROM donations_np")), "파티션": int(psql("SELECT count(*) FROM donations_p"))}}
    assert out["purge"]["rows_left"]["비분할"] == out["purge"]["rows_left"]["파티션"]

    psql("DROP TABLE IF EXISTS donations_np, donations_p CASCADE")  # 실험용 복사본 정리 (원본 donations 는 그대로)
    (RESULTS / "pg_partition.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
