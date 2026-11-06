-- 시드 데이터 분포 검증: 값이 행마다 다르게 생성됐는지(위의 LATERAL 버그 재발 방지) 확인하고, 아니면 실패시킨다.
DO $$
DECLARE
    d_joined bigint; d_gift int; d_start bigint; d_created bigint; skew numeric;
BEGIN
    SELECT count(DISTINCT joined_at) INTO d_joined FROM listens;
    SELECT count(DISTINCT gift_id)   INTO d_gift   FROM donations;
    SELECT count(DISTINCT started_at) INTO d_start FROM broadcasts;
    SELECT count(DISTINCT created_at) INTO d_created FROM donations;
    SELECT round(100.0 * count(*) FILTER (WHERE broadcast_id <= 1000) / count(*), 1) INTO skew FROM listens;

    RAISE NOTICE 'listens.joined_at distinct=%, donations.gift_id distinct=%, broadcasts.started_at distinct=%, donations.created_at distinct=%, 상위 1%% 방송의 청취 비중=% %%',
        d_joined, d_gift, d_start, d_created, skew;

    IF d_joined  < 2900000 THEN RAISE EXCEPTION 'listens.joined_at 이 거의 같은 값이다 (distinct=%)', d_joined; END IF;
    IF d_gift    <       5 THEN RAISE EXCEPTION 'donations.gift_id 가 5종 미만이다 (distinct=%)', d_gift; END IF;
    IF d_start   <   90000 THEN RAISE EXCEPTION 'broadcasts.started_at 이 거의 같은 값이다 (distinct=%)', d_start; END IF;
    IF d_created <  900000 THEN RAISE EXCEPTION 'donations.created_at 이 거의 같은 값이다 (distinct=%)', d_created; END IF;
END $$;
