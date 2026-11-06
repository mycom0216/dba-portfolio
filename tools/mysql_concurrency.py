"""MySQL(InnoDB) 동시성 실험: PostgreSQL 실험(tools/concurrency.py)과 같은 4가지 차감 방식 + 데드락.

PyMySQL 스레드로 구현했다(pip install pymysql). 서버 쪽 sleep(DO SLEEP) 으로 '앱 처리 2ms'를 흉내 내는 것은 pgbench 실험과 같다.
주의: 클라이언트가 Python 스레드라 TPS 절대값은 PostgreSQL(pgbench) 결과와 비교할 수 없다. 비교 대상은 '정합성(사라진 차감, 데드락)'이다.

사용: python tools/mysql_concurrency.py   (MySQL 기동 + tune_mysql.py 로 데이터 적재 완료 상태)
"""
import json
import random
import threading
import time

import pymysql

from common import MY_PORT, RESULTS

CLIENTS, TXN, INIT, PTS = 16, 500, 10_000_000, 10
DL_CLIENTS, DL_TXN = 8, 250


def conn(isolation=None):
    c = pymysql.connect(host="127.0.0.1", port=MY_PORT, user="root", database="lab", autocommit=True)
    if isolation:
        with c.cursor() as cur:
            cur.execute(f"SET SESSION TRANSACTION ISOLATION LEVEL {isolation}")
    return c


def scalar(sql):
    c = conn()
    with c.cursor() as cur:
        cur.execute(sql)
        v = cur.fetchone()[0]
    c.close()
    return int(v)


def run_threads(n, worker):
    res = {"ok": 0, "err": {}}
    lock = threading.Lock()
    ths = [threading.Thread(target=worker, args=(res, lock)) for _ in range(n)]
    t = time.perf_counter()
    [x.start() for x in ths]
    [x.join() for x in ths]
    res["secs"] = time.perf_counter() - t
    return res


# --- 차감 4방식 -------------------------------------------------------------
def naive(cur, u):          # 읽고 -> 앱 계산 -> 쓰기
    cur.execute("START TRANSACTION")
    cur.execute("SELECT balance_points FROM wallets WHERE user_id=%s", (u,))
    bal = cur.fetchone()[0]
    cur.execute("DO SLEEP(0.002)")
    cur.execute("UPDATE wallets SET balance_points=%s WHERE user_id=%s", (bal - PTS, u))
    cur.execute("COMMIT")


def for_update(cur, u):
    cur.execute("START TRANSACTION")
    cur.execute("SELECT balance_points FROM wallets WHERE user_id=%s FOR UPDATE", (u,))
    bal = cur.fetchone()[0]
    cur.execute("DO SLEEP(0.002)")
    cur.execute("UPDATE wallets SET balance_points=%s WHERE user_id=%s", (bal - PTS, u))
    cur.execute("COMMIT")


def atomic(cur, u):         # 앱 처리 시간은 잠금 밖
    cur.execute("DO SLEEP(0.002)")
    cur.execute("START TRANSACTION")
    cur.execute("UPDATE wallets SET balance_points=balance_points-%s WHERE user_id=%s AND balance_points>=%s", (PTS, u, PTS))
    cur.execute("COMMIT")


def deduction_case(label, fn, isolation=None):
    c0 = conn()
    with c0.cursor() as cur:
        cur.execute(f"UPDATE wallets SET balance_points={INIT} WHERE user_id<=10")
    c0.close()

    def worker(res, lock):
        c = conn(isolation)
        cur = c.cursor()
        for _ in range(TXN):
            try:
                fn(cur, random.randint(1, 10))
                with lock:
                    res["ok"] += 1
            except pymysql.MySQLError as e:
                with lock:
                    res["err"][e.args[0]] = res["err"].get(e.args[0], 0) + 1
                try:
                    cur.execute("ROLLBACK")
                except pymysql.MySQLError:
                    pass
        c.close()

    r = run_threads(CLIENTS, worker)
    actual = 10 * INIT - scalar("SELECT SUM(balance_points) FROM wallets WHERE user_id<=10")
    expected = r["ok"] * PTS
    return {"case": label, "committed": r["ok"], "errors": r["err"], "expected_deduction": expected,
            "actual_deduction": actual, "lost_updates": (expected - actual) // PTS, "tps(참고)": round(r["ok"] / r["secs"])}


# --- 데드락 -------------------------------------------------------------------
def transfer_naive(cur, a, b):
    cur.execute("START TRANSACTION")
    cur.execute("UPDATE wallets SET balance_points=balance_points-1 WHERE user_id=%s", (a,))
    cur.execute("DO SLEEP(0.002)")
    cur.execute("UPDATE wallets SET balance_points=balance_points+1 WHERE user_id=%s", (b,))
    cur.execute("COMMIT")


def transfer_ordered(cur, a, b):
    cur.execute("START TRANSACTION")
    cur.execute("SELECT 1 FROM wallets WHERE user_id IN (%s,%s) ORDER BY user_id FOR UPDATE", (a, b))
    cur.execute("UPDATE wallets SET balance_points=balance_points-1 WHERE user_id=%s", (a,))
    cur.execute("DO SLEEP(0.002)")
    cur.execute("UPDATE wallets SET balance_points=balance_points+1 WHERE user_id=%s", (b,))
    cur.execute("COMMIT")


def deadlock_case(label, fn):
    c0 = conn()
    with c0.cursor() as cur:
        cur.execute(f"UPDATE wallets SET balance_points={INIT} WHERE user_id<=4")
    c0.close()

    def worker(res, lock):
        c = conn()
        cur = c.cursor()
        for _ in range(DL_TXN):
            a = random.randint(1, 4)
            b = (a + random.randint(1, 3) - 1) % 4 + 1
            try:
                fn(cur, a, b)
                with lock:
                    res["ok"] += 1
            except pymysql.MySQLError as e:
                with lock:
                    res["err"][e.args[0]] = res["err"].get(e.args[0], 0) + 1
                try:
                    cur.execute("ROLLBACK")
                except pymysql.MySQLError:
                    pass
        c.close()

    r = run_threads(DL_CLIENTS, worker)
    return {"case": label, "committed": r["ok"], "errors(1213=데드락)": r["err"],
            "total_conserved": scalar("SELECT SUM(balance_points) FROM wallets WHERE user_id<=4") == 4 * INIT}


def main():
    res = {
        "setup": {"clients": CLIENTS, "txn_per_client": TXN, "hot_wallets": 10, "points_per_txn": PTS,
                  "deadlock_clients": DL_CLIENTS, "deadlock_txn_per_client": DL_TXN, "client": "PyMySQL 스레드"},
        "deduction": [
            deduction_case("읽고-계산-쓰기 (REPEATABLE READ, InnoDB 기본)", naive),
            deduction_case("읽고-계산-쓰기 (READ COMMITTED)", naive, "READ COMMITTED"),
            deduction_case("SELECT FOR UPDATE", for_update),
            deduction_case("원자적 조건부 UPDATE", atomic),
        ],
        "deadlock": [deadlock_case("차감->증가 (잠금 순서 제각각)", transfer_naive),
                     deadlock_case("user_id 순으로 먼저 잠금", transfer_ordered)],
    }
    (RESULTS / "mysql_concurrency.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
