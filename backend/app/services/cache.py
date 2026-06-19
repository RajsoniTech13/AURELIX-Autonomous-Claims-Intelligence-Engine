import json
import hashlib
from typing import Dict, Any, Optional
from backend.app.config import settings

# Global in-memory fallback cache
_in_memory_cache: Dict[str, str] = {}

def generate_cache_key(user_id: str, image_paths: str) -> str:
    # Generate a unique hash key based on user and image paths
    raw_str = f"{user_id}:{image_paths}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

def get_cached_result(user_id: str, image_paths: str) -> Optional[Dict[str, Any]]:
    key = generate_cache_key(user_id, image_paths)
    
    # Try Redis if configured
    if settings.REDIS_URL:
        try:
            import redis
            r = redis.from_url(settings.REDIS_URL)
            cached_data = r.get(key)
            if cached_data:
                print(f"[Cache] Redis Hit for key: {key}")
                return json.loads(cached_data)
        except Exception as e:
            print(f"[Cache] Redis get failed, falling back: {e}")
            
    # Try In-memory fallback
    if key in _in_memory_cache:
        print(f"[Cache] In-Memory Hit for key: {key}")
        return json.loads(_in_memory_cache[key])
        
    return None

def set_cached_result(user_id: str, image_paths: str, result: Dict[str, Any], expire_seconds: int = 3600):
    key = generate_cache_key(user_id, image_paths)
    serialized = json.dumps(result)
    
    # Save to Redis if configured
    if settings.REDIS_URL:
        try:
            import redis
            r = redis.from_url(settings.REDIS_URL)
            r.setex(key, expire_seconds, serialized)
            print(f"[Cache] Saved result to Redis for key: {key}")
            return
        except Exception as e:
            print(f"[Cache] Redis set failed: {e}")
            
    # Save to In-memory fallback
    _in_memory_cache[key] = serialized
    print(f"[Cache] Saved result to In-Memory Cache for key: {key}")
