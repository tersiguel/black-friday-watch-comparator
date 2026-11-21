"""Data models for the Keepa-style Watch Price Comparator (Neuf & Occasion)."""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


def normalize_promo_type(val: Any) -> str:
    """Normalize promotion type to 'eur' or 'pct'."""
    s = str(val or "eur").strip().lower()
    if s in ("pct", "%", "percent", "pourcent", "pourcentage"):
        return "pct"
    return "eur"


def compute_promo_amount(
    base_price: Optional[float],
    promo_value: Optional[float],
    promo_type: str = "eur",
) -> float:
    """Compute effective discount amount in EUR from base price and promo value/type."""
    if base_price is None or base_price <= 0:
        return 0.0
    if promo_value is None or promo_value <= 0:
        return 0.0
    ptype = normalize_promo_type(promo_type)
    if ptype == "pct":
        pct = min(float(promo_value), 100.0)
        return round(float(base_price) * pct / 100.0, 2)
    return round(float(promo_value), 2)


def compute_total_price(
    base_price: Optional[float],
    shipping_fee: float = 0.0,
    site_fee: float = 0.0,
    customs_fee: float = 0.0,
    promo_value: Optional[float] = None,
    promo_type: str = "eur",
) -> Optional[float]:
    """Compute total price (EUR) including fees and subtracting any promotion."""
    if base_price is None or base_price <= 0:
        return None
    promo_amount = compute_promo_amount(base_price, promo_value, promo_type)
    total = float(base_price) - promo_amount + float(shipping_fee or 0.0) + float(site_fee or 0.0) + float(customs_fee or 0.0)
    return round(max(0.0, total), 2)


@dataclass
class WatchURL:
    url: str
    merchant: str = ""
    condition: str = "new"  # "new" (Neuf) or "used" (Occasion)
    shipping_fee: Optional[float] = None  # Frais de port (€) - None = auto-detect if stated on site
    site_fee: Optional[float] = None      # Frais du site / protection acheteur (€)
    customs_fee: Optional[float] = None   # Frais de douane & TVA import (€)
    has_customs: Optional[bool] = None    # True = appliquer le calcul douane/TVA, False = 0 € (UE), None = auto
    manual_price: Optional[float] = None  # Prix affiché saisi ou mis en cache (€)
    promo_value: Optional[float] = None   # Valeur de la promotion (€ ou %)
    promo_type: str = "eur"               # "eur" (€) or "pct" (%)
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
    price: Optional[float]                     # Prix TOTAL tout compris (base - promo + port + site + douane)
    base_price: Optional[float] = None         # Prix affiché hors frais additionnels
    condition: str = "new"                     # "new" | "used"
    shipping_fee: float = 0.0
    site_fee: float = 0.0
    customs_fee: float = 0.0
    has_customs: bool = False
    promo_value: float = 0.0
    promo_type: str = "eur"                    # "eur" | "pct"
    promo_amount: float = 0.0
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
