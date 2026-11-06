"""스트리밍 복제 + 장애 조치 실험 (한 PC 안에서 포트 두 개로 primary/standby 를 흉내).

각 라운드:
  1) primary 의 동기/비동기 모드 설정 -> 2) pg_basebackup 으로 standby 생성 -> 3) 쓰기 부하 + 복제 지연 측정
  4) primary 를 비정상 종료(pg_ctl stop -m immediate, 크래시와 같은 효과) -> 5) standby promote -> 6) 유실 건수·전환 시간 측정
라운드가 끝나면 승격된 standby 가 새 primary 가 되고, 옛 primary 디렉터리는 지우고 새 standby 로 다시 만든다.

'유실' = 클라이언트가 커밋 성공 응답을 받았는데 승격된 서버에 없는 행. 비동기 복제의 RPO 가 0 이 아님을 숫자로 본다.

사용: python tools/replication_exp.py   (PostgreSQL 기동 + 시드 완료, psycopg 설치 필요: pip install "psycopg[binary]")
주의: 끝나면 데이터가 어느 디렉터리에 있는지 바뀐다(pgdata <-> pgstandby). 마지막에 두 인스턴스를 모두 정지한다.
"""
import json
import statistics
import threading
import time

import psycopg

from cluster import psql, rmtree, run, running, start, stop, wait_for
from common import LAB, PG_DATA, PG_PORT, RESULTS

A = {"dir": PG_DATA, "port": PG_PORT, "log": LAB / "pg.log"}
B = {"dir": LAB / "pgstandby", "port": PG_PORT + 1, "log": LAB / "pgstandby.log"}
RUN_SECONDS = 6


def alter_system(port, stmt):
    """ALTER SYSTEM 은 트랜잭션 블록 안에서 못 쓴다: psql -c 에 문장을 ';' 로 이어 보내면 한 블록이 되므로 따로 보낸다."""
    psql(port, stmt, db="postgres")
    psql(port, "SELECT pg_reload_conf()", db="postgres")


def build_standby(primary, standby, sync):
    stop(standby["dir"])
    rmtree(standby["dir"])
    # 동기 모드는 standby 가 붙은 '뒤에' 켠다. 먼저 켜면 응답할 standby 가 없어 primary 의 모든 커밋이 무한 대기한다(실제로 겪음).
    alter_system(primary["port"], "ALTER SYSTEM RESET synchronous_standby_names")
    psql(primary["port"], "CREATE TABLE IF NOT EXISTS repl_t (id bigserial PRIMARY KEY, payload text)")
    psql(primary["port"], "TRUNCATE repl_t")
    psql(primary["port"], "CHECKPOINT")
    t = time.perf_counter()
    run("pg_basebackup", ["-D", str(standby["dir"]), "-X", "stream", "-R", "-c", "fast", "-w", "-d",
                          f"host=127.0.0.1 port={primary['port']} user=postgres application_name=standby1"])
    base_s = time.perf_counter() - t
    start(standby["dir"], standby["port"], standby["log"])
    ok = wait_for(lambda: psql(primary["port"], "SELECT state FROM pg_stat_replication WHERE application_name='standby1'", db="postgres") == "streaming", 60)
    assert ok, "standby 가 streaming 상태가 되지 않았다"
    if sync:
        alter_system(primary["port"], "ALTER SYSTEM SET synchronous_standby_names = 'standby1'")
        ok = wait_for(lambda: psql(primary["port"], "SELECT sync_state FROM pg_stat_replication WHERE application_name='standby1'", db="postgres") == "sync", 30)
        assert ok, "standby 가 sync 상태가 되지 않았다"
    return base_s


def writer(port, stop_evt, st):
    try:
        with psycopg.connect(host="127.0.0.1", port=port, user="postgres", dbname="lab", autocommit=True) as c:
            t0 = time.perf_counter()
            while not stop_evt.is_set():
                st["acked"] = c.execute("INSERT INTO repl_t (payload) VALUES ('x') RETURNING id").fetchone()[0]
                st["n"] += 1
                st["secs"] = time.perf_counter() - t0
    except Exception as e:  # primary 가 죽으면 여기로 온다
        st["err"] = type(e).__name__


def lag_sampler(port, stop_evt, samples):
    try:
        with psycopg.connect(host="127.0.0.1", port=port, user="postgres", dbname="postgres", autocommit=True) as c:
            while not stop_evt.is_set():
                row = c.execute("SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn), coalesce(extract(epoch FROM replay_lag)*1000, 0) "
                                "FROM pg_stat_replication WHERE application_name='standby1'").fetchone()
                if row:
                    samples.append((float(row[0]), float(row[1])))
                time.sleep(0.1)
    except Exception:
        pass


def round_(primary, standby, sync):
    base_s = build_standby(primary, standby, sync)
    stop_evt, st, samples = threading.Event(), {"acked": 0, "n": 0, "secs": 1e-9}, []
    th = [threading.Thread(target=writer, args=(primary["port"], stop_evt, st)),
          threading.Thread(target=lag_sampler, args=(primary["port"], stop_evt, samples))]
    [t.start() for t in th]
    time.sleep(RUN_SECONDS)

    t_kill = time.perf_counter()
    stop(primary["dir"], "immediate")                      # 크래시
    stop_evt.set()
    [t.join() for t in th]
    run("pg_ctl", ["promote", "-D", str(standby["dir"]), "-w", "-t", "60"])
    ok = wait_for(lambda: psql(standby["port"], "SELECT pg_is_in_recovery()") == "f", 30)
    assert ok
    alter_system(standby["port"], "ALTER SYSTEM RESET synchronous_standby_names")  # 안 지우면 새 primary 의 쓰기가 멈춘다
    psql(standby["port"], "INSERT INTO repl_t (payload) VALUES ('after-failover')")                               # 쓰기 가능 확인
    failover_s = time.perf_counter() - t_kill

    present_max = int(psql(standby["port"], "SELECT max(id) FROM repl_t WHERE payload='x'") or 0)
    present = int(psql(standby["port"], "SELECT count(*) FROM repl_t WHERE payload='x'"))
    lost = st["acked"] - present_max if st["acked"] > present_max else 0
    lag_bytes = [s[0] for s in samples] or [0]
    lag_ms = [s[1] for s in samples] or [0]
    return {"mode": "동기(synchronous_standby_names)" if sync else "비동기(기본)",
            "basebackup_s": round(base_s, 1), "commits_acked": st["n"], "tps": round(st["n"] / st["secs"]),
            "last_acked_id": st["acked"], "rows_on_new_primary": present, "lost_acked_commits": lost,
            "lag_bytes_avg": round(statistics.mean(lag_bytes)), "lag_bytes_max": round(max(lag_bytes)),
            "replay_lag_ms_avg": round(statistics.mean(lag_ms), 1), "replay_lag_ms_max": round(max(lag_ms), 1),
            "failover_seconds(kill->writable)": round(failover_s, 1)}


def main():
    assert running(A["dir"]), "먼저 python tools/setup_pg.py start"
    primary, standby = A, B
    results = []
    for sync in (False, False, False, True, True):
        results.append(round_(primary, standby, sync))
        primary, standby = standby, primary                # 승격된 쪽이 새 primary
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    stop(A["dir"]); stop(B["dir"])
    (RESULTS / "pg_replication.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    # 정리: 마지막에 승격된 쪽(살아 있는 데이터)을 원래 위치(pgdata)로 옮긴다.
    # 죽은 쪽 디렉터리에는 synchronous_standby_names 가 남아 있어, 그대로 다시 켜면 모든 쓰기가 무한 대기한다.
    alive = primary  # 루프 마지막에 primary/standby 를 바꿨으므로 primary 가 마지막으로 승격된 쪽
    if alive["dir"] != A["dir"]:
        rmtree(A["dir"])
        alive["dir"].rename(A["dir"])
    sb = A["dir"] / "standby.signal"
    if sb.exists():
        sb.unlink()
    print("데이터를 pgdata 로 정리했다. 다시 쓰려면: python tools/setup_pg.py start")


if __name__ == "__main__":
    main()
