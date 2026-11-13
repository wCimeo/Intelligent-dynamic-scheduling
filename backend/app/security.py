import hashlib, hmac, secrets, time
from collections import defaultdict, deque
from threading import Lock
from pwdlib import PasswordHash

passwords = PasswordHash.recommended()
DUMMY_HASH = passwords.hash(secrets.token_urlsafe(32))
def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def csrf_token(secret):
    value = secrets.token_urlsafe(32)
    return value + '.' + hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
def csrf_valid(token, secret):
    try:
        value, signature = token.split('.')
        return hmac.compare_digest(signature, hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest())
    except (ValueError, AttributeError):
        return False

class RateLimiter:
    # Single local API process. Deployments with multiple workers must use a shared limiter.
    def __init__(self):
        self.events = defaultdict(deque)
        self.lock = Lock()
    def allow(self, key):
        with self.lock:
            clock = time.monotonic()
            for old in list(self.events):
                if not self.events[old] or self.events[old][-1] < clock - 60:
                    del self.events[old]
            queue = self.events[key]
            while queue and queue[0] < clock - 60: queue.popleft()
            if len(queue) >= 20: return False
            queue.append(clock)
            return True
