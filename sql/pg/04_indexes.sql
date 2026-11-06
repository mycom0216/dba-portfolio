-- 튜닝: 쿼리 패턴에서 역산한 인덱스. 인덱스 하나하나가 쓰기 비용이므로 쿼리 1개당 1개 이하로 최소화했다.

-- Q1, Q4: 기간 범위 + 집계에 필요한 컬럼을 INCLUDE 로 얹어 힙 접근 없이 처리(Index Only Scan)
CREATE INDEX idx_donations_created ON donations (created_at) INCLUDE (broadcast_id, points);

-- Q2: 등치(user_id) 조건 다음에 정렬 컬럼 -> 인덱스 순서대로 읽고 20건에서 멈춤(정렬 제거)
CREATE INDEX idx_listens_user_joined ON listens (user_id, joined_at DESC);

-- Q3: '청취 중'(left_at IS NULL)은 전체의 0.08% -> 부분 인덱스로 크기와 쓰기 비용을 거의 0 에 가깝게
CREATE INDEX idx_listens_live ON listens (broadcast_id) WHERE left_at IS NULL;

-- Q5: FK 컬럼(PostgreSQL 은 자동 생성 안 함) + 집계에 필요한 컬럼 포함
CREATE INDEX idx_donations_broadcast ON donations (broadcast_id) INCLUDE (sender_id, points);

-- Index Only Scan 은 visibility map 이 채워져 있어야 힙을 안 읽는다 -> 대량 적재 직후에는 VACUUM 으로 채운다
VACUUM (ANALYZE) donations;
VACUUM (ANALYZE) listens;
