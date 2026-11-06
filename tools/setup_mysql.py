"""MySQL 8.4 포터블 바이너리: initialize -> my.ini 작성 -> 백그라운드 기동 -> lab DB 생성 (재실행 안전).

사용: python tools/setup_mysql.py [start|stop|status]
"""
import subprocess
import sys
import time

from common import LAB, MY_BASE, MY_BIN, MY_DATA, MY_PORT, my_run

INI = LAB / "my.ini"
LOG = LAB / "mysqld.log"


def ini_text():
    fw = lambda p: str(p).replace("\\", "/")
    return f"""[mysqld]
basedir={fw(MY_BASE)}
datadir={fw(MY_DATA)}
port={MY_PORT}
bind-address=127.0.0.1
mysqlx=OFF
character-set-server=utf8mb4
local_infile=ON
secure_file_priv=
# --- 실험용 설정 (PostgreSQL 쪽과 메모리 규모를 비슷하게) ---
innodb_buffer_pool_size=1G
innodb_redo_log_capacity=512M
max_connections=100
slow_query_log=ON
slow_query_log_file={fw(LAB / 'mysql-slow.log')}
long_query_time=0.2
log_error={fw(LOG)}
"""


def alive():
    try:
        return "alive" in my_run(["mysqladmin", "ping"], check=False)
    except Exception:
        return False


def start():
    if not (MY_BIN / "mysqld.exe").exists():
        sys.exit("MySQL 이 압축 해제되어 있지 않습니다 (%s)" % MY_BIN)
    INI.write_text(ini_text(), encoding="utf-8")
    if not (MY_DATA / "mysql").exists():
        print("initialize...", flush=True)
        subprocess.run([str(MY_BIN / "mysqld"), f"--defaults-file={INI}", "--initialize-insecure"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    if not alive():
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        subprocess.Popen([str(MY_BIN / "mysqld"), f"--defaults-file={INI}"], creationflags=flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        for _ in range(60):
            if alive():
                break
            time.sleep(1)
        else:
            sys.exit(f"mysqld 기동 실패. 로그: {LOG}")
    my_run(["mysql", "--batch", "-e", "CREATE DATABASE IF NOT EXISTS lab CHARACTER SET utf8mb4; SET GLOBAL local_infile=1;"])
    print(my_run(["mysql", "--batch", "--skip-column-names", "-e", "SELECT VERSION()"]).strip())


def stop():
    if alive():
        my_run(["mysqladmin", "shutdown"])
        print("stopped")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    {"start": start, "stop": stop, "status": lambda: print("running" if alive() else "stopped")}[cmd]()
