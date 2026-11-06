"""PostgreSQL 상태 점검 리포트 (운영 모니터링 스크립트의 최소 구현).

수집 항목: 연결 수/한도, 캐시 적중률, 슬로우 쿼리 TOP(pg_stat_statements), 사용되지 않는 인덱스,
          dead tuple 비율(vacuum 필요), 장시간 트랜잭션, 데드락/롤백 누적.
임계값을 넘으면 WARN/CRIT 로 표시하고 종료 코드로 알린다(0 정상, 1 경고, 2 심각) -> 스케줄러/알림 연동용.

사용: python tools/monitor_report.py [--out results/monitor_report.md]
"""
import sys

from common import RESULTS, psql

THRESHOLDS = {
    "conn_pct": (70, 90),        # 연결 사용률 %
    "cache_hit_pct": (99, 95),   # 낮을수록 나쁨: 99 미만 경고, 95 미만 심각
    "dead_tuple_pct": (10, 30),  # 테이블 dead tuple 비율 %
    "long_txn_sec": (60, 600),   # 열려 있는 트랜잭션 시간
}
LEVEL = {0: "OK", 1: "WARN", 2: "CRIT"}


def rows(sql):
    return [r.split("|") for r in psql(sql).strip().splitlines() if r.strip()]


def judge(value, name, lower_is_bad=False):
    warn, crit = THRESHOLDS[name]
    if lower_is_bad:
        return 2 if value < crit else 1 if value < warn else 0
    return 2 if value >= crit else 1 if value >= warn else 0


def main():
    out, worst = ["# PostgreSQL 점검 리포트", ""], 0
    checks = []

    used, maxc = (int(x) for x in rows("SELECT count(*), current_setting('max_connections')::int FROM pg_stat_activity WHERE backend_type='client backend'")[0])
    pct = used * 100 / maxc
    checks.append(("연결 사용률", f"{used}/{maxc} ({pct:.0f}%)", judge(pct, "conn_pct")))

    hit = float(rows("SELECT round(100.0*sum(blks_hit)/nullif(sum(blks_hit)+sum(blks_read),0),2) FROM pg_stat_database WHERE datname='lab'")[0][0])
    checks.append(("버퍼 캐시 적중률", f"{hit}%", judge(hit, "cache_hit_pct", True)))

    dl, rb, cm = rows("SELECT deadlocks, xact_rollback, xact_commit FROM pg_stat_database WHERE datname='lab'")[0]
    checks.append(("누적 데드락", f"{dl}건 (롤백 {rb} / 커밋 {cm})", 1 if int(dl) > 0 else 0))

    lt = rows("SELECT coalesce(max(extract(epoch FROM now()-xact_start)),0)::int FROM pg_stat_activity WHERE state<>'idle' AND xact_start IS NOT NULL AND pid<>pg_backend_pid()")[0][0]
    checks.append(("가장 오래 열린 트랜잭션", f"{lt}초", judge(int(lt), "long_txn_sec")))

    out += ["## 요약", "", "| 항목 | 값 | 상태 |", "| --- | --- | --- |"]
    for n, v, lvl in checks:
        out.append(f"| {n} | {v} | {LEVEL[lvl]} |")
        worst = max(worst, lvl)

    out += ["", "## 슬로우 쿼리 TOP 5 (총 실행시간 기준)", "", "| 쿼리(앞 70자) | 호출 | 평균(ms) | 총(ms) | 캐시 미스 블록 |", "| --- | ---: | ---: | ---: | ---: |"]
    for q, calls, mean, total, rd in rows(
            "SELECT replace(left(query,70), E'\\n', ' '), calls, round(mean_exec_time::numeric,2), round(total_exec_time::numeric,0), shared_blks_read "
            "FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname='lab') AND query NOT ILIKE '%pg_stat%' "
            "ORDER BY total_exec_time DESC LIMIT 5"):
        out.append(f"| `{q.replace('|', '/')}` | {calls} | {mean} | {total} | {rd} |")

    out += ["", "## 사용되지 않는 인덱스 (idx_scan = 0, PK/유니크 제외)", ""]
    unused = rows("SELECT s.relname, s.indexrelname, pg_size_pretty(pg_relation_size(s.indexrelid)) FROM pg_stat_user_indexes s "
                  "JOIN pg_index i ON i.indexrelid=s.indexrelid WHERE s.idx_scan=0 AND NOT i.indisunique AND NOT i.indisprimary ORDER BY pg_relation_size(s.indexrelid) DESC")
    out += [f"- {t}.{i} ({sz})" for t, i, sz in unused] or ["- 없음"]
    if unused:
        out.append("\n> 쓰기 비용만 내고 읽기에 안 쓰이는 인덱스 후보. 삭제 전 충분한 기간(월말 배치 등)을 관찰한다.")

    out += ["", "## dead tuple 비율 상위", "", "| 테이블 | live | dead | dead % | 마지막 autovacuum | 상태 |", "| --- | ---: | ---: | ---: | --- | --- |"]
    for t, live, dead, last in rows(
            "SELECT relname, n_live_tup, n_dead_tup, coalesce(to_char(last_autovacuum,'MM-DD HH24:MI'),'-') FROM pg_stat_user_tables "
            "ORDER BY n_dead_tup DESC LIMIT 5"):
        p = int(dead) * 100 / max(int(live) + int(dead), 1)
        lvl = judge(p, "dead_tuple_pct")
        worst = max(worst, lvl)
        out.append(f"| {t} | {live} | {dead} | {p:.1f} | {last} | {LEVEL[lvl]} |")

    out += ["", f"**종합: {LEVEL[worst]}**"]
    text = "\n".join(out)
    path = RESULTS / "monitor_report.md"
    if "--out" in sys.argv:
        path = type(path)(sys.argv[sys.argv.index("--out") + 1])
    path.write_text(text, encoding="utf-8")
    print(text)
    sys.exit(worst)


if __name__ == "__main__":
    main()
