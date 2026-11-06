-- [해법 1] 읽는 시점에 행 잠금(SELECT ... FOR UPDATE). 앱 로직이 복잡해 SQL 한 줄로 못 쓸 때 쓴다. 대신 잠금 보유 시간이 길다.
\set uid random(1, 10)
\set pts 10
BEGIN;
SELECT balance_points AS bal FROM wallets WHERE user_id = :uid FOR UPDATE \gset
SELECT pg_sleep(0.002);
UPDATE wallets SET balance_points = :bal - :pts WHERE user_id = :uid;
COMMIT;
