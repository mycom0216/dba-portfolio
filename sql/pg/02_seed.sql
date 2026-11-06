-- 합성 데이터 생성 (PostgreSQL). setseed 로 재현 가능.
-- 규모: users 200k / broadcasts 100k / listens 3M / donations 1M  (개인 PC 기준으로 줄인 값)
--
-- 주의(실제로 겪은 버그): 행마다 달라야 하는 random() 값을 'LATERAL (SELECT ... random())' 로 만들면
-- 바깥 행에 의존하지 않는 서브쿼리라서 '한 번만' 평가되어 모든 행에 같은 값이 들어간다.
-- 그래서 값을 FROM 절의 서브쿼리 SELECT 목록에서 만든다(volatile 함수가 있는 서브쿼리는 행마다 평가된다).
-- 생성 후 02b_seed_check.sql 로 분포를 검증한다.
SELECT setseed(0.42);

INSERT INTO users
SELECT g,
       'user_' || md5(g::text)::text,
       (ARRAY['KR','KR','KR','KR','JP','US','VN','TH'])[1 + (g % 8)],
       (CASE WHEN random() < 0.90 THEN 1 WHEN random() < 0.8 THEN 2 ELSE 3 END)::smallint,
       timestamptz '2025-01-01' + (random() * interval '600 days')
FROM generate_series(1, 200000) g;

INSERT INTO wallets SELECT user_id, (random() * 100000)::bigint, now() FROM users;

INSERT INTO gifts VALUES (1,'하트',10),(2,'꽃',50),(3,'왕관',200),(4,'로켓',1000),(5,'다이아',5000);

-- 방송: 호스트는 일부 유저에 몰리도록(상위 일부가 대부분의 방송) 편향시킨다 -> 실제 서비스의 쏠림(skew)을 흉내
INSERT INTO broadcasts
SELECT s.g,
       1 + floor(200000 * power(random(), 2.5))::bigint,
       'broadcast ' || s.g,
       (1 + s.g % 12)::smallint,
       s.st,
       CASE WHEN s.g > 99900 THEN NULL ELSE s.st + (random() * interval '3 hours') END
FROM (SELECT g, timestamptz '2026-01-01' + (random() * interval '300 days') AS st
      FROM generate_series(1, 100000) g) s;

-- 청취 이력: 인기 방송(번호가 작을수록)에 몰리게 편향
INSERT INTO listens
SELECT j.g,
       1 + floor(100000 * power(random(), 1.8))::bigint,
       1 + floor(200000 * random())::bigint,
       j.t,
       CASE WHEN random() < 0.0008 THEN NULL ELSE j.t + (random() * interval '2 hours') END
FROM (SELECT g, timestamptz '2026-01-01' + (random() * interval '300 days') AS t
      FROM generate_series(1, 3000000) g) j;

-- 후원: 값싼 선물이 훨씬 많이 나가도록 (gift_id 1 이 가장 흔함)
INSERT INTO donations
SELECT d.g,
       1 + floor(100000 * power(random(), 1.8))::bigint,
       1 + floor(200000 * random())::bigint,
       d.gid,
       (SELECT price_points FROM gifts WHERE gift_id = d.gid),
       timestamptz '2026-01-01' + (random() * interval '300 days')
FROM (SELECT g, 1 + floor(random() * random() * 5)::int AS gid
      FROM generate_series(1, 1000000) g) d;

ANALYZE;
