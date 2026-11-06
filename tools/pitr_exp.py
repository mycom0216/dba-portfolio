"""시점 복구(PITR) 실험: 베이스 백업 + WAL 아카이브로 '사고 직전 시각'의 데이터를 되살린다.

시나리오: 100k행 적재 -> 베이스 백업 -> 50k행 추가(T1 기록) -> 사고(짝수 id 삭제) -> WAL 아카이브 확인 -> 서버 정지
          -> 베이스 백업을 새 디렉터리에 복사 + recovery_target_time=T1 -> 복구 서버에서 행 수 확인
별도의 작은 인스턴스(포트 5436/5437)를 쓰므로 lab DB 와 무관하다.

사용: python tools/pitr_exp.py
"""
import json
import shutil
import time

from cluster import psql, rmtree, run, start, stop, wait_for
from common import LAB, RESULTS

SRC, BASE, RESTORE, ARCH = LAB / "pitr_data", LAB / "pitr_base", LAB / "pitr_restore", LAB / "pitr_archive"
P_SRC, P_RESTORE = 5436, 5437


def conf_path(p):  # postgresql.conf 안의 역슬래시는 이스케이프되므로 두 번 쓴다
    return str(p).replace("\\", "\\\\")


def main():
    for d in (SRC, BASE, RESTORE, ARCH):
        stop(d)
        rmtree(d)
    ARCH.mkdir(parents=True)

    run("initdb", ["-D", str(SRC), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--locale=C"])
    with open(SRC / "postgresql.conf", "a", encoding="utf-8") as f:
        f.write(f"\narchive_mode = on\narchive_command = 'copy \"%p\" \"{conf_path(ARCH)}\\\\%f\"'\nshared_buffers = 128MB\n")
    start(SRC, P_SRC, LAB / "pitr_src.log")
    psql(P_SRC, "CREATE DATABASE lab2", db="postgres")
    psql(P_SRC, "CREATE TABLE t (id int PRIMARY KEY, v text)", db="lab2")
    psql(P_SRC, "INSERT INTO t SELECT g, md5(g::text) FROM generate_series(1, 100000) g", db="lab2")

    t = time.perf_counter()
    run("pg_basebackup", ["-D", str(BASE), "-X", "stream", "-c", "fast", "-w"], P_SRC)
    base_s = time.perf_counter() - t

    psql(P_SRC, "INSERT INTO t SELECT g, md5(g::text) FROM generate_series(100001, 150000) g", db="lab2")
    time.sleep(1)
    t1 = psql(P_SRC, "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')", db="lab2")
    count_t1 = int(psql(P_SRC, "SELECT count(*) FROM t", db="lab2"))
    time.sleep(2)

    psql(P_SRC, "DELETE FROM t WHERE id % 2 = 0", db="lab2")                     # 사고
    count_after = int(psql(P_SRC, "SELECT count(*) FROM t", db="lab2"))
    psql(P_SRC, "SELECT pg_switch_wal()", db="lab2")
    assert wait_for(lambda: int(psql(P_SRC, "SELECT archived_count FROM pg_stat_archiver", db="postgres")) >= 3, 30), "WAL 아카이브 실패"
    archived = int(psql(P_SRC, "SELECT archived_count FROM pg_stat_archiver", db="postgres"))
    failed = int(psql(P_SRC, "SELECT failed_count FROM pg_stat_archiver", db="postgres"))
    stop(SRC)

    shutil.copytree(BASE, RESTORE)
    (RESTORE / "recovery.signal").write_text("")
    with open(RESTORE / "postgresql.conf", "a", encoding="utf-8") as f:
        f.write(f"\narchive_mode = off\nrestore_command = 'copy \"{conf_path(ARCH)}\\\\%f\" \"%p\"'\n"
                f"recovery_target_time = '{t1}+00'\nrecovery_target_action = 'promote'\nshared_buffers = 128MB\n")
    t = time.perf_counter()
    start(RESTORE, P_RESTORE, LAB / "pitr_restore.log")
    assert wait_for(lambda: psql(P_RESTORE, "SELECT pg_is_in_recovery()", db="lab2") == "f", 120), "복구가 끝나지 않았다"
    restore_s = time.perf_counter() - t

    restored = int(psql(P_RESTORE, "SELECT count(*) FROM t", db="lab2"))
    even_back = int(psql(P_RESTORE, "SELECT count(*) FROM t WHERE id % 2 = 0", db="lab2"))
    out = {"target_time_utc": t1, "rows_at_target": count_t1, "rows_after_accident": count_after, "rows_restored": restored,
           "deleted_even_rows_restored": even_back, "success": restored == count_t1,
           "basebackup_s": round(base_s, 1), "wal_files_archived": archived, "archive_failures": failed,
           "recovery_start_to_ready_s": round(restore_s, 1)}
    stop(RESTORE)
    (RESULTS / "pg_pitr.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    for d in (SRC, BASE, RESTORE, ARCH):
        rmtree(d)  # 디스크 정리


if __name__ == "__main__":
    main()
