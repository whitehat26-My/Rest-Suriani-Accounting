"""Turning spoken sentences into a transaction the owner can confirm.

The browser does the speech-to-text (the Web Speech API); this module handles
the harder half - working out what the sentence *means*. It is a deterministic
rule-based parser rather than a language model, which matters here for three
reasons: it runs instantly on a cheap device, it costs nothing per use, and it
behaves identically every time, so the owner learns to trust it.

It understands English and Malay mixed freely, which is how the phrase is
actually spoken in a Malaysian kitchen:

    "Bought RM50 of chicken"      -> money out, RM50.00, ingredients, chicken
    "Beli ayam 2 kg RM35"          -> money out, RM35.00, ingredients, 2kg chicken
    "Jual RM120 tunai"             -> money in,  RM120.00, cash
    "Bayar gaji pekerja RM800"     -> money out, RM800.00, wages

Nothing is ever posted straight from a parse. The parsed result is read back to
the owner as a confirmation sentence, and only a tap on the big green button
writes it to the ledger.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..chart_of_accounts import SPENDING_CATEGORIES
from ..models import InventoryItem, PaymentMethod
from ..schemas import VoiceParseResponse

CATEGORY_LABELS = {slug: label for slug, label, _, _ in SPENDING_CATEGORIES}

# Words that put money into the business.
INCOME_WORDS = {
    "sold", "sell", "sale", "sales", "selling", "received", "receive", "took in",
    "income", "revenue", "earned", "collection", "collected", "customer paid",
    "jual", "jualan", "terima", "dapat", "masuk", "hasil", "kutipan", "untung",
}
# Words that take money out.
EXPENSE_WORDS = {
    "bought", "buy", "buying", "purchase", "purchased", "paid", "pay", "paying",
    "spent", "spend", "cost", "bill", "expense", "order", "ordered", "topped up",
    "beli", "belian", "bayar", "belanja", "keluar", "kos", "hantar duit", "upah",
}

# Category keyword map. Order matters: the first list to match with the highest
# score wins, and more specific phrases are checked before generic ones.
CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (
        "transport",
        ("petrol", "diesel", "fuel", "toll", "tol", "parking", "delivery", "courier",
         "grab", "penghantaran", "transport", "pengangkutan", "van", "lorry", "lori"),
    ),
    (
        "wages",
        ("worker", "workers", "staff", "salary", "salaries", "wage", "wages", "helper",
         "employee", "pekerja", "gaji", "upah", "pembantu", "kakitangan", "bonus"),
    ),
    ("rent", ("rent", "rental", "landlord", "sewa", "penyewa", "kedai sewa")),
    (
        "gas",
        ("gas", "lpg", "cooking gas", "gas masak", "petronas gas", "tong gas", "cylinder"),
    ),
    (
        "utilities",
        ("electric", "electricity", "current", "tnb", "tenaga", "letrik", "elektrik",
         "water bill", "syabas", "air bill", "utility", "utilities", "internet",
         "wifi", "phone bill", "bil"),
    ),
    (
        "supplies",
        ("packaging", "plastic", "container", "bekas", "napkin", "tissue", "soap",
         "sabun", "glove", "gloves", "sarung tangan", "straw", "penyedut", "cup",
         "cawan", "bag", "beg", "detergent", "cleaning", "pembersih", "supplies"),
    ),
    (
        "repairs",
        ("repair", "repairs", "fix", "fixed", "service", "servicing", "maintenance",
         "baiki", "membaiki", "rosak", "ganti", "spare part", "plumber", "electrician"),
    ),
    (
        "marketing",
        ("advertise", "advertising", "advert", "ads", "iklan", "promotion", "promosi",
         "banner", "flyer", "facebook", "instagram", "tiktok", "boost", "marketing"),
    ),
    (
        "licenses",
        ("licence", "license", "permit", "lesen", "council", "majlis", "dbkl", "mbpj",
         "halal cert", "sijil", "renewal", "pembaharuan"),
    ),
    (
        "ingredients",
        ("chicken", "ayam", "beef", "daging", "mutton", "kambing", "fish", "ikan",
         "prawn", "udang", "squid", "sotong", "egg", "eggs", "telur", "vegetable",
         "vegetables", "sayur", "sayuran", "rice", "beras", "nasi", "noodle", "mee",
         "mi", "kuey teow", "flour", "tepung", "sugar", "gula", "salt", "garam",
         "oil", "minyak", "onion", "bawang", "garlic", "chilli", "cili", "milk",
         "susu", "coffee", "kopi", "tea", "teh", "spice", "rempah", "coconut",
         "kelapa", "santan", "ingredient", "ingredients", "groceries", "grocery",
         "market", "pasar", "supplier", "pembekal", "stock", "stok", "bahan",
         "food", "makanan", "drink", "minuman", "tomato", "potato", "kentang",
         "cheese", "keju", "bread", "roti", "butter", "mentega", "sauce", "sos"),
    ),
]

PAYMENT_KEYWORDS: list[tuple[PaymentMethod, tuple[str, ...]]] = [
    (PaymentMethod.CREDIT, ("on credit", "later", "hutang", "berhutang", "owe", "owing",
                            "belum bayar", "not paid", "pay later", "bayar kemudian")),
    (PaymentMethod.EWALLET, ("e-wallet", "ewallet", "touch n go", "touch and go", "tng",
                             "grabpay", "boost", "shopeepay", "duitnow", "qr", "scan")),
    (PaymentMethod.CARD, ("card", "credit card", "debit card", "kad", "visa",
                          "mastercard", "swipe", "terminal")),
    (PaymentMethod.BANK, ("bank", "transfer", "online banking", "maybank", "cimb",
                          "pindahan", "banking", "deposit")),
    (PaymentMethod.CASH, ("cash", "tunai", "duit", "note", "coin", "syiling")),
]

UNIT_WORDS = (
    "kg", "kilo", "kilos", "kilogram", "kilograms", "g", "gram", "grams",
    "l", "litre", "litres", "liter", "liters", "ml",
    "pcs", "pc", "piece", "pieces", "biji", "ekor", "ketul",
    "packet", "packets", "pack", "bungkus", "box", "boxes", "kotak",
    "carton", "cartons", "tray", "trays", "dozen", "botol", "bottle", "bottles",
    "tin", "tins", "can", "cans", "bag", "bags", "guni",
)

# RM50 / RM 50.20 / 50 ringgit / 50.50 / rm50k is not supported on purpose.
_AMOUNT_PATTERNS = (
    re.compile(r"rm\s*([0-9]{1,12}(?:[.,][0-9]{1,2})?)", re.IGNORECASE),
    re.compile(r"([0-9]{1,12}(?:[.,][0-9]{1,2})?)\s*(?:ringgit|rm)\b", re.IGNORECASE),
)
_BARE_NUMBER = re.compile(r"\b([0-9]{1,12}(?:\.[0-9]{1,2})?)\b")
_QUANTITY_PATTERN = re.compile(
    r"\b([0-9]+(?:\.[0-9]+)?)\s*(" + "|".join(sorted(UNIT_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _extract_amount(text: str) -> tuple[Decimal | None, str]:
    """Pull the money value out. Explicit RM markers win over bare numbers."""
    for pattern in _AMOUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            raw = match.group(1).replace(",", ".")
            try:
                return Decimal(raw).quantize(Decimal("0.01")), match.group(0)
            except InvalidOperation:  # pragma: no cover - regex already constrains this
                continue

    # No currency marker. Fall back to the largest bare number that is not
    # attached to a unit, so "2 kg chicken 35" reads 35 as the price.
    quantities = {m.group(1) for m in _QUANTITY_PATTERN.finditer(text)}
    candidates = [
        Decimal(m.group(1))
        for m in _BARE_NUMBER.finditer(text)
        if m.group(1) not in quantities
    ]
    if candidates:
        try:
            best = max(candidates)
            return best.quantize(Decimal("0.01")), str(best)
        except InvalidOperation:  # pragma: no cover - digit cap already guards this
            return None, ""
    return None, ""


def _extract_quantity(text: str) -> tuple[Decimal | None, str]:
    match = _QUANTITY_PATTERN.search(text)
    if not match:
        return None, ""
    try:
        return Decimal(match.group(1)), match.group(2).lower()
    except InvalidOperation:  # pragma: no cover
        return None, ""


def _score_words(text: str, words: set[str]) -> int:
    return sum(1 for word in words if word in text)


def _detect_direction(text: str) -> tuple[str | None, float]:
    income = _score_words(text, INCOME_WORDS)
    expense = _score_words(text, EXPENSE_WORDS)
    if income == expense == 0:
        return None, 0.0
    if income > expense:
        return "in", min(0.5 + 0.15 * income, 0.9)
    if expense > income:
        return "out", min(0.5 + 0.15 * expense, 0.9)
    # A tie usually means a phrase like "paid for the sale"; treat as expense,
    # which is the safer default because it does not inflate reported income.
    return "out", 0.4


def _detect_category(text: str) -> tuple[str | None, float]:
    best_slug: str | None = None
    best_hits = 0
    for slug, keywords in CATEGORY_KEYWORDS:
        hits = sum(1 for keyword in keywords if keyword in text)
        if hits > best_hits:
            best_slug, best_hits = slug, hits
    if best_slug is None:
        return None, 0.0
    return best_slug, min(0.4 + 0.2 * best_hits, 0.9)


def _detect_method(text: str) -> tuple[PaymentMethod, float]:
    for method, keywords in PAYMENT_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return method, 0.8
    return PaymentMethod.CASH, 0.4


def _match_inventory_item(db: Session, text: str) -> InventoryItem | None:
    """Find the stock item the sentence is about, longest name first.

    Matching the longest name first stops "chicken" from winning over
    "chicken wings" when both are stocked.
    """
    items = db.scalars(select(InventoryItem).where(InventoryItem.is_active.is_(True))).all()
    matches: list[tuple[int, InventoryItem]] = []
    for item in items:
        for candidate in (item.name, item.local_name):
            if candidate and candidate.lower() in text:
                matches.append((len(candidate), item))
                break
    if not matches:
        return None
    return max(matches, key=lambda pair: pair[0])[1]


def parse(db: Session, text: str) -> VoiceParseResponse:
    """Parse a spoken or typed sentence into a proposed quick entry."""
    original = text.strip()
    normalised = _normalise(text)

    amount, _ = _extract_amount(normalised)
    direction, direction_confidence = _detect_direction(normalised)
    category, category_confidence = _detect_category(normalised)
    method, method_confidence = _detect_method(normalised)
    qty, unit = _extract_quantity(normalised)
    item = _match_inventory_item(db, normalised)

    # Naming a stocked ingredient is itself strong evidence of a food purchase.
    if item is not None and category is None:
        category = "ingredients"
        category_confidence = 0.75

    # Money coming in needs no category, so do not penalise its absence.
    if direction == "in":
        category, category_confidence = None, 1.0

    # An amount is the one thing we cannot guess.
    if amount is None:
        return VoiceParseResponse(
            understood=False,
            confidence=0.0,
            note=original,
            original_text=original,
            confirmation="I did not catch the amount. Please say it like "
            "\"Bought RM50 of chicken\".",
        )

    if direction is None:
        # An amount with an ingredient but no verb is almost always a purchase.
        direction = "out" if category else "in"
        direction_confidence = 0.35

    confidence = round(
        0.45 * direction_confidence
        + 0.30 * category_confidence
        + 0.15 * method_confidence
        + 0.10,
        2,
    )

    confirmation = _build_confirmation(
        direction=direction,
        amount=amount,
        category=category,
        method=method,
        item_name=item.name if item else None,
        qty=qty,
        unit=unit,
    )

    return VoiceParseResponse(
        understood=True,
        confidence=min(confidence, 0.99),
        kind=direction,
        amount=amount,
        category=category,
        category_label=CATEGORY_LABELS.get(category) if category else None,
        method=method,
        inventory_item_id=item.id if item else None,
        inventory_item_name=item.name if item else None,
        inventory_item_unit=item.unit if item else None,
        quantity=qty,
        note=original,
        confirmation=confirmation,
        original_text=original,
    )


def _build_confirmation(
    *,
    direction: str,
    amount: Decimal,
    category: str | None,
    method: PaymentMethod,
    item_name: str | None,
    qty: Decimal | None,
    unit: str,
) -> str:
    """Write the sentence read back to the owner before anything is saved."""
    money_text = f"RM{amount:,.2f}"
    how = {
        PaymentMethod.CASH: "in cash",
        PaymentMethod.BANK: "by bank transfer",
        PaymentMethod.CARD: "by card",
        PaymentMethod.EWALLET: "by e-wallet",
        PaymentMethod.CREDIT: "on credit, to pay later",
    }[method]

    if direction == "in":
        return f"Money IN: {money_text} received {how}. Is that right?"

    what = CATEGORY_LABELS.get(category or "other", "Something Else").lower()
    detail = f" for {what}"
    if item_name:
        quantity_text = f"{qty:g} {unit} of " if qty and unit else ""
        detail = f" for {quantity_text}{item_name.lower()}"
    return f"Money OUT: {money_text} paid{detail} {how}. Is that right?"
