-- 같은 모델의 MySQL 8.4 (InnoDB) 버전. PostgreSQL 스키마와 컬럼을 1:1 로 맞춘다.
-- 시각은 UTC 로 저장한 DATETIME(6) (PostgreSQL 쪽도 timezone=UTC 로 맞춤 -> 같은 리터럴이 같은 행 집합을 가리킨다).
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS donations, listens, broadcasts, wallets, gifts, users;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE users (
    user_id     BIGINT PRIMARY KEY,
    nickname    VARCHAR(64) NOT NULL,
    country     CHAR(2)     NOT NULL,
    status      TINYINT     NOT NULL DEFAULT 1,
    created_at  DATETIME(6) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE wallets (
    user_id         BIGINT PRIMARY KEY,
    balance_points  BIGINT      NOT NULL,
    updated_at      DATETIME(6) NOT NULL,
    CONSTRAINT chk_balance CHECK (balance_points >= 0),
    FOREIGN KEY (user_id) REFERENCES users (user_id)
) ENGINE=InnoDB;

CREATE TABLE gifts (
    gift_id       INT PRIMARY KEY,
    name          VARCHAR(32) NOT NULL,
    price_points  INT NOT NULL
) ENGINE=InnoDB;

CREATE TABLE broadcasts (
    broadcast_id  BIGINT PRIMARY KEY,
    host_id       BIGINT       NOT NULL,
    title         VARCHAR(100) NOT NULL,
    category      TINYINT      NOT NULL,
    started_at    DATETIME(6)  NOT NULL,
    ended_at      DATETIME(6)  NULL,
    FOREIGN KEY (host_id) REFERENCES users (user_id)
) ENGINE=InnoDB;

CREATE TABLE listens (
    listen_id     BIGINT PRIMARY KEY,
    broadcast_id  BIGINT      NOT NULL,
    user_id       BIGINT      NOT NULL,
    joined_at     DATETIME(6) NOT NULL,
    left_at       DATETIME(6) NULL,
    FOREIGN KEY (broadcast_id) REFERENCES broadcasts (broadcast_id),
    FOREIGN KEY (user_id) REFERENCES users (user_id)
) ENGINE=InnoDB;

CREATE TABLE donations (
    donation_id   BIGINT PRIMARY KEY,
    broadcast_id  BIGINT      NOT NULL,
    sender_id     BIGINT      NOT NULL,
    gift_id       INT         NOT NULL,
    points        INT         NOT NULL,
    created_at    DATETIME(6) NOT NULL,
    FOREIGN KEY (broadcast_id) REFERENCES broadcasts (broadcast_id),
    FOREIGN KEY (sender_id) REFERENCES users (user_id),
    FOREIGN KEY (gift_id) REFERENCES gifts (gift_id)
) ENGINE=InnoDB;
-- 차이점: InnoDB 는 FK 컬럼에 인덱스를 자동 생성한다(listens.broadcast_id/user_id, donations.broadcast_id/sender_id).
-- 그래서 MySQL 의 '튜닝 전' 상태는 PostgreSQL(보조 인덱스 0개)보다 이미 유리하다. 비교할 때 이 점을 감안해야 한다.
