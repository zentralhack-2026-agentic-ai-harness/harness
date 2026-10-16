"""What a call costs: the formula the evaluation's gateway charges by (see the README)."""


def cost(usage, price: dict) -> float:
    """USD for one call: its `usage` (a Responses API dict, or the openai SDK's object) at
    `price` (one model's entry of task.json's `prices`)."""
    
    if usage is None:
        return 0.0
    
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    
    inp, out = usage.get("input_tokens") or 0, usage.get("output_tokens") or 0
    details = usage.get("input_tokens_details") or {}
    cached = details.get("cached_tokens") or 0
    written = details.get("cache_write_tokens") or 0
    
    uncached = max(0, inp - cached - written)
    
    long = price.get("long_context")
    if long and inp > long["above_input_tokens"]:
        price = long
    
    p_in = price["input"]
    
    return (
        uncached * p_in
        + cached * price.get("cached_input", p_in)
        + written * price.get("cache_write", p_in)
        + out * price["output"]
    ) / 1e6
