"""Manually requested, source-scoped Eastmoney sentiment snapshots."""

from datetime import date, datetime, timedelta, timezone
import hashlib
import json

from src.core.trading_calendar import get_trading_dates
from src.data.csmar_daily import CsmarDataset, CsmarDay, CsmarSourceError
from src.repositories.sentiment_repo import SentimentRepository
from src.services.sentiment_calendar import trading_sessions
from src.services.sentiment_snapshot_service import compute_snapshot


EASTMONEY_MARKET = "CN_A_EASTMONEY_POOL"
EASTMONEY_VERSION = "eastmoney-pool-v1-market-day-streak"


def _fetch_pool(kind: str, day: date):
    """Reuse the project's bounded AkShare call; failures are never zero rows."""
    import akshare as ak
    from data_provider.akshare_fetcher import _akshare_call_with_timeout

    functions = {"closed": ak.stock_zt_pool_em, "broken": ak.stock_zt_pool_zbgc_em,
                 "previous": ak.stock_zt_pool_previous_em}
    last_error = None
    for _ in range(2):
        try:
            result = _akshare_call_with_timeout(functions[kind], date=day.strftime("%Y%m%d"),
                                                 timeout=15, call_name="sentiment_" + kind)
            if result is not None and not result.empty:
                return result
        except Exception as exc:
            last_error = exc
    raise CsmarSourceError(f"Eastmoney {kind} pool empty or unavailable for {day}") from last_error


def _codes(frame, kind: str) -> set[str]:
    if "代码" not in frame.columns:
        raise CsmarSourceError(f"Eastmoney {kind} pool lacks stock codes")
    codes = [str(value).strip() for value in frame["代码"]]
    if any(len(code) != 6 or not code.isascii() or not code.isdigit() for code in codes):
        raise CsmarSourceError(f"Eastmoney {kind} pool contains invalid stock codes")
    if len(codes) != len(set(codes)) or len(codes) >= (10000 if kind == "closed" else 5000):
        raise CsmarSourceError(f"Eastmoney {kind} pool has duplicates or may be truncated")
    return set(codes)


def build_eastmoney_snapshot(trade_date: date) -> dict:
    now = datetime.now(timezone(timedelta(hours=8)))
    if trade_date > now.date() or (trade_date == now.date() and now.hour < 15):
        raise CsmarSourceError("Eastmoney close snapshot requires a completed trading session")
    sessions = sorted(trading_sessions(get_trading_dates, trade_date - timedelta(days=100), trade_date))
    if not sessions or sessions[-1] != trade_date:
        raise CsmarSourceError("target date is not a supported trading session")

    current = _fetch_pool("closed", trade_date)
    closed = _codes(current, "closed")
    if "连板数" not in current.columns:
        raise CsmarSourceError("Eastmoney closed pool lacks streak counts")
    claimed = {}
    for code, count in zip(current["代码"], current["连板数"]):
        try:
            number = float(count)
            if not number.is_integer() or not 1 <= number <= 30:
                raise ValueError
            claimed[str(code).strip()] = int(number)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CsmarSourceError("Eastmoney closed pool has invalid streak counts") from exc
    needed = max(3, max(claimed.values()) + 1)
    if len(sessions) < needed:
        raise CsmarSourceError("not enough trading sessions to verify streak history")
    selected = sessions[-needed:]
    days = {trade_date: CsmarDay(closed=closed)}
    for day in selected[:-1]:
        days[day] = CsmarDay(closed=_codes(_fetch_pool("closed", day), "closed"))
    previous = _codes(_fetch_pool("previous", trade_date), "previous")
    if previous != days[selected[-2]].closed:
        raise CsmarSourceError("Eastmoney previous pool differs from previous session's closed pool")
    broken = _codes(_fetch_pool("broken", trade_date), "broken")
    if closed & broken:
        raise CsmarSourceError("Eastmoney closed and broken pools overlap")
    days[trade_date].broken = broken
    days[trade_date].touched = closed | broken

    for code, expected in claimed.items():
        actual = 0
        for day in reversed(selected):
            if code not in days[day].closed:
                break
            actual += 1
        if actual != expected:
            raise CsmarSourceError("Eastmoney streak counts disagree with daily pools")

    inputs = {"closed": {day.isoformat(): sorted(days[day].closed) for day in selected},
              "broken": sorted(broken), "previous": sorted(previous), "claimed_streak": claimed}
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    # Reuse the existing pool calculation. Replace its CSMAR-specific trace and
    # scope below before the result can be persisted or returned.
    dataset = CsmarDataset(days, digest, "", sum(len(x.closed) for x in days.values()), "", "A1:B1", 2)
    snapshot = compute_snapshot(dataset, trade_date)
    snapshot["market"] = EASTMONEY_MARKET
    snapshot["definition_version"] = EASTMONEY_VERSION
    snapshot["provider_trace"] = {"provider": "eastmoney_akshare", "as_of_sha256": digest,
                                  "retrieved_at": datetime.now(timezone.utc).isoformat()}
    snapshot["completeness"] = {
        "scope": "Eastmoney provider limit pools; not verified full A-share or main-board coverage",
        "date_min": selected[0].isoformat(), "date_max": trade_date.isoformat(),
        "date_count": len(selected), "previous_pool_matches": True,
        "streak_counts_match": True, "closed_broken_disjoint": True,
        "independent_market_coverage_verified": False,
    }
    return snapshot


def generate_eastmoney_snapshot(session, trade_date: date):
    return SentimentRepository(session).save(build_eastmoney_snapshot(trade_date))
