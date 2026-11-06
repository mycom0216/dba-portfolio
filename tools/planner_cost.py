"""PostgreSQL 플래너의 비용 모델을 소스 코드(src/backend/optimizer/path/costsize.c)에서 읽은 공식으로 직접 계산해 EXPLAIN 과 대조한다.

 검증 1  Seq Scan 비용 공식:  relpages*seq_page_cost + reltuples*(cpu_tuple_cost + (WHERE 조건 수)*cpu_operator_cost)
         -> 계산값과 EXPLAIN 의 cost 가 일치하는가
 검증 2  조회 범위(선택도)를 키우면 플래너가 언제 Index Only Scan -> Seq Scan 으로 바꾸는가 (두 계획의 비용과 교차점)

사용: python tools/planner_cost.py       (PostgreSQL 기동 + 시드 + 인덱스 적용 상태)
"""
import json
import re

from cluster import run
from common import PG_PORT, RESULTS, psql

END = "2026-10-28"
NO_PARALLEL = "SET max_parallel_workers_per_gather = 0"  # 병렬 계획이 끼면 공식이 달라지므로 끈다
SEQ_ONLY = ["SET enable_indexscan = off", "SET enable_bitmapscan = off", "SET enable_indexonlyscan = off"]
INDEX_ONLY = ["SET enable_seqscan = off"]


def explain(sql, settings=()):
    """SET 들과 EXPLAIN 을 같은 세션에서 실행 (psql 의 -c 를 여러 번 주면 한 세션에서 순서대로 실행된다)."""
    args = ["-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-d", "lab"]
    for s in (NO_PARALLEL, *settings):
        args += ["-c", s]
    out = run("psql", args + ["-c", "EXPLAIN " + sql], port=PG_PORT).stdout
    out = "\n".join(l for l in out.splitlines() if l.strip() and l.strip() != "SET")
    m = re.search(r"(?:->\s*)?(.+?)\s+\(cost=([\d.]+)\.\.([\d.]+) rows=(\d+)", out.splitlines()[0])
    scan = re.search(r"(Index Only Scan|Index Scan|Bitmap Heap Scan|Seq Scan)", out)  # 최상위는 Aggregate 라서 스캔 노드를 따로 찾는다
    return {"scan": scan.group(1) if scan else "?", "total_cost": float(m.group(3)), "est_rows": int(m.group(4))}, out


def guc(name):
    return float(psql(f"SHOW {name}").split()[0])


def main():
    params = {k: guc(k) for k in ("seq_page_cost", "random_page_cost", "cpu_tuple_cost", "cpu_index_tuple_cost", "cpu_operator_cost")}
    pages, tuples = (float(x) for x in psql("SELECT relpages, reltuples FROM pg_class WHERE relname='donations'").split("|"))

    # 검증 1: WHERE created_at >= a AND created_at < b  -> 조건 2개
    sql = "SELECT count(*) FROM donations WHERE created_at >= '2026-10-01' AND created_at < '2026-10-08'"
    _, text = explain(sql, SEQ_ONLY)
    scan = re.search(r"Seq Scan on donations\s+\(cost=([\d.]+)\.\.([\d.]+) rows=(\d+)", text)
    shown = float(scan.group(2))
    predicted = pages * params["seq_page_cost"] + tuples * (params["cpu_tuple_cost"] + 2 * params["cpu_operator_cost"])
    v1 = {"params": params, "relpages": pages, "reltuples": tuples, "predicted_total_cost": round(predicted, 2),
          "explain_total_cost": shown, "match_within_1pct": abs(predicted - shown) < 0.01 * shown}

    # 검증 2: 조회 범위를 키우며 플래너의 선택과 두 계획의 비용을 비교
    rows = []
    for days in (1, 7, 30, 60, 90, 120, 180, 300):
        q = (f"SELECT count(*) FROM donations WHERE created_at >= timestamptz '{END}' - interval '{days} days' "
             f"AND created_at < timestamptz '{END}'")
        chosen, _ = explain(q)
        seq, _ = explain(q, SEQ_ONLY)
        idx, _ = explain(q, INDEX_ONLY)
        rows.append({"days": days, "est_rows": chosen["est_rows"], "chosen_plan": chosen["scan"],
                     "seq_scan_cost": seq["total_cost"], "index_only_cost": idx["total_cost"]})
    out = {"validation1_seq_scan_formula": v1, "validation2_crossover": rows}
    (RESULTS / "pg_planner_cost.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
