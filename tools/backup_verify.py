"""백업 -> 별도 DB 로 복구 -> 원본과 대조까지 자동으로 하는 검증 스크립트.

'백업이 있다'가 아니라 '복구가 된다'를 확인하는 것이 목적이다. 실패하면 종료 코드 1.
사용: python tools/backup_verify.py        (DB: lab -> lab_restore_check 로 복구 후 삭제)

범위: 논리 백업(pg_dump) 검증. 시점 복구(PITR, WAL 아카이빙)와 물리 백업은 다루지 않는다.
"""
import json
import sys
import time

from common import LAB, RESULTS, pg_run, psql

DUMP = LAB / "backup" / "lab.dump"
RESTORE_DB = "lab_restore_check"
# 테이블별 대조 쿼리: 행 수 + 값 체크섬. 복구본과 원본이 완전히 같아야 한다.
CHECKS = {
    "users": "SELECT count(*), sum(user_id), md5(string_agg(nickname, ',' ORDER BY user_id)) FROM users",
    "wallets": "SELECT count(*), sum(balance_points) FROM wallets",
    "listens": "SELECT count(*), sum(listen_id), sum(user_id), count(left_at) FROM listens",
    "donations": "SELECT count(*), sum(points), sum(sender_id), sum(broadcast_id) FROM donations",
}


def main():
    DUMP.parent.mkdir(exist_ok=True)
    t = time.perf_counter()
    pg_run(["pg_dump", "-Fc", "-Z", "5", "-d", "lab", "-f", str(DUMP)])
    dump_s = time.perf_counter() - t
    size_mb = DUMP.stat().st_size / 1e6

    psql(f"DROP DATABASE IF EXISTS {RESTORE_DB}", db="postgres")
    psql(f"CREATE DATABASE {RESTORE_DB}", db="postgres")
    t = time.perf_counter()
    pg_run(["pg_restore", "--no-owner", "-j", "4", "-d", RESTORE_DB, str(DUMP)])
    restore_s = time.perf_counter() - t

    report, ok = {}, True
    for tbl, sql in CHECKS.items():
        a, b = psql(sql, db="lab").strip(), psql(sql, db=RESTORE_DB).strip()
        report[tbl] = {"source": a, "restored": b, "match": a == b}
        ok &= a == b
    # 인덱스·제약조건도 복구됐는지(개수 비교)
    cnt = "SELECT (SELECT count(*) FROM pg_indexes WHERE schemaname='public'), (SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public')"
    ic_a, ic_b = psql(cnt, db="lab").strip(), psql(cnt, db=RESTORE_DB).strip()
    report["indexes|constraints"] = {"source": ic_a, "restored": ic_b, "match": ic_a == ic_b}
    ok &= ic_a == ic_b

    psql(f"DROP DATABASE {RESTORE_DB}", db="postgres")
    summary = {"ok": ok, "dump_seconds": round(dump_s, 1), "dump_mb": round(size_mb, 1),
               "restore_seconds": round(restore_s, 1), "tables": report}
    (RESULTS / "backup_verify.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("BACKUP VERIFY:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
