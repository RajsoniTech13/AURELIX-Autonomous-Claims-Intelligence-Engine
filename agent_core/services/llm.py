import os
import json
import re
import time
import random
from typing import Type, TypeVar, Dict, Any, List
from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

T = TypeVar("T", bound=BaseModel)

def clean_json_string(s: str) -> str:
    # Helper to strip markdown formatting around JSON
    s = s.strip()
    if s.startswith("```json"):
        s = s[7:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()

def get_llm():
    """Get the LLM client. Raises RuntimeError if no API key is configured."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No API key found. Set GEMINI_API_KEY or OPENAI_API_KEY in your environment or .env file."
        )

    # Gemini path
    if os.getenv("GEMINI_API_KEY"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-flash-latest",
            temperature=0.1,
            google_api_key=api_key,
            max_retries=2,
        )

    # OpenAI fallback
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model="gpt-4o-mini", temperature=0.1, openai_api_key=api_key, max_retries=2)


import hashlib

_CACHE_DATA = None

def get_hash(text: str) -> str:
    return hashlib.md5(text.strip().encode("utf-8")).hexdigest()

def _get_cache() -> Dict[str, Any]:
    global _CACHE_DATA
    if _CACHE_DATA is not None:
        return _CACHE_DATA
    
    # Resolve cache file path
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_path = os.path.join(base_dir, "data", "llm_cache.json")
    
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                _CACHE_DATA = json.load(f)
                return _CACHE_DATA
        except Exception as e:
            print(f"[Cache] Error reading cache file: {e}", flush=True)
            
    _CACHE_DATA = {}
    return _CACHE_DATA


def retry_on_429(func):
    """Decorator to retry API calls on 429 Rate Limits / Resource Exhaustion."""
    def wrapper(*args, **kwargs):
        max_attempts = 10  # Increase max attempts to handle higher load
        base_sleep = 5
        for attempt in range(max_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                err_str = str(e)
                is_rate_limit = any(term in err_str.lower() for term in ["429", "resource_exhausted", "quota exceeded", "rate limit"])
                if is_rate_limit and attempt < max_attempts - 1:
                    sleep_time = base_sleep * (2 ** attempt) + random.uniform(0, 1)
                    # Extract retryDelay if available in error message
                    # e.g., "Please retry in 57.565580092s"
                    delay_match = re.search(r"Please retry in (\d+\.?\d*)s", err_str)
                    if delay_match:
                        sleep_time = float(delay_match.group(1)) + 2.0 # Add a buffer
                    print(f"[LLM Retry] Hit rate limit (429). Sleeping for {sleep_time:.2f}s before retry {attempt+1}/{max_attempts}...", flush=True)
                    time.sleep(sleep_time)
                else:
                    raise e
    return wrapper


@retry_on_429
def call_structured_llm(
    prompt_template: str,
    variables: Dict[str, Any],
    response_model: Type[T],
) -> T:
    """
    Call the LLM with a prompt template and return a structured Pydantic output.
    Uses local JSON file cache if present; otherwise calls Gemini API.
    """
    # 1. Cache lookup
    cache = _get_cache()
    conversation = variables.get("conversation") or variables.get("user_claim_text")
    
    if conversation and cache:
        c_hash = get_hash(conversation)
        if c_hash in cache:
            model_name = response_model.__name__
            agent_key = None
            if "ClaimUnderstanding" in model_name:
                agent_key = "claim_understanding"
            elif "ImageQuality" in model_name:
                agent_key = "image_quality"
            elif "VisionAnalysis" in model_name:
                agent_key = "vision_analysis"
                
            if agent_key and agent_key in cache[c_hash]:
                cached_res = cache[c_hash][agent_key]
                print(f"[Cache Hit] Returning cached response for {agent_key} ({c_hash[:8]})...", flush=True)
                return response_model.model_validate(cached_res)

    # 2. Live API Call
    llm = get_llm()
    prompt = ChatPromptTemplate.from_template(prompt_template)
    chain = prompt | llm.with_structured_output(response_model)
    result = chain.invoke(variables)

    # 3. Save to cache
    if conversation:
        c_hash = get_hash(conversation)
        model_name = response_model.__name__
        agent_key = None
        if "ClaimUnderstanding" in model_name:
            agent_key = "claim_understanding"
        elif "ImageQuality" in model_name:
            agent_key = "image_quality"
        elif "VisionAnalysis" in model_name:
            agent_key = "vision_analysis"
            
        if agent_key:
            try:
                # Reload cache to avoid race conditions
                global _CACHE_DATA
                _CACHE_DATA = None
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
