import json

import httpx

from app.config import get_settings


def deterministic_score(category: str, drop_percentage: float, days_since_purchase: int) -> tuple[float, str]:
    risk = 0.14 + min(drop_percentage, 35) * 0.009
    category_name = category.lower()
    if any(term in category_name for term in ("electronic", "appliance", "camera", "computer")):
        risk += 0.2
    elif any(term in category_name for term in ("fashion", "shoe", "apparel")):
        risk += 0.16
    else:
        risk += 0.08
    if days_since_purchase <= 3:
        risk += 0.15
    elif days_since_purchase <= 7:
        risk += 0.08
    return max(0.05, min(0.9, risk)), "Rule-based estimate using price-drop size, product category, and time since purchase."


async def explain_decision(category: str, drop_percentage: float, days_since_purchase: int, probability: float, savings: float) -> tuple[float, str, str]:
    settings = get_settings()
    provider = settings.llm_provider.lower()
    api_key = settings.openai_api_key if provider in {"openai", "auto"} else settings.gemini_api_key
    active_provider = "openai" if api_key and provider in {"openai", "auto"} else "gemini" if settings.gemini_api_key and provider == "gemini" else "rules"
    if active_provider == "rules":
        return probability, f"{deterministic_score(category, drop_percentage, days_since_purchase)[1]} Estimated net savings are ${savings:.2f} if this refund replaces a return.", "rules"

    if active_provider == "openai":
        url = "https://api.openai.com/v1/responses"
        model = settings.openai_model
        prompt = (
            "Assess return likelihood for a merchant price-protection offer. Return only JSON with keys "
            "return_probability (number 0..1) and reasoning (string under 220 chars). Do not recommend or execute payment. "
            f"Category={category}; price drop={drop_percentage:.1f}%; days since purchase={days_since_purchase}; "
            f"estimated savings=${savings:.2f}; rule-based prior={probability:.2f}."
        )
        body = {"model": model, "input": prompt, "max_output_tokens": 160}
    else:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        model = "gemini-2.0-flash"
        prompt = (
            "Return JSON only: {\"return_probability\": number between 0 and 1, \"reasoning\": string under 220 chars}. "
            "Estimate return probability; never recommend or execute payment. "
            f"Category={category}; drop={drop_percentage:.1f}%; days={days_since_purchase}; savings=${savings:.2f}; prior={probability:.2f}."
        )
        url += f"?key={settings.gemini_api_key}"
        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 160}}
        api_key = ""
    headers = {"Content-Type": "application/json"}
    if active_provider == "openai":
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(url, headers=headers, json=body)
        if response.is_error:
            raise ValueError("LLM request failed")
        data = response.json()
        text = data.get("output_text")
        if not text and active_provider == "gemini":
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        if not text:
            raise ValueError("No model output")
        result = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
        model_probability = max(0.0, min(1.0, float(result["return_probability"])))
        # Blend the model estimate with a deterministic prior; the agent never decides beyond the fixed policy.
        score = round((model_probability * 0.4) + (probability * 0.6), 4)
        reason = str(result.get("reasoning", "Model-assisted return likelihood estimate."))[:220]
        return score, reason, active_provider
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        return probability, f"{deterministic_score(category, drop_percentage, days_since_purchase)[1]} Model scoring was unavailable; using the rule-based estimate. Estimated net savings: ${savings:.2f}.", "rules"
