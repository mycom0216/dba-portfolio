"""공통 유틸: psql/mysql 클라이언트를 subprocess 로 호출한다 (DB 드라이버 설치 없이 동작).

환경 변수로 위치를 바꿀 수 있다: DBA_LAB(설치 루트), PGPORT_LAB, MYPORT_LAB
"""
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAB = pathlib.Path(os.environ.get("DBA_LAB", pathlib.Path(os.environ.get("LOCALAPPDATA", ".")) / "dba-lab"))
PG_BIN = LAB / "pg" / "pgsql" / "bin"
PG_DATA = LAB / "pgdata"
PG_PORT = int(os.environ.get("PGPORT_LAB", 5433))
MY_BASE = next(iter((LAB / "mysql").glob("mysql-*")), LAB / "mysql")
MY_BIN = MY_BASE / "bin"
MY_DATA = LAB / "mydata"
MY_PORT = int(os.environ.get("MYPORT_LAB", 3307))
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)


def _pg_env():
    e = os.environ.copy()
    e.update(PGHOST="127.0.0.1", PGPORT=str(PG_PORT), PGUSER="postgres", PGCLIENTENCODING="UTF8")
    return e


def pg_run(args, **kw):
    """pg_bin 아래 실행 파일을 호출. 실패하면 stderr 와 함께 예외."""
    exe, *rest = args
    r = subprocess.run([str(PG_BIN / exe), *rest], env=_pg_env(), capture_output=True, text=True, encoding="utf-8", **kw)
    if r.returncode != 0:
        raise RuntimeError(f"{exe} 실패(code {r.returncode}): {r.stderr.strip()[:800]}")
    return r.stdout


def psql(sql=None, file=None, db="lab", raw=False):
    """SQL 문자열 또는 파일 실행. raw=False 이면 -A -t (값만) 출력."""
    a = ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", db]
    if not raw:
        a += ["-A", "-t"]
    a += ["-f", str(file)] if file else ["-c", sql]
    return pg_run(a)


def my_run(args, db=None, check=True):
    exe, *rest = args
    cmd = [str(MY_BIN / exe), f"--port={MY_PORT}", "--host=127.0.0.1", "--user=root", *rest]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise RuntimeError(f"{exe} 실패(code {r.returncode}): {r.stderr.strip()[:800]}")
    return r.stdout


def mysql(sql=None, file=None, db="lab"):
    a = ["mysql", "--batch", "--skip-column-names", "--local-infile=1", f"--database={db}"]
    if file:
        r = subprocess.run([str(MY_BIN / "mysql"), f"--port={MY_PORT}", "--host=127.0.0.1", "--user=root", "--local-infile=1",
                            f"--database={db}"], stdin=open(file, "rb"), capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            raise RuntimeError(f"mysql 실패: {r.stderr.strip()[:800]}")
        return r.stdout
    return my_run([*a, "-e", sql])


def split_named_queries(path):
    """'-- name: Qn 설명' 주석 단위로 SQL 을 잘라 [(이름, 설명, sql)] 반환."""
    out, cur = [], None
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"--\s*name:\s*(\S+)\s*(.*)", line)
        if m:
            cur = [m.group(1), m.group(2), []]
            out.append(cur)
        elif cur is not None and not line.strip().startswith("--"):
            cur[2].append(line)
    return [(n, d, "\n".join(s).strip().rstrip(";")) for n, d, s in out]


def eprint(*a):
    print(*a, file=sys.stderr, flush=True)
