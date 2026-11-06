# 재현 방법 (Windows, 관리자 권한 불필요)

DB 는 설치 프로그램 없이 **포터블 압축 파일**을 사용자 폴더(`%LOCALAPPDATA%\dba-lab`)에 풀어서 쓴다. 지우려면 그 폴더만 삭제하면 된다. 전체 실험은 약 6GB 디스크를 쓴다.

## 1. 준비 (한 번만)
```powershell
$d = "$env:LOCALAPPDATA\dba-lab"; New-Item -ItemType Directory -Force $d | Out-Null
curl.exe -L -o "$d\pg.zip"    https://get.enterprisedb.com/postgresql/postgresql-16.9-1-windows-x64-binaries.zip   # 약 300MB
curl.exe -L -o "$d\mysql.zip" https://cdn.mysql.com/archives/mysql-8.4/mysql-8.4.6-winx64.zip                      # 약 249MB
Expand-Archive "$d\pg.zip"    -DestinationPath "$d\pg"    -Force      # pg\pgsql\bin 이 생겨야 한다
Expand-Archive "$d\mysql.zip" -DestinationPath "$d\mysql" -Force
pip install sqlalchemy "psycopg[binary]" pymysql                       # ORM / 복제 / MySQL 동시성 실험용
```
Python 3.10+ 필요. DB 클라이언트는 `psql`/`mysql` 실행 파일을 직접 호출한다.

## 2. 실행 순서
```powershell
$env:PYTHONIOENCODING = "utf-8"         # 한글 출력 깨짐 방지 (Windows PowerShell 5.1)
python tools/setup_pg.py start          # initdb + 기동 (포트 5433) + DB 시간대를 UTC 로 고정
python tools/setup_mysql.py start       # initialize + 기동 (포트 3307)
$env:Path = "$env:LOCALAPPDATA\dba-lab\pg\pgsql\bin;$env:Path"        # psql 을 이 창에서 쓸 수 있게 (창을 닫으면 사라짐)
psql -h 127.0.0.1 -p 5433 -U postgres -d lab -f sql/pg/01_schema.sql
psql -h 127.0.0.1 -p 5433 -U postgres -d lab -f sql/pg/02_seed.sql      # 약 50초
psql -h 127.0.0.1 -p 5433 -U postgres -d lab -f sql/pg/02b_seed_check.sql   # 분포 검증 (실패하면 중단)

python tools/run_all.py core            # 튜닝 / MySQL / 동시성 / 점검 / 백업 (약 5분)
python tools/run_all.py extra           # 파티셔닝 / 비용 모델 / ORM / MySQL 동시성 / PITR / 복제 (복제는 맨 마지막, 데이터 디렉터리가 바뀜)
python tools/bench.py report            # 두 DB 결과표
```
결과는 `results/*.json`, `results/*.md` 에 저장된다. 실험 하나만 돌리려면 `python tools/<이름>.py`.

## 3. 알려진 함정 (직접 겪은 것)
- `pg_ctl start` 를 `subprocess` 의 `capture_output` 으로 부르면 서버가 파이프를 상속해 **영원히 안 끝난다** → 출력을 DEVNULL 로 버린다.
- Windows 의 `COPY ... TO` 는 CSV 를 CRLF 로 쓴다. MySQL `LOAD DATA` 의 줄 끝을 맞추지 않으면 마지막 열의 `\N`(NULL)이 깨진다.
- 시드의 `LATERAL (SELECT ... random())` 은 **한 번만 평가**되어 모든 행이 같은 값이 된다 → FROM 절 서브쿼리에서 값을 만들고 `02b_seed_check.sql` 로 검증.
- **DB 시간대를 코드에 넣지 않으면** 환경마다(OS 시간대) 날짜 리터럴 해석이 달라져 PG 와 MySQL 결과가 어긋난다 (`setup_pg.py` 가 UTC 로 고정).
- `deadlock_timeout`(기본 1초)이 데드락 재현 실험의 걸림돌이다 (세션 단위로 50ms 로 낮춤).
- 작업 도중 프로세스 트리를 강제로 종료하면 그 아래에서 띄운 DB 서버도 같이 죽는다.
- PowerShell 5.1 스크립트(`*.ps1`)는 한글 주석을 BOM 없는 UTF-8 로 쓰면 줄바꿈을 삼킨다 → ASCII 로 유지.
