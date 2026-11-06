-- 라이브 오디오 서비스 가상 스키마 (PostgreSQL 16)
-- 주의: 스푼랩스의 실제 스키마가 아니라, 공고의 업무(스키마 설계/튜닝/트랜잭션)를 연습하기 위해 직접 만든 모델이다.
-- 시간대는 UTC 로 고정한다 (tools/setup_pg.py 가 DB 기본값으로 설정). 날짜 리터럴 해석이 환경마다 달라지지 않게 하는 장치.
DO $$ BEGIN IF current_setting('TimeZone') <> 'UTC' THEN RAISE EXCEPTION 'timezone 이 UTC 가 아니다: python tools/setup_pg.py start 로 설정 후 새 세션에서 실행'; END IF; END $$;

DROP TABLE IF EXISTS donations, listens, broadcasts, wallets, gifts, users CASCADE;

CREATE TABLE users (
    user_id     bigint PRIMARY KEY,
    nickname    text        NOT NULL,
    country     char(2)     NOT NULL,
    status      smallint    NOT NULL DEFAULT 1,           -- 1 활성, 2 휴면, 3 정지
    created_at  timestamptz NOT NULL
);

CREATE TABLE wallets (                                    -- 포인트 잔액: 1 유저 1 행, 동시성 실험의 핵심 테이블
    user_id         bigint PRIMARY KEY REFERENCES users,
    balance_points  bigint      NOT NULL CHECK (balance_points >= 0),  -- 음수 잔액을 DB 레벨에서 차단
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE gifts (
    gift_id       int PRIMARY KEY,
    name          text NOT NULL,
    price_points  int  NOT NULL CHECK (price_points > 0)
);

CREATE TABLE broadcasts (
    broadcast_id  bigint PRIMARY KEY,
    host_id       bigint      NOT NULL REFERENCES users,
    title         text        NOT NULL,
    category      smallint    NOT NULL,
    started_at    timestamptz NOT NULL,
    ended_at      timestamptz                               -- NULL 이면 진행 중
);

CREATE TABLE listens (                                    -- 청취 이력: 가장 빨리 커지는 테이블
    listen_id     bigint PRIMARY KEY,
    broadcast_id  bigint      NOT NULL REFERENCES broadcasts,
    user_id       bigint      NOT NULL REFERENCES users,
    joined_at     timestamptz NOT NULL,
    left_at       timestamptz                               -- NULL 이면 청취 중
);

CREATE TABLE donations (                                  -- 후원(선물) 내역
    donation_id   bigint PRIMARY KEY,
    broadcast_id  bigint      NOT NULL REFERENCES broadcasts,
    sender_id     bigint      NOT NULL REFERENCES users,
    gift_id       int         NOT NULL REFERENCES gifts,
    points        int         NOT NULL CHECK (points > 0),
    created_at    timestamptz NOT NULL
);
-- 의도적으로 보조 인덱스를 만들지 않는다: 02 단계의 '튜닝 전' 기준선(baseline)을 만들기 위해서다.
-- (PostgreSQL 은 FK 컬럼에 인덱스를 자동 생성하지 않는다. MySQL InnoDB 는 FK 컬럼에 자동 생성한다 -> 비교 포인트)
