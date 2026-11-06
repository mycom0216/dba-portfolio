-- [나쁜 예] 읽고 -> 앱에서 계산 -> 쓰기. 두 트랜잭션이 같은 잔액을 읽으면 한쪽 차감이 사라진다(lost update).
\set uid random(1, 10)
\set pts 10
BEGIN;
SELECT balance_points AS bal FROM wallets WHERE user_id = :uid \gset
SELECT pg_sleep(0.002);  -- 애플리케이션의 검증/계산 시간을 흉내
UPDATE wallets SET balance_points = :bal - :pts WHERE user_id = :uid;
COMMIT;
