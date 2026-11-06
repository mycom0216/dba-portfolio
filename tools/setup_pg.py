"""PostgreSQL 포터블 바이너리 압축 해제 -> initdb -> 설정 -> 기동 -> lab DB 생성 (여러 번 실행해도 안전).

사용: python tools/setup_pg.py [start|stop|status]
"""
import subprocess
import sys
import zipfile

from common import LAB, PG_BIN, PG_DATA, PG_PORT, _pg_env, pg_run, psql

CONF = f"""
# --- DBA 포트폴리오 실험용 설정 (개인 PC 기준) ---
port = {PG_PORT}
listen_addresses = '127.0.0.1'
shared_buffers = 512MB
work_mem = 16MB
maintenance_work_mem = 256MB
max_connections = 100
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all
track_io_timing = on
log_min_duration_statement = 200     # 200ms 이상 쿼리를 로그에 남김 (슬로우 쿼리)
log_lock_waits = on
deadlock_timeout = 1s
logging_collector = on
log_directory = 'log'
log_line_prefix = '%m [%p] %u@%d '
"""


def ensure_installed():
    if (PG_BIN / "pg_ctl.exe").exists():
        return
    z = LAB / "pg.zip"
    if not z.exists():
        sys.exit(f"{z} 가 없습니다. README 의 다운로드 단계를 먼저 수행하세요.")
    print("압축 해제 중...", flush=True)
    with zipfile.ZipFile(z) as f:
        f.extractall(LAB / "pg")


def running():
    try:
        pg_run(["pg_ctl", "status", "-D", str(PG_DATA)])
        return True
    except RuntimeError:
        return False


def start():
    ensure_installed()
    if not (PG_DATA / "PG_VERSION").exists():
        print("initdb...", flush=True)
        pg_run(["initdb", "-D", str(PG_DATA), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--locale=C"])
        with open(PG_DATA / "postgresql.conf", "a", encoding="utf-8") as f:
            f.write(CONF)
    if not running():
        # 주의: pg_ctl 이 띄운 서버가 stdout/stderr 파이프를 상속하므로 capture_output 을 쓰면 영원히 안 끝난다.
        # 출력을 DEVNULL 로 버리고, 서버 로그는 -l 파일로 받는다.
        subprocess.run([str(PG_BIN / "pg_ctl"), "start", "-D", str(PG_DATA), "-l", str(LAB / "pg.log"), "-w", "-t", "60"],
                       env=_pg_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, check=True)
    if psql("SELECT 1 FROM pg_database WHERE datname='lab'", db="postgres").strip() != "1":
        psql("CREATE DATABASE lab", db="postgres")
    psql("CREATE EXTENSION IF NOT EXISTS pg_stat_statements", db="lab")
    # 시각은 전부 UTC 로 다룬다. 이 설정이 빠지면 OS 시간대(예: KST)로 날짜 리터럴이 해석되어 MySQL(UTC) 과 결과가 달라진다.
    # (재설치 후 재현 테스트에서 실제로 겪은 문제)
    psql("ALTER DATABASE lab SET timezone TO 'UTC'", db="postgres")
    print(psql("SELECT version()", db="lab").strip())


def stop():
    if running():
        pg_run(["pg_ctl", "stop", "-D", str(PG_DATA), "-m", "fast", "-w"])
        print("stopped")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    {"start": start, "stop": stop, "status": lambda: print("running" if running() else "stopped")}[cmd]()
