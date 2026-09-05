"""Bounded sector candidate-universe domain model and selector.

This module is deliberately upstream of the Strategy Engine.  It only decides
whether a security is a sufficiently tradable candidate for deeper analysis;
it never evaluates a setup and has no ``ENTRY_ALLOWED`` output.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import Enum
from typing import Iterable, Mapping, Sequence

from core import Quote


TOP_N_PER_SECTOR = 20
CN_PREFERRED_MAX_NOTIONAL = 10_000.0
CN_EXTENDED_MAX_NOTIONAL = 20_000.0
US_CANDIDATE_MAX_SHARE_NOTIONAL = 1_000.0
MIN_HISTORY_BARS = 60
MAX_HISTORY_STALENESS_DAYS = 7

SSE_MAIN_BOARD_RULE_URL = (
    "https://english.sse.com.cn/news/newsrelease/c/5725303.shtml"
)
SSE_STAR_BOARD_RULE_URL = (
    "https://big5.sse.com.cn/site/cht/www.sse.com.cn/star/en/gettingstarted/features/trading/"
)
SZSE_MAIN_BOARD_RULE_URL = (
    "https://www.szse.cn/English/rules/siteRule/P020181124401737559498.pdf"
)
SZSE_CHINEXT_BOARD_RULE_URL = (
    "https://www.szse.cn/English/rules/siteRule/P020200811392728112984.pdf"
)


class AffordabilityTier(str, Enum):
    CN_PREFERRED = "CN_PREFERRED"
    CN_EXTENDED_LOWER_PRIORITY = "CN_EXTENDED_LOWER_PRIORITY"
    US_CANDIDATE_ALLOWED = "US_CANDIDATE_ALLOWED"
    EXCLUDED = "EXCLUDED"


@dataclass(frozen=True)
class BoardRule:
    board: str
    minimum_quantity: int
    evidence_url: str


@dataclass(frozen=True)
class SeedSecurity:
    """Normalized security metadata from a bounded seed source."""

    market: str
    symbol: str
    name: str
    sector: str | None
    asset_class: str
    exchange: str | None
    currency: str
    source: str
    source_as_of: date | None = None
    reference_price: float | None = None
    board_rule: BoardRule | None = None
    metadata_status: str = "OK"
    source_symbol: str | None = None
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True)
class LiquidityMetrics:
    average_traded_notional_20d: float
    average_traded_notional_60d: float
    history_bar_count: int
    latest_history_date: date


@dataclass(frozen=True)
class CandidateRecord:
    market: str
    symbol: str
    name: str
    sector: str | None
    included: bool
    rank: int | None
    affordability_tier: AffordabilityTier
    price: float | None
    minimum_quantity: int | None
    minimum_executable_notional: float | None
    board: str | None
    board_rule_source: str | None
    average_traded_notional_20d: float | None
    average_traded_notional_60d: float | None
    history_bar_count: int
    latest_history_date: date | None
    source: str
    inclusion_reason: str | None
    exclusion_reason: str | None

    def to_row(self) -> dict[str, object]:
        """Return a lightweight, serializable audit row."""

        return {
            "market": self.market,
            "symbol": self.symbol,
            "name": self.name,
            "sector": self.sector,
            "included": self.included,
            "rank": self.rank,
            "affordability_tier": self.affordability_tier.value,
            "price": self.price,
            "minimum_quantity": self.minimum_quantity,
            "minimum_executable_notional": self.minimum_executable_notional,
            "board": self.board,
            "board_rule_source": self.board_rule_source,
            "average_traded_notional_20d": self.average_traded_notional_20d,
            "average_traded_notional_60d": self.average_traded_notional_60d,
            "history_bar_count": self.history_bar_count,
            "latest_history_date": (
                self.latest_history_date.isoformat()
                if self.latest_history_date
                else None
            ),
            "source": self.source,
            "inclusion_reason": self.inclusion_reason,
            "exclusion_reason": self.exclusion_reason,
        }


@dataclass(frozen=True)
class CandidateUniverse:
    as_of_date: date
    top_n_per_sector: int
    records: tuple[CandidateRecord, ...]

    @property
    def included(self) -> tuple[CandidateRecord, ...]:
        return tuple(record for record in self.records if record.included)

    def rows(self) -> list[dict[str, object]]:
        return [record.to_row() for record in self.records]


def infer_cn_board_rule(seed: SeedSecurity) -> BoardRule | None:
    """Resolve a documented minimum executable quantity for a CN stock.

    Unknown prefixes fail closed.  The selector must never silently apply the
    main-board 100-share rule to an unsupported board.
    """

    if seed.board_rule is not None:
        return seed.board_rule
    symbol = str(seed.symbol or "").upper()
    code, _, suffix = symbol.partition(".")
    exchange = str(seed.exchange or suffix).upper()
    if exchange in {"SH", "SSE", "XSHG"}:
        if code.startswith("688"):
            return BoardRule("SSE_STAR", 200, SSE_STAR_BOARD_RULE_URL)
        if code.startswith(("600", "601", "603", "605")):
            return BoardRule("SSE_MAIN", 100, SSE_MAIN_BOARD_RULE_URL)
    if exchange in {"SZ", "SZSE", "XSHE"}:
        if code.startswith(("300", "301")):
            return BoardRule("SZSE_CHINEXT", 100, SZSE_CHINEXT_BOARD_RULE_URL)
        if code.startswith(("000", "001", "002", "003")):
            return BoardRule("SZSE_MAIN", 100, SZSE_MAIN_BOARD_RULE_URL)
    return None


def _notional(quote: Quote) -> float | None:
    if quote.close is None or quote.volume is None:
        return None
    if float(quote.close) <= 0 or float(quote.volume) < 0:
        return None
    if quote.amount is not None:
        value = float(quote.amount)
    else:
        value = float(quote.close) * float(quote.volume)
    return value if value >= 0 else None


def _history_metrics(
    history: Sequence[Quote],
    as_of_date: date,
    *,
    min_history_bars: int,
    max_staleness_days: int,
) -> tuple[LiquidityMetrics | None, str | None]:
    if not history:
        return None, "HISTORY_INSUFFICIENT"
    if any(item.trade_date > as_of_date for item in history):
        return None, "HISTORY_CONTAINS_FUTURE_BAR"
    dates = [item.trade_date for item in history]
    if len(set(dates)) != len(dates):
        return None, "HISTORY_DUPLICATE_DATE"
    ordered = sorted(history, key=lambda item: item.trade_date)
    if len(ordered) < min_history_bars:
        return None, "HISTORY_INSUFFICIENT"
    if ordered[-1].trade_date < as_of_date - timedelta(days=max_staleness_days):
        return None, "HISTORY_STALE"
    notionals = [_notional(item) for item in ordered]
    if any(value is None for value in notionals):
        return None, "HISTORY_INVALID_OHLCV"
    values = [float(value) for value in notionals if value is not None]
    recent_60 = values[-60:]
    recent_20 = recent_60[-20:]
    return LiquidityMetrics(
        average_traded_notional_20d=sum(recent_20) / len(recent_20),
        average_traded_notional_60d=sum(recent_60) / len(recent_60),
        history_bar_count=len(ordered),
        latest_history_date=ordered[-1].trade_date,
    ), None


def _base_record(seed: SeedSecurity, reason: str) -> CandidateRecord:
    return CandidateRecord(
        market=seed.market,
        symbol=seed.symbol,
        name=seed.name,
        sector=seed.sector,
        included=False,
        rank=None,
        affordability_tier=AffordabilityTier.EXCLUDED,
        price=None,
        minimum_quantity=None,
        minimum_executable_notional=None,
        board=None,
        board_rule_source=None,
        average_traded_notional_20d=None,
        average_traded_notional_60d=None,
        history_bar_count=0,
        latest_history_date=None,
        source=seed.source,
        inclusion_reason=None,
        exclusion_reason=reason,
    )


def _evaluate_seed(
    seed: SeedSecurity,
    history: Sequence[Quote],
    as_of_date: date,
    *,
    min_history_bars: int,
    max_staleness_days: int,
) -> CandidateRecord:
    if seed.market not in {"CN", "US"}:
        return _base_record(seed, "UNSUPPORTED_MARKET")
    if seed.metadata_status != "OK":
        return _base_record(seed, f"METADATA_{seed.metadata_status}")
    if seed.asset_class.upper() != "EQUITY":
        return _base_record(seed, "ASSET_CLASS_NOT_EQUITY")
    if not str(seed.sector or "").strip():
        return _base_record(seed, "SECTOR_MISSING")

    metrics, history_reason = _history_metrics(
        history,
        as_of_date,
        min_history_bars=min_history_bars,
        max_staleness_days=max_staleness_days,
    )
    if history_reason or metrics is None:
        return _base_record(seed, history_reason or "HISTORY_UNAVAILABLE")
    price = float(sorted(history, key=lambda item: item.trade_date)[-1].close)

    minimum_quantity: int | None = None
    minimum_notional: float | None = None
    board: str | None = None
    board_source: str | None = None
    if seed.market == "CN":
        rule = infer_cn_board_rule(seed)
        if rule is None:
            return replace(
                _base_record(seed, "UNSUPPORTED_BOARD_RULE"),
                price=price,
                average_traded_notional_20d=metrics.average_traded_notional_20d,
                average_traded_notional_60d=metrics.average_traded_notional_60d,
                history_bar_count=metrics.history_bar_count,
                latest_history_date=metrics.latest_history_date,
            )
        minimum_quantity = rule.minimum_quantity
        minimum_notional = price * minimum_quantity
        board = rule.board
        board_source = rule.evidence_url
        if minimum_notional <= CN_PREFERRED_MAX_NOTIONAL:
            tier = AffordabilityTier.CN_PREFERRED
        elif minimum_notional <= CN_EXTENDED_MAX_NOTIONAL:
            tier = AffordabilityTier.CN_EXTENDED_LOWER_PRIORITY
        else:
            return CandidateRecord(
                market=seed.market,
                symbol=seed.symbol,
                name=seed.name,
                sector=seed.sector,
                included=False,
                rank=None,
                affordability_tier=AffordabilityTier.EXCLUDED,
                price=price,
                minimum_quantity=minimum_quantity,
                minimum_executable_notional=minimum_notional,
                board=board,
                board_rule_source=board_source,
                average_traded_notional_20d=metrics.average_traded_notional_20d,
                average_traded_notional_60d=metrics.average_traded_notional_60d,
                history_bar_count=metrics.history_bar_count,
                latest_history_date=metrics.latest_history_date,
                source=seed.source,
                inclusion_reason=None,
                exclusion_reason="CN_MINIMUM_NOTIONAL_OVER_20000",
            )
        inclusion_reason = (
            "CN_PREFERRED_AFFORDABILITY"
            if tier is AffordabilityTier.CN_PREFERRED
            else "CN_EXTENDED_AFFORDABILITY_LOWER_PRIORITY"
        )
    else:
        minimum_notional = price
        if minimum_notional > US_CANDIDATE_MAX_SHARE_NOTIONAL:
            return CandidateRecord(
                market=seed.market,
                symbol=seed.symbol,
                name=seed.name,
                sector=seed.sector,
                included=False,
                rank=None,
                affordability_tier=AffordabilityTier.EXCLUDED,
                price=price,
                minimum_quantity=1,
                minimum_executable_notional=minimum_notional,
                board=None,
                board_rule_source=None,
                average_traded_notional_20d=metrics.average_traded_notional_20d,
                average_traded_notional_60d=metrics.average_traded_notional_60d,
                history_bar_count=metrics.history_bar_count,
                latest_history_date=metrics.latest_history_date,
                source=seed.source,
                inclusion_reason=None,
                exclusion_reason="US_ONE_SHARE_NOTIONAL_OVER_1000",
            )
        tier = AffordabilityTier.US_CANDIDATE_ALLOWED
        minimum_quantity = 1
        inclusion_reason = "US_ONE_SHARE_AFFORDABILITY"

    return CandidateRecord(
        market=seed.market,
        symbol=seed.symbol,
        name=seed.name,
        sector=seed.sector,
        included=True,
        rank=None,
        affordability_tier=tier,
        price=price,
        minimum_quantity=minimum_quantity,
        minimum_executable_notional=minimum_notional,
        board=board,
        board_rule_source=board_source,
        average_traded_notional_20d=metrics.average_traded_notional_20d,
        average_traded_notional_60d=metrics.average_traded_notional_60d,
        history_bar_count=metrics.history_bar_count,
        latest_history_date=metrics.latest_history_date,
        source=seed.source,
        inclusion_reason=inclusion_reason,
        exclusion_reason=None,
    )


def select_candidate_universe(
    seeds: Iterable[SeedSecurity],
    histories: Mapping[str, Sequence[Quote]],
    as_of_date: date,
    *,
    top_n_per_sector: int = TOP_N_PER_SECTOR,
    min_history_bars: int = MIN_HISTORY_BARS,
    max_staleness_days: int = MAX_HISTORY_STALENESS_DAYS,
) -> CandidateUniverse:
    """Apply bounded affordability, history, liquidity and sector ranking.

    Liquidity is only a ranking proxy: 20D/60D traded notional, using the
    provider amount when available and otherwise ``close * volume``.  There is
    intentionally no new absolute cross-market liquidity threshold.
    """

    if top_n_per_sector <= 0:
        raise ValueError("top_n_per_sector must be positive")
    if min_history_bars < 60:
        raise ValueError("min_history_bars must support the 60D liquidity proxy")

    evaluated = [
        _evaluate_seed(
            seed,
            histories.get(seed.symbol, ()),
            as_of_date,
            min_history_bars=min_history_bars,
            max_staleness_days=max_staleness_days,
        )
        for seed in seeds
    ]
    by_sector: dict[tuple[str, str], list[CandidateRecord]] = {}
    for record in evaluated:
        if record.included and record.sector:
            by_sector.setdefault((record.market, record.sector), []).append(record)

    affordability_priority = {
        AffordabilityTier.CN_PREFERRED: 0,
        AffordabilityTier.US_CANDIDATE_ALLOWED: 0,
        AffordabilityTier.CN_EXTENDED_LOWER_PRIORITY: 1,
    }
    replacements: dict[str, CandidateRecord] = {}
    for records in by_sector.values():
        ranked = sorted(
            records,
            key=lambda record: (
                affordability_priority[record.affordability_tier],
                -float(record.average_traded_notional_20d or 0),
                -float(record.average_traded_notional_60d or 0),
                record.symbol,
            ),
        )
        for rank, record in enumerate(ranked, start=1):
            if rank > top_n_per_sector:
                replacements[record.symbol] = replace(
                    record,
                    included=False,
                    rank=rank,
                    inclusion_reason=None,
                    exclusion_reason="SECTOR_TOP_N_EXCEEDED",
                )
            else:
                replacements[record.symbol] = replace(record, rank=rank)

    final_records = []
    for record in evaluated:
        final_records.append(replacements.get(record.symbol, record))
    final_records.sort(
        key=lambda record: (
            record.market,
            record.sector or "",
            0 if record.included else 1,
            record.rank if record.rank is not None else 10**9,
            record.symbol,
        )
    )
    return CandidateUniverse(
        as_of_date=as_of_date,
        top_n_per_sector=top_n_per_sector,
        records=tuple(final_records),
    )


__all__ = [
    "AffordabilityTier",
    "BoardRule",
    "CandidateRecord",
    "CandidateUniverse",
    "CN_EXTENDED_MAX_NOTIONAL",
    "CN_PREFERRED_MAX_NOTIONAL",
    "LiquidityMetrics",
    "MAX_HISTORY_STALENESS_DAYS",
    "MIN_HISTORY_BARS",
    "SSE_MAIN_BOARD_RULE_URL",
    "SSE_STAR_BOARD_RULE_URL",
    "SeedSecurity",
    "SZSE_CHINEXT_BOARD_RULE_URL",
    "SZSE_MAIN_BOARD_RULE_URL",
    "TOP_N_PER_SECTOR",
    "US_CANDIDATE_MAX_SHARE_NOTIONAL",
    "infer_cn_board_rule",
    "select_candidate_universe",
]
