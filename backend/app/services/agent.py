import json
import logging
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger("dropback.agent")


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
    return max(0.05, min(0.9, risk)), "Rule-based actuarial model factoring competitor price delta, category return propensity, and days since purchase."


def build_rule_report(
    category: str,
    drop_percentage: float,
    days_since_purchase: int,
    probability: float,
    savings: float,
    product_name: str = "",
    purchase_price: float = 0.0,
    refund_amount: float = 0.0,
    return_cost: float = 0.0,
) -> dict[str, Any]:
    risk_level = "HIGH" if probability >= 0.55 else "MEDIUM" if probability >= 0.3 else "LOW"
    drivers = [
        f"Elapsed time: Order placed {days_since_purchase} day{'s' if days_since_purchase != 1 else ''} ago (well within active return policy).",
        f"Price difference: {drop_percentage:.1f}% market price drop creates high return-and-repurchase incentive.",
        f"Category dynamics: '{category}' has elevated remorse sensitivity when competitor discounts appear.",
    ]
    if savings > 0:
        drivers.append(f"Financial justification: Proactive ${refund_amount:.2f} refund saves an estimated ${savings:.2f} compared to return logistics.")

    reasoning = (
        f"Rule-based analysis calculated a {probability * 100:.0f}% return likelihood for {product_name or category}. "
        f"A proactive partial refund of ${refund_amount:.2f} avoids full return processing costs of ${return_cost:.2f}, "
        f"protecting ${savings:.2f} in merchant gross margin."
    )

    return {
        "return_probability": round(probability, 3),
        "confidence": "MEDIUM",
        "risk_level": risk_level,
        "key_drivers": drivers,
        "reasoning": reasoning,
        "retention_impact": "Proactively refunding the price delta removes customer dissatisfaction and preserves store loyalty.",
        "recommended_action": "APPROVE_PARTIAL_REFUND" if savings > 0 else "SKIP",
        "provider": "rules",
        "model": "Actuarial Rule Engine v1",
        "financial_breakdown": {
            "purchase_price": round(purchase_price, 2),
            "drop_percentage": round(drop_percentage, 1),
            "days_since_purchase": days_since_purchase,
            "proposed_refund": round(refund_amount, 2),
            "estimated_return_cost": round(return_cost, 2),
            "net_savings": round(savings, 2),
        },
    }


async def explain_decision(
    category: str,
    drop_percentage: float,
    days_since_purchase: int,
    probability: float,
    savings: float,
    product_name: str = "",
    purchase_price: float = 0.0,
    refund_amount: float = 0.0,
    return_cost: float = 0.0,
) -> tuple[float, str, str, dict[str, Any]]:
    settings = get_settings()
    provider = settings.llm_provider.lower()
    api_key = settings.openai_api_key if provider in {"openai", "auto"} else settings.gemini_api_key
    active_provider = "openai" if api_key and provider in {"openai", "auto"} else "gemini" if settings.gemini_api_key and provider == "gemini" else "rules"

    if active_provider == "rules":
        report = build_rule_report(category, drop_percentage, days_since_purchase, probability, savings, product_name, purchase_price, refund_amount, return_cost)
        return probability, report["reasoning"], "rules", report

    system_prompt = (
        "You are DropBack AI, an advanced e-commerce actuarial engine analyzing return likelihood and customer churn risk. "
        "A merchant is evaluating whether to issue a proactive partial refund to a buyer after a market/competitor price drop. "
        "Return ONLY valid JSON matching this schema:\n"
        "{\n"
        '  "return_probability": <float 0.0 to 1.0>,\n'
        '  "confidence": "HIGH" | "MEDIUM" | "LOW",\n'
        '  "risk_level": "HIGH" | "MEDIUM" | "LOW",\n'
        '  "key_drivers": [<3-4 concise string explanations of behavioral/financial drivers>],\n'
        '  "reasoning": "<clear 2-sentence rationale summarizing why this probability was assigned and why a refund helps>",\n'
        '  "retention_impact": "<1-2 sentence statement on customer relationship and lifetime value impact>",\n'
        '  "recommended_action": "APPROVE_PARTIAL_REFUND" | "POLICY_SKIP"\n'
        "}"
    )

    user_prompt = (
        f"Product: {product_name or 'Retail Item'}\n"
        f"Category: {category}\n"
        f"Original Purchase Price: ${purchase_price:.2f}\n"
        f"Competitor Price Drop: {drop_percentage:.1f}%\n"
        f"Days Elapsed Since Purchase: {days_since_purchase} days\n"
        f"Proposed Proactive Refund Amount: ${refund_amount:.2f}\n"
        f"Estimated Full Return Cost (Shipping + Restocking + Open-Box): ${return_cost:.2f}\n"
        f"Projected Merchant Net Savings if Preempted: ${savings:.2f}\n"
        f"Deterministic Actuarial Baseline Probability: {probability:.2f}\n"
    )

    try:
        if active_provider == "openai":
            # Primary: Universal chat/completions endpoint
            url = "https://api.openai.com/v1/chat/completions"
            model = settings.openai_model or "gpt-4.1-mini"
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 400,
                "response_format": {"type": "json_object"},
            }
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, headers=headers, json=body)
                if response.is_error:
                    # Fallback to responses endpoint if chat fails
                    alt_url = "https://api.openai.com/v1/responses"
                    alt_body = {"model": model, "input": f"{system_prompt}\n\n{user_prompt}", "max_output_tokens": 350}
                    response = await client.post(alt_url, headers=headers, json=alt_body)
                    if response.is_error:
                        raise ValueError(f"OpenAI error {response.status_code}: {response.text[:120]}")
            data = response.json()
            # Extract content from chat/completions or responses
            text = None
            if "choices" in data and data["choices"]:
                text = data["choices"][0].get("message", {}).get("content")
            elif "output" in data and data["output"]:
                for item in data["output"]:
                    for c in item.get("content", []):
                        if c.get("text"):
                            text = c.get("text")
                            break
            if not text:
                text = data.get("output_text")
        else:
            # Gemini provider
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.gemini_api_key}"
            model = "gemini-2.0-flash"
            body = {
                "contents": [{"parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]}],
                "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 400},
            }
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, headers={"Content-Type": "application/json"}, json=body)
                if response.is_error:
                    raise ValueError(f"Gemini error {response.status_code}")
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]

        if not text:
            raise ValueError("No text in LLM response payload")

        clean_text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(clean_text)

        model_prob = max(0.0, min(1.0, float(parsed.get("return_probability", probability))))
        # Blend model evaluation (50%) with deterministic actuarial baseline (50%)
        blended_score = round((model_prob * 0.5) + (probability * 0.5), 4)

        reason = str(parsed.get("reasoning", f"Model estimate: {blended_score * 100:.0f}% return likelihood."))
        drivers = parsed.get("key_drivers") or [f"Significant market drop of {drop_percentage:.1f}%.", f"Purchased {days_since_purchase} days ago."]

        report = {
            "return_probability": blended_score,
            "confidence": str(parsed.get("confidence", "HIGH")),
            "risk_level": str(parsed.get("risk_level", "HIGH" if blended_score >= 0.5 else "MEDIUM")),
            "key_drivers": drivers,
            "reasoning": reason,
            "retention_impact": str(parsed.get("retention_impact", "Protects brand loyalty by proactively crediting the price drop.")),
            "recommended_action": str(parsed.get("recommended_action", "APPROVE_PARTIAL_REFUND")),
            "provider": active_provider,
            "model": model,
            "financial_breakdown": {
                "purchase_price": round(purchase_price, 2),
                "drop_percentage": round(drop_percentage, 1),
                "days_since_purchase": days_since_purchase,
                "proposed_refund": round(refund_amount, 2),
                "estimated_return_cost": round(return_cost, 2),
                "net_savings": round(savings, 2),
            },
        }
        return blended_score, reason, active_provider, report

    except Exception as exc:
        log.warning("LLM scoring failed (%s), falling back to actuarial rule report.", exc)
        fallback_report = build_rule_report(category, drop_percentage, days_since_purchase, probability, savings, product_name, purchase_price, refund_amount, return_cost)
        fallback_reason = f"{fallback_report['reasoning']} (LLM unavailable; using deterministic actuarial model)"
        fallback_report["reasoning"] = fallback_reason
        return probability, fallback_reason, "rules", fallback_report
