-- [데드락 해결] 항상 user_id 오름차순으로 먼저 잠근 뒤 갱신한다. 모든 트랜잭션이 같은 순서로 잠그면 순환이 불가능하다.
\set a random(1, 4)
\set d random(1, 3)
\set b (:a + :d - 1) % 4 + 1
BEGIN;
SELECT 1 FROM wallets WHERE user_id IN (:a, :b) ORDER BY user_id FOR UPDATE;
UPDATE wallets SET balance_points = balance_points - 1 WHERE user_id = :a;
SELECT pg_sleep(0.002);
UPDATE wallets SET balance_points = balance_points + 1 WHERE user_id = :b;
COMMIT;
