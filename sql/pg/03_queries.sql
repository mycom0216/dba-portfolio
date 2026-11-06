-- 튜닝 대상 쿼리. bench_queries.py 가 '-- name:' 단위로 잘라서 EXPLAIN (ANALYZE, BUFFERS) 로 실행한다.
-- 서비스에서 실제로 나올 법한 조회 패턴 5개 (파라미터는 시드 데이터에서 의미 있는 값으로 고정)

-- name: Q1 최근 7일 후원 합계 상위 방송 (범위 조건 + 집계)
SELECT broadcast_id, SUM(points) AS total_points
FROM donations
WHERE created_at >= '2026-10-01' AND created_at < '2026-10-08'
GROUP BY broadcast_id
ORDER BY total_points DESC, broadcast_id
LIMIT 10;

-- name: Q2 유저의 최근 청취 이력 20건 (필터 + 정렬 + LIMIT)
SELECT listen_id, broadcast_id, joined_at
FROM listens
WHERE user_id = 12345
ORDER BY joined_at DESC
LIMIT 20;

-- name: Q3 특정 방송의 현재 청취자 수 (NULL 조건, 선택도가 매우 낮음)
SELECT COUNT(*)
FROM listens
WHERE broadcast_id = 1 AND left_at IS NULL;

-- name: Q4 하루치 후원 건수 - 컬럼을 함수로 감싼 조건 (non-sargable)
SELECT COUNT(*)
FROM donations
WHERE date_trunc('day', created_at) = '2026-10-05';

-- name: Q5 방송의 후원 상위 유저 10명 + 닉네임 (JOIN + 집계)
SELECT u.nickname, SUM(d.points) AS total_points
FROM donations d
JOIN users u ON u.user_id = d.sender_id
WHERE d.broadcast_id = 1
GROUP BY u.user_id, u.nickname
ORDER BY total_points DESC, u.user_id
LIMIT 10;
