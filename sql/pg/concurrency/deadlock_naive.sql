-- [데드락 재현] 후원자 지갑을 먼저 차감하고 수신자 지갑을 증가. 서로 반대 방향 전송이 동시에 오면 잠금 순환이 생긴다.
\set a random(1, 4)
\set d random(1, 3)
\set b (:a + :d - 1) % 4 + 1
BEGIN;
UPDATE wallets SET balance_points = balance_points - 1 WHERE user_id = :a;
SELECT pg_sleep(0.002);
UPDATE wallets SET balance_points = balance_points + 1 WHERE user_id = :b;
COMMIT;
