-- name: Q4 하루치 후원 건수 - 범위 조건으로 재작성 (sargable)
SELECT COUNT(*)
FROM donations
WHERE created_at >= '2026-10-05' AND created_at < '2026-10-06';

-- name: Q5 방송의 후원 상위 유저 10명 - 집계를 먼저 하고 상위 10명에게만 JOIN
SELECT u.nickname, t.total_points
FROM (
    SELECT sender_id, SUM(points) AS total_points
    FROM donations
    WHERE broadcast_id = 1
    GROUP BY sender_id
    ORDER BY total_points DESC, sender_id
    LIMIT 10
) t
JOIN users u ON u.user_id = t.sender_id
ORDER BY t.total_points DESC, t.sender_id;
