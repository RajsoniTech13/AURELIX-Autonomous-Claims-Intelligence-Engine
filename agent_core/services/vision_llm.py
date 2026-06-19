"""
Vision LLM service using the native google-genai SDK.
Handles multimodal (image + text) analysis with Gemini Vision.
"""
import os
import json
import re
from typing import Type, TypeVar, List, Any
from pydantic import BaseModel
from PIL import Image

from agent_core.services.llm import retry_on_429, _get_cache, get_hash

T = TypeVar("T", bound=BaseModel)


def _get_genai_client():
    """Get a configured google-genai client."""
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set. Vision analysis requires Gemini.")

    client = genai.Client(api_key=api_key)
    return client


def _clean_json_from_response(text: str) -> str:
    """Extract JSON from a model response that may include markdown fences."""
    text = text.strip()
    # Remove markdown code fences
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


@retry_on_429
def analyze_images(
    images: List[Image.Image],
    prompt: str,
    model: str = "gemini-flash-latest",
) -> str:
    """
    Send PIL images + text prompt to Gemini Vision and return raw text response.
    """
    client = _get_genai_client()

    # Build content parts: images first, then text prompt
    contents = []
    for img in images:
        contents.append(img)
    contents.append(prompt)

    response = client.models.generate_content(
        model=model,
        contents=contents,
    )

    return response.text


@retry_on_429
def analyze_images_structured(
    images: List[Image.Image],
    prompt: str,
    response_model: Type[T],
    model: str = "gemini-flash-latest",
    conversation: str = None,
) -> T:
    """
    Send PIL images + text prompt to Gemini Vision and parse
    the response into a structured Pydantic model.
    Uses local JSON file cache if present; otherwise calls Gemini Vision API.
    """
    # 1. Cache lookup
    cache = _get_cache()
    if conversation and cache:
        c_hash = get_hash(conversation)
        if c_hash in cache:
            model_name = response_model.__name__
            agent_key = None
            if "ImageQuality" in model_name:
                agent_key = "image_quality"
            elif "VisionAnalysis" in model_name:
                agent_key = "vision_analysis"
                
            if agent_key and agent_key in cache[c_hash]:
                cached_res = cache[c_hash][agent_key]
                print(f"[Cache Hit] Returning cached response for {agent_key} ({c_hash[:8]})...", flush=True)
                return response_model.model_validate(cached_res)

    # 2. Live API Call
    # Build schema instruction
    schema_fields = response_model.model_json_schema()
    schema_instruction = (
        "\n\nYou MUST respond with ONLY a valid JSON object matching this exact schema. "
        "No markdown, no explanation, no extra text — just the JSON object.\n"
        f"Schema: {json.dumps(schema_fields, indent=2)}"
    )

    full_prompt = prompt + schema_instruction
    raw_response = analyze_images(images, full_prompt, model=model)

    # Parse JSON response
    cleaned = _clean_json_from_response(raw_response)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Try to extract JSON from the response using regex
        json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            raise ValueError(
                f"Failed to parse Vision model response as JSON.\n"
                f"Raw response: {raw_response[:500]}\n"
                f"Parse error: {e}"
            )

    result = response_model.model_validate(data)

    # 3. Save to cache
    if conversation:
        c_hash = get_hash(conversation)
        model_name = response_model.__name__
        agent_key = None
        if "ImageQuality" in model_name:
            agent_key = "image_quality"
        elif "VisionAnalysis" in model_name:
            agent_key = "vision_analysis"
            
        if agent_key:
            try:
                # Reload cache to avoid race conditions
                import agent_core.services.llm as llm_svc
                llm_svc._CACHE_DATA = None
                current_cache = _get_cache()
                if c_hash not in current_cache:
                    current_cache[c_hash] = {}
                current_cache[c_hash][agent_key] = json.loads(result.model_dump_json())
                
                # Write back
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                cache_path = os.path.join(base_dir, "data", "llm_cache.json")
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(current_cache, f, indent=2)
                print(f"[Cache Saved] Wrote live response for {agent_key} ({c_hash[:8]}) to {cache_path}", flush=True)
            except Exception as e:
                print(f"[Cache] Error saving to cache: {e}", flush=True)
                
    return result
