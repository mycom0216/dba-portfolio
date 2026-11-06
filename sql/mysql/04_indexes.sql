-- MySQL 용 인덱스. PostgreSQL 과 같은 쿼리 패턴을 겨냥하되 기능 차이 때문에 모양이 다르다.

-- Q1, Q4: INCLUDE 절이 없으므로 필요한 컬럼을 키 뒤에 붙여 커버링 인덱스로 만든다
CREATE INDEX idx_donations_created ON donations (created_at, broadcast_id, points);

-- Q2: MySQL 8.0+ 는 DESC 인덱스를 지원한다
CREATE INDEX idx_listens_user_joined ON listens (user_id, joined_at DESC);

-- Q3: 부분 인덱스(WHERE 절 인덱스)가 없다 -> (broadcast_id, left_at) 전체를 색인. NULL 도 B-Tree 에 저장되므로 IS NULL 에 사용 가능.
CREATE INDEX idx_listens_live ON listens (broadcast_id, left_at);

-- Q5: 커버링
CREATE INDEX idx_donations_broadcast ON donations (broadcast_id, sender_id, points);

ANALYZE TABLE donations, listens;
