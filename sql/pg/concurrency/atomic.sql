-- [해법 2] 조건부 원자적 UPDATE. 검증(잔액 >= 금액)과 차감을 한 문장으로 끝낸다.
-- 잔액 부족이면 0 rows 가 갱신되므로 앱은 영향 행 수로 성공/실패를 판단한다.
-- 앱 처리 시간(2ms)은 잠금 '밖'에서 일어난다: 검증이 SQL 안으로 들어갔기 때문에 행 잠금을 쥔 채 앱 로직을 기다릴 필요가 없다.
-- (naive/for_update 는 읽은 값을 앱이 검증하는 동안 트랜잭션이 열려 있다. 이 차이가 처리량 차이의 원인이다.)
\set uid random(1, 10)
\set pts 10
SELECT pg_sleep(0.002);
BEGIN;
UPDATE wallets SET balance_points = balance_points - :pts WHERE user_id = :uid AND balance_points >= :pts;
COMMIT;
