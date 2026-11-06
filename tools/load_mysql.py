"""PostgreSQL 의 데이터를 CSV 로 내보내 MySQL 에 그대로 적재한다 (두 DB 가 '똑같은 데이터'를 가져야 성능 비교가 공정하다).

사용: python tools/load_mysql.py     (PostgreSQL, MySQL 둘 다 기동되어 있어야 함)
"""
import time

from common import LAB, ROOT, mysql, psql

EXPORT = LAB / "export"
EXPORT.mkdir(exist_ok=True)
TS = "to_char({c} AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')"

# (테이블, PG SELECT, MySQL 컬럼 목록)
TABLES = [
    ("users", f"SELECT user_id, nickname, country, status, {TS.format(c='created_at')} FROM users",
     "user_id, nickname, country, status, created_at"),
    ("wallets", f"SELECT user_id, balance_points, {TS.format(c='updated_at')} FROM wallets",
     "user_id, balance_points, updated_at"),
    ("gifts", "SELECT gift_id, name, price_points FROM gifts", "gift_id, name, price_points"),
    ("broadcasts", f"SELECT broadcast_id, host_id, title, category, {TS.format(c='started_at')}, {TS.format(c='ended_at')} FROM broadcasts",
     "broadcast_id, host_id, title, category, started_at, ended_at"),
    ("listens", f"SELECT listen_id, broadcast_id, user_id, {TS.format(c='joined_at')}, {TS.format(c='left_at')} FROM listens",
     "listen_id, broadcast_id, user_id, joined_at, left_at"),
    ("donations", f"SELECT donation_id, broadcast_id, sender_id, gift_id, points, {TS.format(c='created_at')} FROM donations",
     "donation_id, broadcast_id, sender_id, gift_id, points, created_at"),
]

CHECKS = {
    "users": ("SELECT count(*), sum(user_id), sum(status) FROM users", "SELECT COUNT(*), SUM(user_id), SUM(status) FROM users"),
    "listens": ("SELECT count(*), sum(broadcast_id), sum(user_id), count(left_at) FROM listens",
                "SELECT COUNT(*), SUM(broadcast_id), SUM(user_id), COUNT(left_at) FROM listens"),
    "donations": ("SELECT count(*), sum(points), sum(sender_id), sum(broadcast_id) FROM donations",
                  "SELECT COUNT(*), SUM(points), SUM(sender_id), SUM(broadcast_id) FROM donations"),
    "broadcasts": ("SELECT count(*), sum(host_id), count(ended_at) FROM broadcasts",
                   "SELECT COUNT(*), SUM(host_id), COUNT(ended_at) FROM broadcasts"),
}


def main():
    t0 = time.time()
    mysql(file=ROOT / "sql" / "mysql" / "01_schema.sql", db="lab")
    for name, select, cols in TABLES:
        f = (EXPORT / f"{name}.csv").as_posix()
        psql(f"COPY ({select}) TO '{f}' WITH (FORMAT csv, NULL '\\N')")
        mysql("SET GLOBAL local_infile=1")
        # Windows 의 PostgreSQL 은 CSV 를 CRLF 로 쓴다. 줄 끝을 맞추지 않으면 마지막 열의 \N(NULL)이 '\N\r' 이 되어 NULL 로 인식되지 않는다.
        eol = "\\r\\n" if b"\r\n" in (EXPORT / f"{name}.csv").read_bytes()[:4096] else "\\n"
        mysql(f"SET FOREIGN_KEY_CHECKS=0; SET UNIQUE_CHECKS=0; "
              f"LOAD DATA INFILE '{f}' INTO TABLE {name} CHARACTER SET utf8mb4 "
              f"FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' LINES TERMINATED BY '{eol}' ({cols})")
        print(f"{name:11s} loaded  ({time.time() - t0:.0f}s)", flush=True)
    mysql("ANALYZE TABLE users, listens, donations, broadcasts")

    ok = True
    for name, (pg_sql, my_sql) in CHECKS.items():
        a, b = psql(pg_sql).strip(), mysql(my_sql).strip().replace("\t", "|")
        same = a == b
        ok &= same
        print(f"check {name:11s} PG={a}  MySQL={b}  {'OK' if same else 'MISMATCH'}")
    print("데이터 동일:", ok)
    for f in EXPORT.glob("*.csv"):
        f.unlink()  # 디스크 절약
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
