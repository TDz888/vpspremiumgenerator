"""
Simple In-Memory Cache
"""
import time
from threading import Lock

class SimpleCache:
    """Thread-safe in-memory cache with TTL"""
    
    def __init__(self, default_ttl=5):
        self._cache = {}
        self._lock = Lock()
        self._default_ttl = default_ttl
    
    def get(self, key):
        """Get value from cache"""
        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    return value
                else:
                    del self._cache[key]
        return None
    
    def set(self, key, value, ttl=None):
        """Set value in cache with TTL"""
        ttl = ttl or self._default_ttl
        expiry = time.time() + ttl
        with self._lock:
            self._cache[key] = (value, expiry)
    
    def delete(self, key):
        """Delete key from cache"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
    
    def clear(self):
        """Clear all cache"""
        with self._lock:
            self._cache.clear()
    
    def cleanup(self):
        """Remove expired entries"""
        with self._lock:
            now = time.time()
            expired = [k for k, (_, exp) in self._cache.items() if now >= exp]
            for k in expired:
                del self._cache[k]

# Global cache instance
cache = SimpleCache(default_ttl=5)
