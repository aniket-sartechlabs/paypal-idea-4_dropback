from difflib import SequenceMatcher
from typing import Any

import re

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


OUT_OF_STOCK = {"outofstock", "soldout", "discontinued", "unavailable", "false"}


def _in_stock(value: Any) -> bool:
    """Channel3 reports schema.org-style values (InStock, OutOfStock, ...)."""
    return re.sub(r"[^a-z]", "", str(value).lower()) not in OUT_OF_STOCK


def _is_new(condition: Any) -> bool:
    """Refund evidence needs an offer explicitly listed as new; a missing condition is not enough."""
    return str(condition or "").strip().lower() == "new"


def _domain(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"^https?://", "", value).split("/")[0]
    return value[4:] if value.startswith("www.") else value


def parse_retailers(text: str) -> list[str]:
    """'bestbuy.com, www.Target.com' -> ['bestbuy.com', 'target.com']"""
    return sorted({_domain(part) for part in re.split(r"[,\s]+", text or "") if _domain(part)})


def retailer_allowed(merchant: str, allowed: list[str]) -> bool:
    domain = _domain(merchant)
    return any(domain == entry or domain.endswith("." + entry) for entry in allowed)


def _normalized(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else " " for char in value).strip()


_DISTINGUISHING_TOKENS = {
    "air", "basic", "black", "blue", "classic", "express", "green", "large", "lite", "max",
    "medium", "mini", "plus", "pro", "red", "rose", "se", "silver", "small", "standard", "ultra",
    "white", "wireless", "wired", "xl", "xs",
}


_MODEL_DISTINGUISHING_TOKENS = {
    "air", "basic", "classic", "express", "lite", "max",
    "mini", "plus", "pro", "se", "ultra", "standard",
}


def _match_score(product_name: str, sku: str, result: dict) -> float:
    title = _title(result)
    if not title:
        return 0.0
    result_sku = str(result.get("sku") or "").strip()
    if result_sku and sku.strip().lower() == result_sku.lower():
        return 1.0

    norm_name = _normalized(product_name)
    norm_title = _normalized(title)
    if norm_name == norm_title:
        return 1.0

    wanted_tokens = set(norm_name.split())
    candidate_tokens = set(norm_title.split())
    if not wanted_tokens or not candidate_tokens:
        return 0.0

    # Reject if distinguishing model variant tokens conflict (e.g., Pro vs Express, Plus vs Mini)
    wanted_model_vars = {token for token in wanted_tokens if token in _MODEL_DISTINGUISHING_TOKENS}
    candidate_model_vars = {token for token in candidate_tokens if token in _MODEL_DISTINGUISHING_TOKENS}
    if wanted_model_vars and candidate_model_vars and wanted_model_vars != candidate_model_vars:
        return 0.0

    # Reject if explicit different model numbers exist (e.g., XM4 vs XM5)
    digit_wanted = {token for token in wanted_tokens if any(char.isdigit() for char in token)}
    digit_candidate = {token for token in candidate_tokens if any(char.isdigit() for char in token)}
    if digit_wanted and digit_candidate and not (digit_wanted & digit_candidate):
        return 0.0

    overlap = len(wanted_tokens & candidate_tokens)
    coverage = overlap / len(wanted_tokens)
    sequence_score = SequenceMatcher(None, norm_name, norm_title).ratio()
    return round(0.7 * sequence_score + 0.3 * coverage, 3)


class Channel3Client:
    """Server-side Channel3 search adapter. No API key is ever sent to the browser."""

    base_url = "https://api.trychannel3.com"
    min_match_confidence = 0.75

    def __init__(self) -> None:
        self._websites: dict[str, dict | None] = {}

    def matches_product(self, product_name: str, sku: str, candidate: str) -> bool:
        return _match_score(product_name, sku, {"title": candidate}) >= self.min_match_confidence

    async def search_products(self, query: str, limit: int = 6, currency: str = "USD") -> list[dict]:
        key = get_settings().channel3_api_key
        if not key:
            raise Channel3Error("Channel3 is required. Add CHANNEL3_API_KEY to .env.", 503)
        headers = {"x-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
        body = {"query": query, "limit": limit, "config": {"country": "US", "currency": currency}}
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.post(f"{self.base_url}/v1/search", headers=headers, json=body)
            except httpx.HTTPError as exc:
                raise Channel3Error("Channel3 could not be reached.") from exc
        if response.is_error:
            raise Channel3Error(f"Channel3 search failed ({response.status_code}).", 502)
        payload = response.json()
        raw_items = payload.get("products") or payload.get("data") or payload.get("items") or []
        items = []
        for p in raw_items:
            offers = p.get("offers") or []
            valid_offers = []
            for o in offers:
                amt = _offer_price(o)
                if amt:
                    valid_offers.append({
                        "price": round(amt, 2),
                        "merchant": str(o.get("domain") or o.get("merchant") or "Retailer")[:100],
                        "url": o.get("url"),
                        "available": _in_stock(o.get("availability")),
                        "condition": str(o.get("condition") or "unknown"),
                    })
            best = min(valid_offers, key=lambda x: x["price"]) if valid_offers else None
            items.append({
                "id": p.get("id"),
                "title": _title(p),
                "description": p.get("description", ""),
                "category": p.get("category", "General"),
                "image_url": p.get("image_url") or p.get("image"),
                "best_offer": best,
                "all_offers": valid_offers,
            })
        return items

    async def search_and_compare(self, product_name: str, sku: str, local_price: float, currency: str,
                                 allowed_retailers: list[str] | None = None) -> dict:
        key = get_settings().channel3_api_key
        if not key:
            raise Channel3Error("Channel3 is required for live price checks. Add CHANNEL3_API_KEY to the server .env file.", 503)
        headers = {"x-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
        body = {"query": f"{product_name} {sku}", "limit": 8, "config": {"country": "US", "currency": currency},
                # Channel3 does the filtering: new, in-stock offers, and only the merchant's approved retailers.
                "filters": {"conditions": ["new"], "availability": ["InStock"], **({"website_ids": allowed_retailers} if allowed_retailers else {})}}
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
                        # Extract weight/dimensions if present
                        weight_info = (offer.get("dimensions") or {}).get("weight") if isinstance(offer.get("dimensions"), dict) else None
                        priced.append({
                            "price": round(amount, 2),
                            "merchant": str(offer.get("domain") or offer.get("merchant") or offer.get("seller") or "Retailer")[:100],
                            "url": offer.get("url"),
                            "available": _in_stock(offer.get("availability")),
                            "condition": str(offer.get("condition") or "unknown"),
                            "weight": weight_info,
                        })
            if priced:
                candidates.append((ratio, result, title, priced))
        candidates.sort(key=lambda item: item[0], reverse=True)
        if (not candidates or candidates[0][0] < self.min_match_confidence) and allowed_retailers:
            return {"matched": False, "results_count": len(results), "retailer_filtered": True,
                    "message": "No in-stock new offer for this exact model from a retailer this store price-matches: " + ", ".join(allowed_retailers) + "."}
        if not candidates or candidates[0][0] < self.min_match_confidence:
            return {"matched": False, "results_count": len(results), "message": "Channel3 could not confirm an exact model match. Use the Channel3 product title or matching SKU."}

        match_score, matched, title, offers = candidates[0]
        new_offers = [offer for offer in offers if offer["available"] and _is_new(offer["condition"])]
        if not new_offers:
            raise Channel3Error("Channel3 matched the product but returned no current in-stock new offers.", 404)
        if allowed_retailers:
            new_offers = [offer for offer in new_offers if retailer_allowed(offer["merchant"], allowed_retailers)]
            if not new_offers:
                return {"matched": False, "results_count": len(results), "retailer_filtered": True,
                        "message": "No in-stock new offer from a retailer this store price-matches: " + ", ".join(allowed_retailers) + "."}
        best = min(new_offers, key=lambda offer: offer["price"])
        matched_id = matched.get("id")
        return {
            "matched": True,
            "product_id": str(matched_id) if matched_id else None,
            "title": title,
            "image_url": matched.get("image_url") or matched.get("image"),
            "match_confidence": round(match_score, 3),
            "offer_count": len(new_offers),
            "best_offer": best,
            "all_offers": new_offers[:5],
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
            if amount and str(offer_currency).upper() == currency.upper() and _in_stock(offer.get("availability")):
                valid.append({
                    "price": round(amount, 2),
                    "merchant": str(offer.get("domain") or offer.get("merchant") or "Retailer")[:100],
                    "url": offer.get("url"),
                    "condition": str(offer.get("condition") or "unknown"),
                })
        if not valid:
            raise Channel3Error("Channel3 matched the product but returned no live offers.", 404)
        return {"id": product.get("id"), "title": _title(product), "image_url": product.get("image_url") or product.get("image"), "best_offer": min(valid, key=lambda item: item["price"]), "offer_count": len(valid)}

    # -- market evidence: price history (Price Tracking API) and retailer details (Websites API) ------------
    def _headers(self) -> dict:
        key = get_settings().channel3_api_key
        if not key:
            raise Channel3Error("Channel3 is required. Add CHANNEL3_API_KEY to .env.", 503)
        return {"x-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}

    async def price_history(self, product_id: str, days: int = 90) -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.get(f"{self.base_url}/v0/price-tracking/history/{product_id}", params={"days": days}, headers=self._headers())
            except httpx.HTTPError as exc:
                raise Channel3Error("Channel3 price history could not be reached.") from exc
        if response.is_error:
            raise Channel3Error(f"Channel3 price history failed ({response.status_code}).", 502)
        payload = response.json()
        points = [{"date": str(p.get("timestamp", ""))[:10], "price": round(float(p["price"]), 2)}
                  for p in payload.get("history") or [] if isinstance(p, dict) and p.get("price") is not None]
        stats = payload.get("statistics") or {}
        return {"points": points[-90:], "statistics": {k: stats.get(k) for k in ("min_price", "max_price", "mean", "current_price", "current_status")} if stats else None}

    async def website(self, domain: str) -> dict | None:
        domain = _domain(domain)
        if not domain:
            return None
        if domain in self._websites:
            return self._websites[domain]
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response = await client.get(f"{self.base_url}/v1/websites/{domain}", params={"country": "US"}, headers=self._headers())
            except httpx.HTTPError:
                return None
        info = None
        if response.status_code == 200:
            data = response.json()
            info = {"domain": domain, "name": data.get("name") or domain, "logo_url": data.get("logo_url"), "website_id": data.get("id")}
        self._websites[domain] = info
        return info

    async def market_context(self, product_id: str | None, retailer: str | None) -> dict:
        """Evidence for a claim: 90-day price history for the exact product, and who the retailer is."""
        context: dict = {"product_id": product_id, "history": None, "retailer": None}
        if product_id:
            try:
                context["history"] = await self.price_history(product_id)
            except Channel3Error:
                pass
        if retailer:
            context["retailer"] = await self.website(retailer)
        return context

    async def lookup(self, url: str, currency: str = "USD") -> dict:
        """Resolve any product page URL to the exact Channel3 product (Lookup API)."""
        async with httpx.AsyncClient(timeout=45) as client:
            try:
                response = await client.post(f"{self.base_url}/v1/lookup", headers=self._headers(),
                                             json={"url": url, "realtime_fetch": True})
            except httpx.HTTPError as exc:
                raise Channel3Error("Channel3 lookup could not be reached.") from exc
        if response.status_code in (404, 422):
            raise Channel3Error("Channel3 could not identify a product at that URL.", 404)
        if response.is_error:
            raise Channel3Error(f"Channel3 lookup failed ({response.status_code}).", 502)
        product = response.json().get("product") or {}
        offers = []
        for offer in product.get("offers") or []:
            amount = _offer_price(offer) if isinstance(offer, dict) else None
            if amount and _in_stock(offer.get("availability")) and _is_new(offer.get("condition")):
                offers.append({"price": round(amount, 2), "merchant": str(offer.get("domain") or "Retailer")[:100], "url": offer.get("url")})
        images = product.get("images") or []
        first_image = images[0] if images else None
        image_url = first_image.get("url") if isinstance(first_image, dict) else first_image
        brands = product.get("brands") or []
        brand = brands[0].get("name") if brands and isinstance(brands[0], dict) else (brands[0] if brands else None)
        category = product.get("category") or {}
        return {"id": product.get("id"), "title": _title(product), "description": (product.get("description") or "")[:500],
                "brand": brand, "image_url": image_url, "category": category.get("title") if isinstance(category, dict) else None,
                "best_offer": min(offers, key=lambda o: o["price"]) if offers else None, "all_offers": offers}

    async def start_tracking(self, product_id: str) -> bool:
        """Keep Channel3 price history building for a protected product (Price Tracking API)."""
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response = await client.post(f"{self.base_url}/v0/price-tracking/start", headers=self._headers(),
                                             json={"canonical_product_id": product_id})
            except httpx.HTTPError:
                return False
        return response.status_code < 300


channel3 = Channel3Client()
