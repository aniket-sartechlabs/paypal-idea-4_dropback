from difflib import SequenceMatcher
from typing import Any

import httpx

from app.config import get_settings


class Channel3Error(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _price(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("price", value.get("amount", value.get("value")))
    try:
        result = float(value)
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


def _offer_price(offer: dict) -> float | None:
    for key in ("price", "current_price", "amount"):
        if key in offer:
            result = _price(offer[key])
            if result is not None:
                return result
    return None


def _title(product: dict) -> str:
    return str(product.get("title") or product.get("name") or "").strip()


def _normalized(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else " " for char in value).strip()


_DISTINGUISHING_TOKENS = {
    "air", "basic", "black", "blue", "classic", "express", "green", "large", "lite", "max",
    "medium", "mini", "plus", "pro", "red", "rose", "se", "silver", "small", "standard", "ultra",
    "white", "wireless", "wired", "xl", "xs",
}


def _match_score(product_name: str, sku: str, result: dict) -> float:
    title = _title(result)
    if not title:
        return 0.0
    result_sku = str(result.get("sku") or "").strip()
    if result_sku and sku.strip().lower() == result_sku.lower():
        return 1.0

    wanted_tokens = set(_normalized(product_name).split())
    candidate_tokens = set(_normalized(title).split())
    if not wanted_tokens or not candidate_tokens:
        return 0.0
    wanted_variants = {token for token in wanted_tokens if token in _DISTINGUISHING_TOKENS or any(char.isdigit() for char in token)}
    candidate_variants = {token for token in candidate_tokens if token in _DISTINGUISHING_TOKENS or any(char.isdigit() for char in token)}
    # A title similarity score can hide a different model, color, size, or generation.
    if wanted_variants != candidate_variants:
        return 0.0
    coverage = len(wanted_tokens & candidate_tokens) / len(wanted_tokens)
    if coverage < 0.75:
        return 0.0
    sequence_score = SequenceMatcher(None, _normalized(product_name), _normalized(title)).ratio()
    return round(0.7 * sequence_score + 0.3 * coverage, 3)


class Channel3Client:
    """Server-side Channel3 search adapter. No API key is ever sent to the browser."""

    base_url = "https://api.trychannel3.com"
    min_match_confidence = 0.95

    def matches_product(self, product_name: str, sku: str, candidate: str) -> bool:
        return _match_score(product_name, sku, {"title": candidate}) >= self.min_match_confidence

    async def search_and_compare(self, product_name: str, sku: str, local_price: float, currency: str) -> dict:
        key = get_settings().channel3_api_key
        if not key:
            raise Channel3Error("Channel3 is required for live price checks. Add CHANNEL3_API_KEY to the server .env file.", 503)
        headers = {"x-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
        body = {"query": f"{product_name} {sku}", "limit": 8, "config": {"country": "US", "currency": currency}}
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.post(f"{self.base_url}/v1/search", headers=headers, json=body)
            except httpx.HTTPError as exc:
                raise Channel3Error("Channel3 could not be reached. Try the live price check again.") from exc
        if response.status_code == 401 or response.status_code == 403:
            raise Channel3Error("Channel3 rejected the API key. Check CHANNEL3_API_KEY in the server environment.", 502)
        if response.is_error:
            raise Channel3Error(f"Channel3 price search failed ({response.status_code}).", 502)
        payload = response.json()
        results = payload.get("data", payload.get("items", payload.get("products", [])))
        if isinstance(results, dict):
            results = results.get("data", results.get("items", []))
        if not isinstance(results, list):
            results = []

        candidates = []
        for result in results:
            if not isinstance(result, dict):
                continue
            title = _title(result)
            ratio = _match_score(product_name, sku, result)
            offers = result.get("offers") or []
            priced = []
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                amount = _offer_price(offer)
                if amount is not None:
                    offer_currency = (offer.get("currency") or (offer.get("price") or {}).get("currency") if isinstance(offer.get("price"), dict) else offer.get("currency") or currency).upper()
                    if offer_currency == currency.upper():
                        priced.append({
                            "price": round(amount, 2),
                            "merchant": str(offer.get("domain") or offer.get("merchant") or offer.get("seller") or "Retailer")[:100],
                            "available": offer.get("availability") not in {"out_of_stock", "unavailable", False},
                            "condition": str(offer.get("condition") or "new"),
                        })
            if priced:
                candidates.append((ratio, result, title, priced))
        candidates.sort(key=lambda item: item[0], reverse=True)
        if not candidates or candidates[0][0] < self.min_match_confidence:
            return {"matched": False, "results_count": len(results), "message": "Channel3 could not confirm an exact model match. Use the Channel3 product title or matching SKU."}

        match_score, matched, title, offers = candidates[0]
        new_offers = [offer for offer in offers if offer["available"] and offer["condition"].lower() not in {"used", "refurbished", "pre-owned"}]
        if not new_offers:
            raise Channel3Error("Channel3 matched the product but returned no current in-stock new offers.", 404)
        best = min(new_offers, key=lambda offer: offer["price"])
        matched_id = matched.get("id")
        return {
            "matched": True,
            "product_id": str(matched_id) if matched_id else None,
            "title": title,
            "match_confidence": round(match_score, 3),
            "offer_count": len(new_offers),
            "best_offer": best,
            "local_price": round(local_price, 2),
            "currency": currency.upper(),
            "lower_than_current": best["price"] < local_price,
        }

    async def subscribe(self, product_id: str, merchant_domain: str | None = None) -> str | None:
        key = get_settings().channel3_api_key
        if not key:
            return None
        body: dict = {"product_id": product_id, "events": ["offer.price.changed", "offer.availability.changed"]}
        if merchant_domain:
            body["domains"] = [merchant_domain]
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/v1/product-subscriptions",
                    headers={"x-api-key": key, "Content-Type": "application/json", "Accept": "application/json"},
                    json=body,
                )
            except httpx.HTTPError as exc:
                raise Channel3Error("Channel3 subscription setup could not be reached.") from exc
        if response.is_error:
            raise Channel3Error(f"Channel3 subscription setup failed ({response.status_code}).", 502)
        payload = response.json()
        subscription = payload.get("subscription", payload)
        if not isinstance(subscription, dict):
            return None
        subscription_id = subscription.get("subscription_id") or subscription.get("id")
        return str(subscription_id) if subscription_id else None

    async def unsubscribe(self, subscription_id: str) -> None:
        key = get_settings().channel3_api_key
        if not key:
            raise Channel3Error("Channel3 is required to manage product subscriptions.", 503)
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response = await client.delete(
                    f"{self.base_url}/v1/product-subscriptions/{subscription_id}",
                    headers={"x-api-key": key, "Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise Channel3Error("Channel3 subscription cleanup could not be reached.") from exc
        if response.is_error and response.status_code != 404:
            raise Channel3Error(f"Channel3 subscription cleanup failed ({response.status_code}).", 502)

    async def current_offer(self, product_id: str, currency: str = "USD") -> dict:
        key = get_settings().channel3_api_key
        if not key:
            raise Channel3Error("Channel3 is required for live price monitoring.", 503)
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/v1/products/{product_id}",
                    params={"country": "US", "currency": currency},
                    headers={"x-api-key": key, "Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise Channel3Error("Channel3 product refresh could not be reached.") from exc
        if response.is_error:
            raise Channel3Error(f"Channel3 product refresh failed ({response.status_code}).", 502)
        payload = response.json()
        product = payload.get("product", payload)
        offers = product.get("offers", []) if isinstance(product, dict) else []
        valid = []
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            amount = _offer_price(offer)
            offer_currency = offer.get("currency") or (offer.get("price", {}).get("currency") if isinstance(offer.get("price"), dict) else None) or currency
            if amount and str(offer_currency).upper() == currency.upper() and offer.get("availability") not in {"out_of_stock", "unavailable", False}:
                valid.append({"price": round(amount, 2), "merchant": str(offer.get("domain") or offer.get("merchant") or "Retailer")[:100]})
        if not valid:
            raise Channel3Error("Channel3 matched the product but returned no live offers.", 404)
        return {"title": _title(product), "best_offer": min(valid, key=lambda item: item["price"]), "offer_count": len(valid)}


channel3 = Channel3Client()
