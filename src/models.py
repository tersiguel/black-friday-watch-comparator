"""Data models for the Black Friday Watch Price Comparator."""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


@dataclass
class WatchURL:
    url: str
    merchant: str = ""


@dataclass
class WatchConfig:
    id: str
    name: str
    brand: str
    reference: str
    features: str
    target_price: float
    reference_price: float
    search_queries: List[str] = field(default_factory=list)
    urls: List[WatchURL] = field(default_factory=list)


@dataclass
class OfferResult:
    watch_id: str
    merchant: str
    url: str
    price: Optional[float]
    original_price: Optional[float] = None
    currency: str = "EUR"
    in_stock: bool = True
    title: str = ""
    extraction_method: str = "unknown"  # json-ld, opengraph, selector, heuristic, playwright, simulated
    promo_code: Optional[str] = None
    shipping_note: Optional[str] = None
    timestamp: str = ""
    error: Optional[str] = None
    is_discovered: bool = False
    temperature: Optional[str] = None  # For Dealabs deals e.g. "245°"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WatchAnalysis:
    watch: WatchConfig
    offers: List[OfferResult]
    discovered_offers: List[OfferResult]
    best_offer: Optional[OfferResult]
    lowest_historical_price: Optional[float]
    highest_historical_price: Optional[float]
    previous_best_price: Optional[float]
    discount_vs_msrp_pct: float
    discount_vs_target_diff: float
    price_drop_vs_previous: float
    is_fake_promo: bool
    fake_promo_reason: Optional[str]
    bf_score: int  # 0 to 100
    bf_verdict: str  # Badge label
    bf_verdict_level: str  # "exceptional", "target_reached", "good", "fake_promo", "wait"
