"""후원 포인트 차감 동시성 실험 (pgbench 커스텀 스크립트).

사용: python tools/concurrency.py
 E1 읽고-계산-쓰기(나쁜 예) : lost update 발생 여부   (READ COMMITTED / REPEATABLE READ)
 E2 SELECT FOR UPDATE, 원자적 UPDATE : 정합성 + 처리량
 E3 데드락 재현 / 잠금 순서 고정으로 해결
"""
import json
import os
import re
import subprocess

from common import PG_BIN, PG_PORT, RESULTS, ROOT, psql

SCRIPTS = ROOT / "sql" / "pg" / "concurrency"
CLIENTS, TXN_PER_CLIENT, INIT = 16, 500, 10_000_000
PTS = 10


def reset(n_wallets):
    psql(f"UPDATE wallets SET balance_points = {INIT} WHERE user_id <= {n_wallets}")


def total(n_wallets):
    return int(psql(f"SELECT sum(balance_points) FROM wallets WHERE user_id <= {n_wallets}").strip())


def pgbench(script, isolation=None, clients=CLIENTS, txns=TXN_PER_CLIENT, deadlock_timeout=None):
    env = os.environ.copy()
    env.update(PGHOST="127.0.0.1", PGPORT=str(PG_PORT), PGUSER="postgres")
    opts = []
    if isolation:
        opts.append(f"-c default_transaction_isolation={isolation.replace(' ', chr(92) + ' ')}")  # PGOPTIONS 값의 공백은 \ 로 이스케이프
    if deadlock_timeout:  # 데드락은 감지될 때까지 deadlock_timeout 만큼 기다린다 -> 실험에서는 세션 단위로 줄인다
        opts.append(f"-c deadlock_timeout={deadlock_timeout}")
    if opts:
        env["PGOPTIONS"] = " ".join(opts)
    r = subprocess.run([str(PG_BIN / "pgbench"), "-n", "-M", "simple", "--failures-detailed", "-c", str(clients), "-j", "4",
                        "-t", str(txns), "-f", str(SCRIPTS / script), "lab"],
                       env=env, capture_output=True, text=True, encoding="utf-8", timeout=600)
    out = r.stdout + r.stderr
    if "number of transactions actually processed: 0" in out or "tps =" not in out:
        raise RuntimeError(f"pgbench 가 한 건도 처리하지 못했다 ({script}):\n{out[-800:]}")  # 0건을 정상 결과로 착각하지 않도록
    g = lambda pat, d=0: (lambda m: float(m.group(1).replace(",", "")) if m else d)(re.search(pat, out))
    return {"processed": int(g(r"number of transactions actually processed: (\d+)")),
            "failed": int(g(r"number of failed transactions: (\d+)")),
            "deadlock_failures": int(g(r"number of deadlock failures: (\d+)")),
            "serialization_failures": int(g(r"number of serialization failures: (\d+)")),
            "tps": round(g(r"tps = ([\d.]+)")), "latency_ms": round(g(r"latency average = ([\d.]+) ms"), 1)}


def deduction_case(label, script, isolation=None):
    reset(10)
    r = pgbench(script, isolation)
    actual = 10 * INIT - total(10)
    expected = r["processed"] * PTS  # 커밋된 트랜잭션 수 x 10포인트
    r.update(case=label, expected_deduction=expected, actual_deduction=actual,
             lost_updates=(expected - actual) // PTS)
    return r


DL_CLIENTS, DL_TXNS = 8, 250  # 데드락 실험은 클라이언트 8개 x 250건 (16x500 은 1초 대기가 겹쳐 수십 분 걸렸다)


def transfer_case(label, script):
    reset(4)
    r = pgbench(script, clients=DL_CLIENTS, txns=DL_TXNS, deadlock_timeout="50ms")
    r.update(case=label, total_conserved=(total(4) == 4 * INIT))
    return r


def main():
    res = {
        "setup": {"clients": CLIENTS, "txn_per_client": TXN_PER_CLIENT, "hot_wallets": 10, "points_per_txn": PTS,
                  "deadlock_clients": DL_CLIENTS, "deadlock_txn_per_client": DL_TXNS, "deadlock_timeout": "50ms"},
        "deduction": [
            deduction_case("읽고-계산-쓰기 (READ COMMITTED)", "naive.sql"),
            deduction_case("읽고-계산-쓰기 (REPEATABLE READ)", "naive.sql", "repeatable read"),
            deduction_case("SELECT FOR UPDATE", "for_update.sql"),
            deduction_case("원자적 조건부 UPDATE", "atomic.sql"),
        ],
        "deadlock": [
            transfer_case("차감->증가 (잠금 순서 제각각)", "deadlock_naive.sql"),
            transfer_case("user_id 순으로 먼저 잠금", "deadlock_ordered.sql"),
        ],
    }
    (RESULTS / "pg_concurrency.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
