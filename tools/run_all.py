"""실험 전체를 순서대로 재실행하고 각 단계의 성공/실패와 소요 시간을 요약한다. (DB 두 대가 기동되어 있고 PG 에 시드가 들어 있어야 함)

사용: python tools/run_all.py            # 전체
      python tools/run_all.py core       # 기본 5단계 (튜닝, MySQL, 동시성, 점검, 백업)
      python tools/run_all.py extra      # 추가 실험 (파티셔닝, 비용 모델, ORM, MySQL 동시성, PITR, 복제)
측정이 서로 간섭하지 않도록 단계를 직렬로 실행한다 (동시에 돌리면 CPU 경쟁으로 수치가 흔들린다).
복제 실험은 데이터 디렉터리를 바꾸므로 맨 마지막에 둔다.
"""
import subprocess
import sys
import time

from common import ROOT

CORE = [
    ("PostgreSQL 튜닝", "tune_pg.py"),
    ("MySQL 적재+튜닝", "tune_mysql.py"),
    ("PG 동시성 실험", "concurrency.py"),
    ("점검 리포트", "monitor_report.py"),
    ("백업 복구 검증", "backup_verify.py"),
]
EXTRA = [
    ("파티셔닝", "partition_exp.py"),
    ("플래너 비용 모델 검증", "planner_cost.py"),
    ("ORM (N+1)", "orm_exp.py"),
    ("MySQL 동시성", "mysql_concurrency.py"),
    ("시점 복구(PITR)", "pitr_exp.py"),
    ("복제·장애 조치", "replication_exp.py"),
]


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    steps = {"core": CORE, "extra": EXTRA, "all": CORE + EXTRA}[which]
    summary = []
    for name, script in steps:
        t = time.time()
        r = subprocess.run([sys.executable, str(ROOT / "tools" / script)], capture_output=True, text=True, encoding="utf-8")
        ok = r.returncode in (0, 1) if script == "monitor_report.py" else r.returncode == 0  # 점검 리포트의 1은 '경고'라서 실행 실패가 아니다
        summary.append((name, "OK" if ok else f"FAIL({r.returncode})", round(time.time() - t)))
        print(f"[{summary[-1][1]}] {name} ({summary[-1][2]}s)", flush=True)
        if not ok:
            print(r.stdout[-1500:], r.stderr[-1500:], flush=True)
            break
    print("\n".join(f"{n:22s} {s:10s} {sec}s" for n, s, sec in summary))
    sys.exit(0 if all(s == "OK" for _, s, _ in summary) else 1)


if __name__ == "__main__":
    main()
