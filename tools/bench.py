"""쿼리 튜닝 전/후 실측 (PostgreSQL / MySQL 공용).

  python tools/bench.py pg before        # 인덱스 없는 기준선
  python tools/bench.py pg after         # 04_indexes.sql 적용 후 (+ 재작성 쿼리)
  python tools/bench.py mysql before|after
  python tools/bench.py report           # results/*.json 을 표(markdown)로 출력

각 쿼리를 EXPLAIN ANALYZE 로 워밍업 1회 + 5회 실행해 중앙값(ms)을 쓰고, 실행계획의 접근 방식(어떤 스캔/인덱스)을 같이 저장한다.
쿼리 결과값 자체도 저장해, '재작성' 쿼리가 원본과 같은 결과를 내는지와 두 DB 의 결과가 같은지 검증한다.
"""
import json
import re
import statistics
import sys

from common import RESULTS, ROOT, mysql, psql, split_named_queries

RUNS = 5
SQL_DIR = ROOT / "sql"


def pg_explain(sql):
    out = psql(f"EXPLAIN (ANALYZE, BUFFERS) {sql}", raw=False)
    t = float(re.search(r"Execution Time: ([\d.]+) ms", out).group(1))
    scans = []
    for m in re.finditer(r"(Parallel )?(Index Only Scan|Bitmap Index Scan|Index Scan|Bitmap Heap Scan|Seq Scan)(?: using (\w+))?(?: on (\w+))?", out):
        s = f"{m.group(2)}{'[' + m.group(3) + ']' if m.group(3) else ''}{' on ' + m.group(4) if m.group(4) else ''}"
        if s not in scans:
            scans.append(s)
    buf = re.search(r"Buffers: shared (?:hit=(\d+))?(?: )?(?:read=(\d+))?", out)
    reads = int(buf.group(1) or 0) + int(buf.group(2) or 0) if buf else None
    return t, scans, reads, out


def my_explain(sql):
    out = mysql(f"EXPLAIN ANALYZE {sql}")
    out = out.replace("\\n", "\n")  # --batch 모드는 개행을 \n 으로 이스케이프한다
    t = float(re.search(r"actual time=[\d.]+\.\.([\d.]+)", out).group(1))
    scans = []
    for m in re.finditer(r"->\s*((?:Covering )?[Ii]ndex (?:range scan|lookup|scan)|Table scan|Single-row index lookup) on (\w+)(?: using (\w+))?", out):
        s = f"{m.group(1)}{'[' + m.group(3) + ']' if m.group(3) else ''} on {m.group(2)}"
        if s not in scans:
            scans.append(s)
    return t, scans, None, out


def run_query(engine, sql):
    explain = pg_explain if engine == "pg" else my_explain
    explain(sql)  # warm-up
    times, last = [], None
    for _ in range(RUNS):
        t, scans, reads, plan = explain(sql)
        times.append(t)
        last = (scans, reads, plan)
    result = (psql(sql) if engine == "pg" else mysql(sql)).strip()
    return {"ms": round(statistics.median(times), 2), "min": round(min(times), 2), "max": round(max(times), 2),
            "scans": last[0], "buffers": last[1], "result": result, "plan": last[2]}


def main():
    if sys.argv[1] == "report":
        return report()
    engine, label = sys.argv[1], sys.argv[2]
    d = SQL_DIR / ("pg" if engine == "pg" else "mysql")
    queries = split_named_queries(d / "03_queries.sql")
    if label == "after":
        queries += [(n + "r", desc, q) for n, desc, q in split_named_queries(d / "05_queries_rewritten.sql")]
    out = {}
    for name, desc, sql in queries:
        r = run_query(engine, sql)
        r["desc"] = desc
        out[name] = r
        print(f"{engine} {label} {name}: {r['ms']:>9.2f} ms  {', '.join(r['scans'])}", flush=True)
    (RESULTS / f"{engine}_{label}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


def report():
    def load(n):
        p = RESULTS / f"{n}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    for eng, title in (("pg", "PostgreSQL 16.9"), ("mysql", "MySQL 8.4.6")):
        b, a = load(f"{eng}_before"), load(f"{eng}_after")
        if not (b and a):
            continue
        print(f"\n### {title}\n\n| 쿼리 | 튜닝 전 (ms) | 인덱스만 (ms) | 인덱스+재작성 (ms) | 개선(최종) | 최종 접근 방식 |\n| --- | ---: | ---: | ---: | ---: | --- |")
        for name, r in b.items():
            rw = a.get(name + "r")
            best = rw or a[name]
            x = r["ms"] / best["ms"] if best["ms"] else float("inf")
            print(f"| {name} {r['desc'].split('(')[0].strip()} | {r['ms']:.2f} | {a[name]['ms']:.2f} | "
                  f"{(format(rw['ms'], '.2f') if rw else '-')} | {x:.0f}배 | {'; '.join(best['scans'])} |")
        for name in b:
            if name + "r" in a:
                same = a[name]["result"] == a[name + "r"]["result"] == b[name]["result"]
                print(f"\n{name} 재작성 결과가 원본과 동일한가: {same}")
    pb, mb = load("pg_before"), load("mysql_before")
    if pb and mb:
        # psql 은 '|' 구분 + timestamptz 에 '+00' 이 붙고, mysql 은 탭 구분이다 -> 표기를 맞춘 뒤 비교
        # 추가: PostgreSQL 은 소수 끝의 0 을 생략(…47.05243)하고 MySQL 은 6자리(…47.052430)로 출력 -> 6자리로 맞춘다
        pad = lambda s: re.sub(r"(\d\d:\d\d:\d\d)\.(\d+)", lambda m: f"{m.group(1)}.{m.group(2).ljust(6, '0')}", s)
        norm = lambda s: pad(s.replace("\t", "|").replace("+00", "")).strip()
        same = {k: norm(pb[k]["result"]) == norm(mb[k]["result"]) for k in pb}
        print("\n결과값 일치(PG vs MySQL, 표기 정규화 후):", same)
        for k, ok in same.items():
            if not ok:
                print(f"  {k} PG   : {norm(pb[k]['result'])[:300]}\n  {k} MySQL: {norm(mb[k]['result'])[:300]}")


if __name__ == "__main__":
    main()
