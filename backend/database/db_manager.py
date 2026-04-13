"""
SQLite Database Manager
"""
import sqlite3
import json
import os
from threading import Lock
from datetime import datetime, timedelta
from utils.logger import logger
from config import config

class DatabaseManager:
    """SQLite database manager with connection pooling"""
    
    def __init__(self, db_path='data/vms.db'):
        self.db_path = db_path
        self._lock = Lock()
        self._local = None
        self._init_db()
    
    def _get_connection(self):
        """Get database connection"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        """Initialize database tables"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # VMs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS vms (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    username TEXT NOT NULL,
                    password TEXT NOT NULL,
                    status TEXT DEFAULT 'creating',
                    repo_url TEXT,
                    workflow_url TEXT,
                    tailscale_ip TEXT,
                    novnc_url TEXT,
                    created_at TEXT,
                    expires_at TEXT,
                    progress INTEGER DEFAULT 0,
                    github_repo TEXT,
                    github_user TEXT,
                    creator_ip TEXT,
                    data TEXT
                )
            ''')
            
            # Indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON vms(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON vms(created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_expires_at ON vms(expires_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_creator_ip ON vms(creator_ip)')
            
            # Rate limits table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS rate_limits (
                    ip TEXT PRIMARY KEY,
                    count INTEGER DEFAULT 0,
                    reset_at TEXT
                )
            ''')
            
            conn.commit()
            conn.close()
        
        logger.info(f"Database initialized at {self.db_path}")
    
    # ========== VM Operations ==========
    
    def save_vm(self, vm_data):
        """Save or update VM"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO vms 
                (id, name, username, password, status, repo_url, workflow_url, 
                 tailscale_ip, novnc_url, created_at, expires_at, progress, 
                 github_repo, github_user, creator_ip, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                vm_data.get('id'),
                vm_data.get('name'),
                vm_data.get('username'),
                vm_data.get('password'),
                vm_data.get('status', 'creating'),
                vm_data.get('repoUrl'),
                vm_data.get('workflowUrl'),
                vm_data.get('tailscaleIP'),
                vm_data.get('novncUrl'),
                vm_data.get('createdAt'),
                vm_data.get('expiresAt'),
                vm_data.get('progress', 0),
                vm_data.get('githubRepo'),
                vm_data.get('githubUser'),
                vm_data.get('creatorIP'),
                json.dumps(vm_data)
            ))
            
            conn.commit()
            conn.close()
        
        logger.debug(f"VM saved: {vm_data.get('id')}")
    
    def get_vm(self, vm_id):
        """Get single VM by ID"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM vms WHERE id = ?', (vm_id,))
            row = cursor.fetchone()
            conn.close()
        
        if row:
            return dict(row)
        return None
    
    def get_all_vms(self):
        """Get all VMs"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM vms ORDER BY created_at DESC')
            rows = cursor.fetchall()
            conn.close()
        
        return [dict(row) for row in rows]
    
    def delete_vm(self, vm_id):
        """Delete VM by ID"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM vms WHERE id = ?', (vm_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            conn.close()
        
        if deleted:
            logger.info(f"VM deleted: {vm_id}")
        return deleted
    
    def delete_batch_vms(self, vm_ids):
        """Delete multiple VMs"""
        if not vm_ids:
            return 0
        
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            placeholders = ','.join('?' * len(vm_ids))
            cursor.execute(f'DELETE FROM vms WHERE id IN ({placeholders})', vm_ids)
            count = cursor.rowcount
            conn.commit()
            conn.close()
        
        logger.info(f"Batch deleted {count} VMs")
        return count
    
    def get_expired_vms(self):
        """Get expired VMs"""
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM vms 
                WHERE expires_at IS NOT NULL 
                AND expires_at < ?
                AND status != 'expired'
            ''', (now,))
            rows = cursor.fetchall()
            conn.close()
        
        return [dict(row) for row in rows]
    
    def update_vm_status(self, vm_id, status, progress=None):
        """Update VM status"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if progress is not None:
                cursor.execute('''
                    UPDATE vms SET status = ?, progress = ? WHERE id = ?
                ''', (status, progress, vm_id))
            else:
                cursor.execute('UPDATE vms SET status = ? WHERE id = ?', (status, vm_id))
            
            updated = cursor.rowcount > 0
            conn.commit()
            conn.close()
        
        return updated
    
    def count_vms_by_ip(self, ip, hours=1):
        """Count VMs created by IP in last N hours"""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM vms 
                WHERE creator_ip = ? AND created_at > ?
            ''', (ip, since))
            count = cursor.fetchone()[0]
            conn.close()
        
        return count
    
    # ========== Rate Limit Operations ==========
    
    def check_rate_limit(self, ip, limit=5):
        """Check if IP is rate limited"""
        now = datetime.now()
        
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM rate_limits WHERE ip = ?', (ip,))
            row = cursor.fetchone()
            
            if row:
                reset_at = datetime.fromisoformat(row['reset_at'])
                if now < reset_at:
                    # Still in rate limit window
                    if row['count'] >= limit:
                        conn.close()
                        return False, row['count'], reset_at.isoformat()
                    # Increment count
                    cursor.execute('''
                        UPDATE rate_limits SET count = count + 1 WHERE ip = ?
                    ''', (ip,))
                    new_count = row['count'] + 1
                else:
                    # Reset window
                    reset_at = now + timedelta(hours=1)
                    cursor.execute('''
                        UPDATE rate_limits SET count = 1, reset_at = ? WHERE ip = ?
                    ''', (reset_at.isoformat(), ip))
                    new_count = 1
            else:
                # First request
                reset_at = now + timedelta(hours=1)
                cursor.execute('''
                    INSERT INTO rate_limits (ip, count, reset_at) VALUES (?, 1, ?)
                ''', (ip, reset_at.isoformat()))
                new_count = 1
            
            conn.commit()
            conn.close()
        
        return True, new_count, reset_at.isoformat()
    
    def cleanup_expired(self):
        """Cleanup expired VMs and rate limits"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Mark VMs as expired
            now = datetime.now().isoformat()
            cursor.execute('''
                UPDATE vms SET status = 'expired' 
                WHERE expires_at IS NOT NULL AND expires_at < ? AND status != 'expired'
            ''', (now,))
            expired_count = cursor.rowcount
            
            # Clean old rate limits
            cursor.execute('DELETE FROM rate_limits WHERE reset_at < ?', (now,))
            
            conn.commit()
            conn.close()
        
        if expired_count > 0:
            logger.info(f"Cleaned up {expired_count} expired VMs")
        
        return expired_count

# Global database instance
db = DatabaseManager(config.DATABASE_PATH)
