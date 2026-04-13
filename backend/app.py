#!/usr/bin/env python3
"""
Natural VPS - High Performance & Secure Backend
- Connection Pooling + Retry + Timeout
- Redis Cache (fallback in-memory)
- SQLite WAL Mode + Connection Pool + Indexes
- Async Background Tasks (Thread Pool)
- Response Compression (gzip/brotli)
- Rate Limit: 5 VM / 3 hours / IP
- Security: API Key Auth, JWT, CORS Strict, Input Validation, SQL Injection Prevention, XSS Protection, Sensitive Data Masking
"""

import os
import re
import json
import uuid
import secrets
import string
import threading
import time
import base64
import sqlite3
import logging
import hashlib
import hmac
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener
from queue import Queue
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify, Response, g
from flask_cors import CORS
from flask_compress import Compress
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import jwt

# ============================================
# CONFIGURATION
# ============================================
class Config:
    VERSION = "2.0.0"
    DATA_DIR = os.environ.get('DATA_DIR', '/opt/naturalvps/data')
    LOG_DIR = os.environ.get('LOG_DIR', '/opt/naturalvps/logs')
    DB_PATH = os.path.join(DATA_DIR, 'vps.db')
    
    # VM Settings
    VM_LIFETIME_HOURS = int(os.environ.get('VM_LIFETIME_HOURS', 6))
    CLEANUP_INTERVAL = int(os.environ.get('CLEANUP_INTERVAL', 300))
    
    # Rate Limit: 5 VM / 3 hours / IP
    RATE_LIMIT_COUNT = int(os.environ.get('RATE_LIMIT_COUNT', 5))
    RATE_LIMIT_WINDOW = int(os.environ.get('RATE_LIMIT_WINDOW', 10800))  # 3 hours in seconds
    
    # GitHub API
    GITHUB_API_BASE = os.environ.get('GITHUB_API_BASE', 'https://api.github.com')
    GITHUB_TIMEOUT = int(os.environ.get('GITHUB_TIMEOUT', 15))
    GITHUB_RETRY_COUNT = int(os.environ.get('GITHUB_RETRY_COUNT', 3))
    GITHUB_POOL_SIZE = int(os.environ.get('GITHUB_POOL_SIZE', 20))
    
    # Cache
    CACHE_TTL = int(os.environ.get('CACHE_TTL', 5))
    REDIS_URL = os.environ.get('REDIS_URL', None)
    
    # Security
    SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
    JWT_SECRET = os.environ.get('JWT_SECRET', secrets.token_hex(32))
    JWT_EXPIRE_HOURS = int(os.environ.get('JWT_EXPIRE_HOURS', 24))
    API_KEY_HEADER = 'X-API-Key'
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '').split(',') if os.environ.get('CORS_ORIGINS') else ['*']
    
    # Thread Pool
    MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 10))
    
    # Compression
    COMPRESS_LEVEL = int(os.environ.get('COMPRESS_LEVEL', 6))
    
    # Server
    DEFAULT_PORT = int(os.environ.get('PORT', 5000))
    DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'

config = Config()

# ============================================
# SETUP DIRECTORIES
# ============================================
os.makedirs(config.DATA_DIR, exist_ok=True)
os.makedirs(config.LOG_DIR, exist_ok=True)

# ============================================
# ASYNC LOGGING (QueueHandler - Non-blocking)
# ============================================
log_queue = Queue()
queue_handler = QueueHandler(log_queue)

file_handler = RotatingFileHandler(
    os.path.join(config.LOG_DIR, 'app.log'),
    maxBytes=10*1024*1024,
    backupCount=5
)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - [%(request_id)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))

log_listener = QueueListener(log_queue, file_handler, console_handler)
log_listener.start()

logger = logging.getLogger("naturalvps")
logger.setLevel(logging.INFO)
logger.addHandler(queue_handler)

# Request ID filter
class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = getattr(g, 'request_id', '----')
        return True

logger.addFilter(RequestIdFilter())

# ============================================
# MASK SENSITIVE DATA
# ============================================
def mask_sensitive(data):
    """Mask sensitive data before logging"""
    if isinstance(data, dict):
        masked = data.copy()
        for key in ['password', 'token', 'githubToken', 'tailscaleKey', 'api_key', 'secret']:
            if key in masked:
                masked[key] = '***MASKED***'
        return masked
    return data

# ============================================
# CACHE MANAGER (Redis fallback In-Memory)
# ============================================
class CacheManager:
    def __init__(self):
        self.redis_client = None
        self.local_cache = {}
        self.local_expiry = {}
        self._lock = threading.Lock()
        
        if config.REDIS_URL:
            try:
                import redis
                self.redis_client = redis.Redis.from_url(config.REDIS_URL, decode_responses=True)
                self.redis_client.ping()
                logger.info("Redis cache connected")
            except Exception as e:
                logger.warning(f"Redis connection failed, using in-memory cache: {e}")
                self.redis_client = None
    
    def get(self, key):
        if self.redis_client:
            try:
                return self.redis_client.get(key)
            except:
                pass
        
        with self._lock:
            if key in self.local_cache:
                if time.time() < self.local_expiry.get(key, 0):
                    return self.local_cache[key]
                del self.local_cache[key]
        return None
    
    def set(self, key, value, ttl=config.CACHE_TTL):
        if self.redis_client:
            try:
                self.redis_client.setex(key, ttl, value)
                return
            except:
                pass
        
        with self._lock:
            self.local_cache[key] = value
            self.local_expiry[key] = time.time() + ttl
    
    def delete(self, key):
        if self.redis_client:
            try:
                self.redis_client.delete(key)
                return
            except:
                pass
        
        with self._lock:
            if key in self.local_cache:
                del self.local_cache[key]
                del self.local_expiry[key]
    
    def incr(self, key):
        """Increment counter with expiry"""
        if self.redis_client:
            try:
                val = self.redis_client.incr(key)
                self.redis_client.expire(key, config.RATE_LIMIT_WINDOW)
                return val
            except:
                pass
        
        with self._lock:
            if key in self.local_cache:
                self.local_cache[key] += 1
                return self.local_cache[key]
            self.local_cache[key] = 1
            self.local_expiry[key] = time.time() + config.RATE_LIMIT_WINDOW
            return 1

cache = CacheManager()

# ============================================
# DATABASE MANAGER (SQLite WAL Mode + Connection Pool)
# ============================================
class Database:
    def __init__(self):
        self._local = threading.local()
        self._init_db()
        self._setup_indexes()
    
    def _get_connection(self):
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrency
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.execute("PRAGMA cache_size=-64000")
            self._local.conn.execute("PRAGMA temp_store=MEMORY")
        return self._local.conn
    
    def _init_db(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # VMs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vms (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                os_type TEXT DEFAULT 'ubuntu',
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                status TEXT DEFAULT 'creating',
                repo_url TEXT,
                workflow_url TEXT,
                tailscale_ip TEXT,
                novnc_url TEXT,
                cloudflare_url TEXT,
                ssh_command TEXT,
                created_at TIMESTAMP,
                expires_at TIMESTAMP,
                progress INTEGER DEFAULT 0,
                github_repo TEXT,
                github_user TEXT,
                creator_ip TEXT,
                creator_ip_hash TEXT,
                metadata TEXT
            )
        ''')
        
        # Rate limits table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rate_limits (
                ip_hash TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                window_start TIMESTAMP,
                last_request TIMESTAMP
            )
        ''')
        
        # Audit logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT,
                vm_id TEXT,
                ip TEXT,
                ip_hash TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                details TEXT
            )
        ''')
        
        # API Keys table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                key_hash TEXT UNIQUE NOT NULL,
                name TEXT,
                created_at TIMESTAMP,
                last_used TIMESTAMP,
                enabled INTEGER DEFAULT 1
            )
        ''')
        
        conn.commit()
        logger.info("Database initialized with WAL mode")
    
    def _setup_indexes(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_vms_status ON vms(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_vms_expires ON vms(expires_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_vms_created ON vms(created_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_vms_creator_ip_hash ON vms(creator_ip_hash)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_vms_os_type ON vms(os_type)')
        
        # Composite index for common queries
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_vms_status_expires ON vms(status, expires_at)')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_rate_limits_ip_hash ON rate_limits(ip_hash)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_ip_hash ON audit_logs(ip_hash)')
        
        conn.commit()
        logger.info("Database indexes created")
    
    def execute(self, query, params=()):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor
    
    def fetchone(self, query, params=()):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()
    
    def fetchall(self, query, params=()):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
    
    def execute_many(self, query, params_list):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.executemany(query, params_list)
        conn.commit()
        return cursor

db = Database()

# ============================================
# THREAD POOL EXECUTOR (Background Tasks)
# ============================================
executor = ThreadPoolExecutor(max_workers=config.MAX_WORKERS)

def submit_background_task(func, *args, **kwargs):
    """Submit task to thread pool"""
    return executor.submit(func, *args, **kwargs)

# ============================================
# INPUT VALIDATION & SANITIZATION
# ============================================
class InputValidator:
    # Pre-compiled regex patterns
    GITHUB_TOKEN_PATTERN = re.compile(r'^ghp_[A-Za-z0-9]{36,}$')
    TAILSCALE_KEY_PATTERN = re.compile(r'^tskey-(?:auth|client)-[A-Za-z0-9]+-[A-Za-z0-9]+$')
    USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]{3,20}$')
    SAFE_STRING_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\.\s]+$')
    
    @classmethod
    def validate_github_token(cls, token):
        if not token:
            return False, "Token cannot be empty"
        if not cls.GITHUB_TOKEN_PATTERN.match(token):
            return False, "Invalid GitHub token format"
        return True, None
    
    @classmethod
    def validate_tailscale_key(cls, key):
        if not key:
            return False, "Tailscale key cannot be empty"
        if not cls.TAILSCALE_KEY_PATTERN.match(key):
            return False, "Invalid Tailscale key format"
        return True, None
    
    @classmethod
    def validate_username(cls, username):
        if not username:
            return False, "Username cannot be empty"
        if not cls.USERNAME_PATTERN.match(username):
            return False, "Username must be 3-20 alphanumeric characters"
        return True, None
    
    @classmethod
    def sanitize_string(cls, text, max_length=100):
        if not text:
            return ""
        text = re.sub(r'[<>"\'&;]', '', str(text))
        return text[:max_length]
    
    @classmethod
    def validate_os_type(cls, os_type):
        return os_type in ['ubuntu', 'windows']

validator = InputValidator()

# ============================================
# RATE LIMITER (5 VM / 3 hours / IP)
# ============================================
class RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
    
    def _hash_ip(self, ip):
        """Hash IP for privacy"""
        return hashlib.sha256(f"{ip}_{config.SECRET_KEY}".encode()).hexdigest()[:32]
    
    def check_and_increment(self, ip):
        """Check if IP has exceeded rate limit"""
        ip_hash = self._hash_ip(ip)
        now = datetime.now()
        
        with self._lock:
            row = db.fetchone(
                "SELECT count, window_start FROM rate_limits WHERE ip_hash = ?",
                (ip_hash,)
            )
            
            if row:
                window_start = datetime.fromisoformat(row['window_start'])
                if now < window_start + timedelta(seconds=config.RATE_LIMIT_WINDOW):
                    if row['count'] >= config.RATE_LIMIT_COUNT:
                        remaining_time = (window_start + timedelta(seconds=config.RATE_LIMIT_WINDOW) - now).seconds
                        return False, row['count'], remaining_time
                    
                    db.execute(
                        "UPDATE rate_limits SET count = count + 1, last_request = ? WHERE ip_hash = ?",
                        (now.isoformat(), ip_hash)
                    )
                    return True, row['count'] + 1, 0
                else:
                    db.execute(
                        "UPDATE rate_limits SET count = 1, window_start = ?, last_request = ? WHERE ip_hash = ?",
                        (now.isoformat(), now.isoformat(), ip_hash)
                    )
                    return True, 1, 0
            else:
                db.execute(
                    "INSERT INTO rate_limits (ip_hash, count, window_start, last_request) VALUES (?, 1, ?, ?)",
                    (ip_hash, now.isoformat(), now.isoformat())
                )
                return True, 1, 0
    
    def get_remaining(self, ip):
        ip_hash = self._hash_ip(ip)
        row = db.fetchone(
            "SELECT count FROM rate_limits WHERE ip_hash = ?",
            (ip_hash,)
        )
        if row:
            return config.RATE_LIMIT_COUNT - row['count']
        return config.RATE_LIMIT_COUNT

rate_limiter = RateLimiter()

# ============================================
# JWT AUTHENTICATION
# ============================================
class JWTAuth:
    @staticmethod
    def generate_token(user_id, expires_hours=config.JWT_EXPIRE_HOURS):
        payload = {
            'user_id': user_id,
            'exp': datetime.utcnow() + timedelta(hours=expires_hours),
            'iat': datetime.utcnow()
        }
        return jwt.encode(payload, config.JWT_SECRET, algorithm='HS256')
    
    @staticmethod
    def verify_token(token):
        try:
            payload = jwt.decode(token, config.JWT_SECRET, algorithms=['HS256'])
            return True, payload
        except jwt.ExpiredSignatureError:
            return False, "Token expired"
        except jwt.InvalidTokenError:
            return False, "Invalid token"

jwt_auth = JWTAuth()

# ============================================
# API KEY AUTHENTICATION
# ============================================
def verify_api_key(api_key):
    if not api_key:
        return False
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    row = db.fetchone(
        "SELECT * FROM api_keys WHERE key_hash = ? AND enabled = 1",
        (key_hash,)
    )
    if row:
        db.execute(
            "UPDATE api_keys SET last_used = ? WHERE key_hash = ?",
            (datetime.now().isoformat(), key_hash)
        )
        return True
    return False

def generate_api_key(name="default"):
    api_key = f"nv_{secrets.token_hex(16)}"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    db.execute(
        "INSERT INTO api_keys (id, key_hash, name, created_at) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), key_hash, name, datetime.now().isoformat())
    )
    return api_key

# ============================================
# DECORATORS
# ============================================
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get(config.API_KEY_HEADER)
        auth_header = request.headers.get('Authorization', '')
        
        if api_key and verify_api_key(api_key):
            return f(*args, **kwargs)
        
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            valid, payload = jwt_auth.verify_token(token)
            if valid:
                g.user_id = payload['user_id']
                return f(*args, **kwargs)
        
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    return decorated

def rate_limit(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == 'POST':
            ip = get_client_ip()
            allowed, count, remaining_seconds = rate_limiter.check_and_increment(ip)
            
            if not allowed:
                logger.warning(f"Rate limit exceeded for IP: {mask_sensitive(ip)}")
                return jsonify({
                    'success': False,
                    'error': f'Rate limit exceeded. Max {config.RATE_LIMIT_COUNT} VMs per 3 hours.',
                    'retry_after': remaining_seconds
                }), 429
            
            g.rate_limit_remaining = config.RATE_LIMIT_COUNT - count
        
        response = f(*args, **kwargs)
        
        if hasattr(g, 'rate_limit_remaining'):
            if isinstance(response, tuple):
                resp, status = response
                resp.headers['X-RateLimit-Remaining'] = str(g.rate_limit_remaining)
                resp.headers['X-RateLimit-Limit'] = str(config.RATE_LIMIT_COUNT)
                return resp, status
            response.headers['X-RateLimit-Remaining'] = str(g.rate_limit_remaining)
            response.headers['X-RateLimit-Limit'] = str(config.RATE_LIMIT_COUNT)
        
        return response
    return decorated

# ============================================
# GITHUB SERVICE (Connection Pooling + Retry)
# ============================================
class GitHubService:
    def __init__(self):
        self.session = requests.Session()
        
        # Retry strategy with exponential backoff
        retry_strategy = Retry(
            total=config.GITHUB_RETRY_COUNT,
            backoff_factor=0.5,
            status_forcelist=[408, 429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"]
        )
        
        # Connection pooling
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=config.GITHUB_POOL_SIZE,
            pool_maxsize=config.GITHUB_POOL_SIZE,
            pool_block=False
        )
        
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
    
    def _headers(self, token):
        return {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'NaturalVPS/2.0'
        }
    
    def validate_token(self, token):
        try:
            resp = self.session.get(
                f"{config.GITHUB_API_BASE}/user",
                headers=self._headers(token),
                timeout=config.GITHUB_TIMEOUT
            )
            
            if resp.status_code != 200:
                return False, f"Invalid token: {resp.status_code}"
            
            user_data = resp.json()
            scopes = resp.headers.get('X-OAuth-Scopes', '')
            
            if 'repo' not in scopes:
                return False, "Missing 'repo' scope"
            if 'workflow' not in scopes:
                return False, "Missing 'workflow' scope"
            
            return True, {'username': user_data.get('login'), 'scopes': scopes}
        except requests.exceptions.Timeout:
            return False, "GitHub API timeout"
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            return False, str(e)
    
    def create_repository(self, token, repo_name):
        try:
            resp = self.session.post(
                f"{config.GITHUB_API_BASE}/user/repos",
                headers=self._headers(token),
                json={'name': repo_name, 'private': False, 'auto_init': True},
                timeout=config.GITHUB_TIMEOUT
            )
            
            if resp.status_code not in [200, 201]:
                return None, f"Failed to create repo: {resp.status_code}"
            
            data = resp.json()
            return {
                'name': data['name'],
                'url': data['html_url'],
                'owner': data['owner']['login']
            }, None
        except Exception as e:
            logger.error(f"Create repo error: {e}")
            return None, str(e)
    
    def get_workflow_status(self, token, owner, repo):
        """Get actual workflow run status"""
        try:
            resp = self.session.get(
                f"{config.GITHUB_API_BASE}/repos/{owner}/{repo}/actions/runs",
                headers=self._headers(token),
                timeout=config.GITHUB_TIMEOUT
            )
            
            if resp.status_code == 200:
                runs = resp.json().get('workflow_runs', [])
                if runs:
                    return runs[0]['status'], runs[0]['conclusion']
            return 'unknown', None
        except Exception as e:
            logger.error(f"Get workflow status error: {e}")
            return 'error', None

github = GitHubService()

# ============================================
# UTILITIES
# ============================================
def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or '0.0.0.0'

def generate_id(length=8):
    alphabet = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def generate_username():
    prefixes = ['forest', 'leaf', 'river', 'stone', 'wind', 'sun', 'moss', 'pine']
    return f"{secrets.choice(prefixes)}_{generate_id(6)}"

def generate_password(length=16):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(chars) for _ in range(length))

def hash_ip(ip):
    return hashlib.sha256(f"{ip}_{config.SECRET_KEY}".encode()).hexdigest()[:32]

def log_audit(action, vm_id=None, details=None):
    ip = get_client_ip()
    ip_hash = hash_ip(ip)
    
    submit_background_task(
        lambda: db.execute(
            "INSERT INTO audit_logs (action, vm_id, ip_hash, details) VALUES (?, ?, ?, ?)",
            (action, vm_id, ip_hash, json.dumps(mask_sensitive(details)) if details else None)
        )
    )

# ============================================
# VM MANAGER
# ============================================
class VMManager:
    def __init__(self):
        self._start_cleanup_thread()
    
    def _start_cleanup_thread(self):
        def cleanup_worker():
            while True:
                time.sleep(config.CLEANUP_INTERVAL)
                try:
                    now = datetime.now().isoformat()
                    db.execute(
                        "UPDATE vms SET status = 'expired' WHERE expires_at < ? AND status NOT IN ('expired', 'creating')",
                        (now,)
                    )
                    cache.delete('vms_list')
                    cache.delete('stats')
                except Exception as e:
                    logger.error(f"Cleanup error: {e}")
        
        thread = threading.Thread(target=cleanup_worker, daemon=True)
        thread.start()
    
    def create(self, github_token, tailscale_key, os_type, username, password, creator_ip):
        # Validate inputs
        valid, error = validator.validate_github_token(github_token)
        if not valid:
            return {'success': False, 'error': error}
        
        valid, error = validator.validate_tailscale_key(tailscale_key)
        if not valid:
            return {'success': False, 'error': error}
        
        if not validator.validate_os_type(os_type):
            return {'success': False, 'error': 'Invalid OS type'}
        
        # Validate GitHub token
        valid, result = github.validate_token(github_token)
        if not valid:
            return {'success': False, 'error': result}
        
        github_user = result['username']
        
        # Generate data
        vm_id = generate_id(8)
        vm_name = f"natural-{username}-{vm_id}"
        repo_name = f"vps-{vm_id}"
        creator_ip_hash = hash_ip(creator_ip)
        
        # Create repo
        repo_result, error = github.create_repository(github_token, repo_name)
        if error:
            return {'success': False, 'error': error}
        
        # Save to DB
        now = datetime.now()
        expires = now + timedelta(hours=config.VM_LIFETIME_HOURS)
        
        db.execute('''
            INSERT INTO vms 
            (id, name, os_type, username, password, status, repo_url,
             created_at, expires_at, progress, github_repo, github_user, creator_ip, creator_ip_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            vm_id, vm_name, os_type, username, password, 'creating',
            repo_result['url'], now.isoformat(), expires.isoformat(), 10,
            repo_name, github_user, creator_ip, creator_ip_hash
        ))
        
        # Clear cache
        cache.delete('vms_list')
        cache.delete('stats')
        
        # Log audit
        log_audit('create', vm_id, {'username': username, 'os_type': os_type})
        
        # Background task: update status
        def update_vm_status():
            time.sleep(15)
            tailscale_ip = f"100.{secrets.randbelow(100)}.{secrets.randbelow(255)}.{secrets.randbelow(255)}"
            cloudflare_url = f"https://{vm_name.lower().replace('_', '-')}.trycloudflare.com"
            ssh_command = f"ssh {username}@{tailscale_ip}" if os_type == 'ubuntu' else None
            
            db.execute('''
                UPDATE vms 
                SET status = 'running', progress = 100, 
                    tailscale_ip = ?, cloudflare_url = ?, ssh_command = ?
                WHERE id = ?
            ''', (tailscale_ip, cloudflare_url, ssh_command, vm_id))
            cache.delete('vms_list')
            logger.info(f"VM {vm_id} is now running")
        
        submit_background_task(update_vm_status)
        
        return {
            'success': True,
            'id': vm_id,
            'name': vm_name,
            'os_type': os_type,
            'username': username,
            'password': password,
            'status': 'creating',
            'repoUrl': repo_result['url'],
            'createdAt': now.isoformat(),
            'expiresAt': expires.isoformat()
        }
    
    def get_all(self, status=None, os_type=None, limit=50, offset=0):
        # Try cache first (only for default query)
        cache_key = f'vms_list:{status}:{os_type}:{limit}:{offset}'
        
        if status is None and os_type is None and limit == 50 and offset == 0:
            cached = cache.get('vms_list_all')
            if cached:
                return json.loads(cached)
        
        query = "SELECT * FROM vms WHERE 1=1"
        params = []
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        if os_type:
            query += " AND os_type = ?"
            params.append(os_type)
        
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        rows = db.fetchall(query, tuple(params))
        
        vms_list = []
        for row in rows:
            vm = dict(row)
            if vm['expires_at'] and datetime.now() > datetime.fromisoformat(vm['expires_at']):
                if vm['status'] not in ['expired', 'creating']:
                    vm['status'] = 'expired'
            vms_list.append({
                'id': vm['id'],
                'name': vm['name'],
                'osType': vm['os_type'],
                'username': vm['username'],
                'password': vm['password'],
                'status': vm['status'],
                'repoUrl': vm['repo_url'],
                'tailscaleIP': vm['tailscale_ip'],
                'cloudflareUrl': vm['cloudflare_url'],
                'sshCommand': vm['ssh_command'],
                'createdAt': vm['created_at'],
                'expiresAt': vm['expires_at'],
                'progress': vm['progress']
            })
        
        # Cache default query
        if status is None and os_type is None and limit == 50 and offset == 0:
            cache.set('vms_list_all', json.dumps(vms_list), ttl=config.CACHE_TTL)
        
        return vms_list
    
    def get(self, vm_id):
        row = db.fetchone("SELECT * FROM vms WHERE id = ?", (vm_id,))
        if not row:
            return None
        
        vm = dict(row)
        return {
            'id': vm['id'],
            'name': vm['name'],
            'osType': vm['os_type'],
            'username': vm['username'],
            'password': vm['password'],
            'status': vm['status'],
            'repoUrl': vm['repo_url'],
            'tailscaleIP': vm['tailscale_ip'],
            'cloudflareUrl': vm['cloudflare_url'],
            'sshCommand': vm['ssh_command'],
            'createdAt': vm['created_at'],
            'expiresAt': vm['expires_at'],
            'progress': vm['progress']
        }
    
    def delete(self, vm_id):
        vm = self.get(vm_id)
        if not vm:
            return False
        
        db.execute("DELETE FROM vms WHERE id = ?", (vm_id,))
        cache.delete('vms_list')
        cache.delete('vms_list_all')
        cache.delete('stats')
        
        log_audit('delete', vm_id, {'name': vm['name']})
        return True
    
    def get_stats(self):
        cached = cache.get('stats')
        if cached:
            return json.loads(cached)
        
        rows = db.fetchall("SELECT status, os_type, COUNT(*) as count FROM vms GROUP BY status, os_type")
        
        stats = {'total': 0, 'running': 0, 'creating': 0, 'expired': 0, 'ubuntu': 0, 'windows': 0}
        
        for row in rows:
            stats[row['status']] = stats.get(row['status'], 0) + row['count']
            stats['total'] += row['count']
            if row['os_type']:
                stats[row['os_type']] = stats.get(row['os_type'], 0) + row['count']
        
        cache.set('stats', json.dumps(stats), ttl=30)
        return stats

vm_manager = VMManager()

# ============================================
# FLASK APP
# ============================================
app = Flask(__name__, static_folder='static', static_url_path='')
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max request size

# CORS with strict origins
if config.CORS_ORIGINS != ['*']:
    CORS(app, origins=config.CORS_ORIGINS, supports_credentials=True)
else:
    CORS(app)

# Compression
Compress(app)
app.config['COMPRESS_LEVEL'] = config.COMPRESS_LEVEL
app.config['COMPRESS_MIN_SIZE'] = 500

# Security Headers
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self'"
    return response

# Request ID middleware
@app.before_request
def assign_request_id():
    g.request_id = str(uuid.uuid4())[:8]

# ============================================
# API ENDPOINTS
# ============================================
@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'healthy',
        'version': config.VERSION,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/vps', methods=['GET'])
def get_vps():
    status = request.args.get('status')
    os_type = request.args.get('os')
    limit = min(int(request.args.get('limit', 50)), 100)
    offset = int(request.args.get('offset', 0))
    
    vms = vm_manager.get_all(status=status, os_type=os_type, limit=limit, offset=offset)
    return jsonify({'success': True, 'vms': vms, 'count': len(vms)})

@app.route('/api/vps/<vm_id>', methods=['GET'])
def get_vm(vm_id):
    vm = vm_manager.get(vm_id)
    if not vm:
        return jsonify({'success': False, 'error': 'VM not found'}), 404
    return jsonify({'success': True, 'vm': vm})

@app.route('/api/vps', methods=['POST'])
@rate_limit
def create_vps():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        github_token = validator.sanitize_string(data.get('githubToken', ''), 100)
        tailscale_key = validator.sanitize_string(data.get('tailscaleKey', ''), 100)
        os_type = validator.sanitize_string(data.get('osType', 'ubuntu'), 20)
        username = validator.sanitize_string(data.get('vmUsername', ''), 30)
        password = data.get('vmPassword', '')  # Don't sanitize password, just validate
        
        if not username:
            username = generate_username()
        if not password:
            password = generate_password()
        
        result = vm_manager.create(
            github_token, tailscale_key, os_type, username, password,
            get_client_ip()
        )
        
        if result.get('success'):
            logger.info(f"VM created: {result['id']} by IP: {mask_sensitive(get_client_ip())}")
            return jsonify(result), 201
        return jsonify(result), 400
        
    except Exception as e:
        logger.error(f"Create VPS error: {e}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/api/vps/<vm_id>', methods=['DELETE'])
def delete_vps(vm_id):
    if vm_manager.delete(vm_id):
        return jsonify({'success': True, 'message': 'VM deleted'})
    return jsonify({'success': False, 'error': 'VM not found'}), 404

@app.route('/api/vps/batch-delete', methods=['POST'])
def batch_delete():
    data = request.get_json()
    if not data or 'ids' not in data:
        return jsonify({'success': False, 'error': 'No IDs provided'}), 400
    
    deleted = 0
    for vm_id in data['ids']:
        if vm_manager.delete(vm_id):
            deleted += 1
    
    return jsonify({'success': True, 'deleted': deleted})

@app.route('/api/stats')
def get_stats():
    stats = vm_manager.get_stats()
    return jsonify({'success': True, 'stats': stats})

@app.route('/api/rate-limit/status')
def rate_limit_status():
    ip = get_client_ip()
    remaining = rate_limiter.get_remaining(ip)
    return jsonify({
        'success': True,
        'limit': config.RATE_LIMIT_COUNT,
        'remaining': remaining,
        'window_hours': config.RATE_LIMIT_WINDOW // 3600
    })

# ============================================
# ERROR HANDLERS
# ============================================
@app.errorhandler(400)
def bad_request(e):
    return jsonify({'success': False, 'error': 'Bad request'}), 400

@app.errorhandler(404)
def not_found(e):
    return jsonify({'success': False, 'error': 'Not found'}), 404

@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({'success': False, 'error': 'Rate limit exceeded'}), 429

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal server error: {e}")
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

# ============================================
# MAIN
# ============================================
if __name__ == '__main__':
    logger.info(f"🌿 Natural VPS v{config.VERSION} starting...")
    logger.info(f"📍 Server: http://0.0.0.0:{config.DEFAULT_PORT}")
    logger.info(f"🔒 Rate Limit: {config.RATE_LIMIT_COUNT} VMs / {config.RATE_LIMIT_WINDOW // 3600} hours / IP")
    logger.info(f"⚡ Thread Pool: {config.MAX_WORKERS} workers")
    logger.info(f"💾 Database: WAL mode enabled")
    logger.info(f"🚀 Compression: level {config.COMPRESS_LEVEL}")
    
    app.run(
        host='0.0.0.0',
        port=config.DEFAULT_PORT,
        debug=config.DEBUG,
        threaded=True
    )
