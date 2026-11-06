"""임의의 데이터 디렉터리/포트로 PostgreSQL 인스턴스를 다루는 헬퍼 (복제·PITR 실험용).

주의: pg_ctl 이 띄운 서버는 stdout/stderr 파이프를 상속하므로 start 는 출력을 DEVNULL 로 버린다 (setup_pg.py 와 같은 이유).
"""
import os
import shutil
import stat
import subprocess
import time

from common import PG_BIN


def env(port):
    e = os.environ.copy()
    e.update(PGHOST="127.0.0.1", PGPORT=str(port), PGUSER="postgres", PGCLIENTENCODING="UTF8")
    return e


def run(exe, args, port=5433, check=True):
    r = subprocess.run([str(PG_BIN / exe), *args], env=env(port), capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise RuntimeError(f"{exe} 실패(code {r.returncode}): {r.stderr.strip()[:800]}")
    return r


def psql(port, sql, db="lab"):
    return run("psql", ["-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-d", db, "-c", sql], port).stdout.strip()


def running(datadir):
    return run("pg_ctl", ["status", "-D", str(datadir)], check=False).returncode == 0


def start(datadir, port, log):
    if running(datadir):
        return
    subprocess.run([str(PG_BIN / "pg_ctl"), "start", "-D", str(datadir), "-o", f"-p {port}", "-l", str(log), "-w", "-t", "120"],
                   env=env(port), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, check=True)


def stop(datadir, mode="fast"):
    if running(datadir):
        run("pg_ctl", ["stop", "-D", str(datadir), "-m", mode, "-w"], check=False)


def rmtree(path):
    def onerr(func, p, _):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if os.path.exists(path):
        shutil.rmtree(path, onerror=onerr)


def wait_for(cond, timeout=60, step=0.2):
    t = time.time()
    while time.time() - t < timeout:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(step)
    return False
