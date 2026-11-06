"""ORM(SQLAlchemy 2) 이 만드는 쿼리 문제 두 가지를 실측한다.

 실험 1  N+1: 방송 20개의 후원 내역과 후원자 닉네임을 읽을 때 lazy loading vs selectinload vs joinedload (쿼리 수, 시간)
 실험 2  ORM 에서도 non-sargable: func.date_trunc(컬럼) = 값  vs  컬럼 범위 조건 (Q4 와 같은 함정)

DBA 관점: ORM 을 쓰면 SQL 을 직접 안 쓰는 대신, 슬로우 쿼리 로그에서 '같은 모양의 쿼리가 수백 번' 찍히는 것으로 N+1 을 찾는다.
사용: python tools/orm_exp.py     (PostgreSQL 기동 + 시드 + 인덱스 적용 상태, pip install sqlalchemy "psycopg[binary]")
"""
import json
import statistics
import time
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, create_engine, event, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, joinedload, mapped_column, relationship, selectinload

from common import PG_PORT, RESULTS


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nickname: Mapped[str] = mapped_column(String)


class Broadcast(Base):
    __tablename__ = "broadcasts"
    broadcast_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    donations: Mapped[list["Donation"]] = relationship(back_populates="broadcast")


class Donation(Base):
    __tablename__ = "donations"
    donation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    broadcast_id: Mapped[int] = mapped_column(ForeignKey("broadcasts.broadcast_id"))
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    points: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    broadcast: Mapped[Broadcast] = relationship(back_populates="donations")
    sender: Mapped[User] = relationship()


engine = create_engine(f"postgresql+psycopg://postgres@127.0.0.1:{PG_PORT}/lab")
counter = {"n": 0}


@event.listens_for(engine, "before_cursor_execute")
def _count(conn, cursor, statement, parameters, context, executemany):
    counter["n"] += 1


def run(fn, rounds=3):
    times, queries, result = [], 0, None
    for _ in range(rounds):
        counter["n"] = 0
        with Session(engine) as s:
            t = time.perf_counter()
            result = fn(s)
            times.append((time.perf_counter() - t) * 1000)
            queries = counter["n"]
    return {"queries": queries, "ms": round(statistics.median(times), 1)}, result


def main():
    with Session(engine) as s:  # 후원이 20~60건인 방송 20개 (너무 인기 있는 방송은 제외)
        ids = list(s.execute(text("SELECT broadcast_id FROM donations GROUP BY 1 HAVING count(*) BETWEEN 20 AND 60 ORDER BY 1 LIMIT 20")).scalars())

    def report(s, opts):
        rows = []
        stmt = select(Broadcast).where(Broadcast.broadcast_id.in_(ids)).order_by(Broadcast.broadcast_id)
        if opts:
            stmt = stmt.options(*opts)
        for b in s.scalars(stmt).unique():
            for d in sorted(b.donations, key=lambda d: d.donation_id):
                rows.append((b.broadcast_id, d.donation_id, d.sender.nickname, d.points))
        return rows

    out = {"broadcasts": len(ids)}
    stat, base_rows = run(lambda s: report(s, None))
    out["N+1 (lazy loading)"] = stat | {"rows": len(base_rows)}
    for name, opts in (("selectinload", [selectinload(Broadcast.donations).selectinload(Donation.sender)]),
                       ("joinedload", [joinedload(Broadcast.donations).joinedload(Donation.sender)])):
        stat, rows = run(lambda s, o=opts: report(s, o))
        out[name] = stat | {"rows": len(rows), "same_result_as_lazy": rows == base_rows}

    day = datetime(2026, 10, 5, tzinfo=timezone.utc)
    nxt = datetime(2026, 10, 6, tzinfo=timezone.utc)
    q_wrapped = select(func.count()).select_from(Donation).where(func.date_trunc("day", Donation.created_at) == day)
    q_range = select(func.count()).select_from(Donation).where(Donation.created_at >= day, Donation.created_at < nxt)
    s1, r1 = run(lambda s: s.scalar(q_wrapped), 5)
    s2, r2 = run(lambda s: s.scalar(q_range), 5)
    out["filter_wrapped_in_function"] = s1 | {"count": r1, "sql": str(q_wrapped.compile(engine)).replace("\n", " ")}
    out["filter_range"] = s2 | {"count": r2, "same_count": r1 == r2, "sql": str(q_range.compile(engine)).replace("\n", " ")}

    (RESULTS / "orm_experiment.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
