"""Data models for the Keepa-style Watch Price Comparator (Neuf & Occasion)."""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


@dataclass
class WatchURL:
    url: str
    merchant: str = ""
    condition: str = "new"  # "new" (Neuf) or "used" (Occasion)
    shipping_fee: Optional[float] = None  # Frais de port (€) - None = auto-detect if stated on site
    site_fee: Optional[float] = None      # Frais du site / protection acheteur (€)
    customs_fee: Optional[float] = None   # Frais de douane & TVA import (€)
    manual_price: Optional[float] = None  # Prix affiché saisi ou mis en cache (€)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SuggestedURL:
    url: str
    merchant: str
    title: str = ""
    condition: str = "new"
    estimated_base_price: Optional[float] = None
    shipping_fee: Optional[float] = None
    site_fee: Optional[float] = None
    customs_fee: Optional[float] = None
    fee_hint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WatchConfig:
    id: str
    name: str
    brand: str
    reference: str
    features: str
    target_price_new: Optional[float] = None   # Prix seuil notification Neuf (€)
    target_price_used: Optional[float] = None  # Prix seuil notification Occasion (€)
    reference_price: float = 0.0               # Prix public conseillé indicatif (€)
    ean: str = ""
    asin: str = ""
    image_url: str = ""
    specs: Dict[str, str] = field(default_factory=dict)
    urls: List[WatchURL] = field(default_factory=list)
    suggested_urls: List[SuggestedURL] = field(default_factory=list)

    @property
    def target_price(self) -> float:
        """Backward-compatible helper returning the primary threshold."""
        if self.target_price_new is not None:
            return self.target_price_new
        if self.target_price_used is not None:
            return self.target_price_used
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OfferResult:
    watch_id: str
    merchant: str
    url: str
    price: Optional[float]                     # Prix TOTAL tout compris (base + port + site + douane)
    base_price: Optional[float] = None         # Prix affiché hors frais additionnels
    condition: str = "new"                     # "new" | "used"
    shipping_fee: float = 0.0
    site_fee: float = 0.0
    customs_fee: float = 0.0
    shipping_detected: bool = False
    site_fee_detected: bool = False
    customs_detected: bool = False
    fee_notes: List[str] = field(default_factory=list)
    original_price: Optional[float] = None
    currency: str = "EUR"
    in_stock: bool = True
    title: str = ""
    extraction_method: str = "unknown"
    timestamp: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WatchAnalysis:
    watch: WatchConfig
    offers: List[OfferResult]
    best_new_offer: Optional[OfferResult]
    best_used_offer: Optional[OfferResult]
    lowest_new_historical: Optional[float]
    highest_new_historical: Optional[float]
    avg_new_historical: Optional[float]
    lowest_used_historical: Optional[float]
    highest_used_historical: Optional[float]
    avg_used_historical: Optional[float]
    previous_new_price: Optional[float]
    previous_used_price: Optional[float]
    drop_new_vs_previous: float
    drop_used_vs_previous: float
    alert_new_triggered: bool
    alert_used_triggered: bool

    @property
    def best_offer(self) -> Optional[OfferResult]:
        candidates = [o for o in (self.best_new_offer, self.best_used_offer) if o and o.price is not None]
        if not candidates:
            return None
        return min(candidates, key=lambda o: o.price)  # type: ignore
