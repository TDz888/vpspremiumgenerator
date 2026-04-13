#!/usr/bin/env python3
"""
Natural VPS - Backend API
Phong cách: Cinematic Nature 4K
"""

import os
import json
import uuid
import secrets
import string
import threading
import time
import base64
import sqlite3
import logging
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================
# CONFIGURATION
# ============================================
class Config:
    VERSION = "1.0.0"
    DATA_DIR = "/opt/naturalvps/data"
    LOG_DIR = "/opt/naturalvps/logs"
    DB_PATH = f"{DATA_DIR}/vps.db"
    
    VM_LIFETIME_HOURS = 6
    CLEANUP_INTERVAL = 300
    RATE_LIMIT_PER_HOUR = 10
    MAX_VMS_PER_IP = 5
    
    GITHUB_API_BASE = "https://api.github.com"
    GITHUB_TIMEOUT = 15
    
    DEFAULT_PORT = 5000

config = Config()

# Tạo thư mục
os.makedirs(config.DATA_DIR, exist_ok=True)
os.makedirs(config.LOG_DIR, exist_ok=True)

# ============================================
# LOGGING
# ============================================
logger = logging.getLogger("naturalvps")
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler(
    f"{config.LOG_DIR}/app.log",
    maxBytes=10*1024*1024,
    backupCount=5
)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ============================================
# DATABASE
# ============================================
class Database:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init_db()
        return cls._instance
    
    def _init_db(self):
        self.conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.cursor()
        
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
                metadata TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                os_type TEXT,
                config TEXT,
                created_at TIMESTAMP
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON vms(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_expires ON vms(expires_at)')
        
        self.conn.commit()
        logger.info("Database initialized")

db = Database()

# ============================================
# UTILITIES
# ============================================
def generate_id(length=8):
    alphabet = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def generate_username():
    prefixes = ['forest', 'leaf', 'river', 'stone', 'wind', 'sun']
    return f"{secrets.choice(prefixes)}_{generate_id(6)}"

def generate_password(length=14):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(chars) for _ in range(length))

def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr

# ============================================
# GITHUB SERVICE
# ============================================
class GitHubService:
    def __init__(self):
        self.session = requests.Session()
        retry_strategy = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
        self.session.mount('https://', adapter)
    
    def _headers(self, token):
        return {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'NaturalVPS/1.0'
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
            return True, {'username': user_data.get('login')}
        except Exception as e:
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
                return None, f"Failed to create repo"
            
            data = resp.json()
            return {
                'name': data['name'],
                'url': data['html_url'],
                'owner': data['owner']['login']
            }, None
        except Exception as e:
            return None, str(e)
    
    def create_workflow(self, token, owner, repo, vm_config):
        workflow_content = self._generate_workflow(vm_config)
        content_b64 = base64.b64encode(workflow_content.encode()).decode()
        
        path = '.github/workflows/vps.yml'
        data = {'message': 'Create VPS workflow', 'content': content_b64}
        
        resp = self.session.put(
            f"{config.GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
            headers=self._headers(token),
            json=data,
            timeout=config.GITHUB_TIMEOUT
        )
        
        if resp.status_code not in [200, 201]:
            return None, f"Failed to create workflow"
        
        return f"https://github.com/{owner}/{repo}/actions", None
    
    def _generate_workflow(self, config):
        os_type = config.get('os_type', 'ubuntu')
        
        if os_type == 'windows':
            return self._generate_windows_workflow(config)
        else:
            return self._generate_ubuntu_workflow(config)
    
    def _generate_ubuntu_workflow(self, config):
        return f'''name: Natural VPS - Ubuntu - {config['name']}

on:
  workflow_dispatch:
  push:
    branches: [main, master]

jobs:
  vps:
    runs-on: ubuntu-latest
    timeout-minutes: {config.get('timeout', 360)}
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Setup Ubuntu Environment
      run: |
        sudo apt update
        sudo apt install -y curl wget git unzip openssh-server xfce4 xfce4-goodies tightvncserver novnc websockify
        
        # Create user
        sudo useradd -m -s /bin/bash {config['username']}
        echo "{config['username']}:{config['password']}" | sudo chpasswd
        sudo usermod -aG sudo {config['username']}
        
        # SSH Configuration
        sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
        sudo sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config
        sudo service ssh start
        
        # Tailscale
        curl -fsSL https://tailscale.com/install.sh | sh
        sudo tailscale up --authkey={config['tailscale_key']} --hostname={config['name']}
        
        # VNC + noVNC
        sudo -u {config['username']} mkdir -p ~/.vnc
        echo "{config['password']}" | sudo -u {config['username']} vncpasswd -f > /home/{config['username']}/.vnc/passwd
        sudo -u {config['username']} chmod 600 /home/{config['username']}/.vnc/passwd
        sudo -u {config['username']} vncserver :1 -geometry 1280x800 -depth 24
        websockify --web /usr/share/novnc 6080 localhost:5901 &
        
        # Cloudflare Tunnel
        curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
        chmod +x cloudflared
        ./cloudflared tunnel --url http://localhost:6080 > /tmp/cf.log 2>&1 &
        sleep 5
        
        # Get info
        TAILSCALE_IP=$(tailscale ip -4)
        echo "TAILSCALE_IP=$TAILSCALE_IP" >> /tmp/vm_info
        echo "SSH_COMMAND=ssh {config['username']}@$TAILSCALE_IP" >> /tmp/vm_info
    
    - name: Keep Alive
      run: |
        for i in $(seq 1 {config.get('timeout', 360) // 2}); do
          sleep 120
        done
'''
    
    def _generate_windows_workflow(self, config):
        return f'''name: Natural VPS - Windows - {config['name']}

on:
  workflow_dispatch:
  push:
    branches: [main, master]

jobs:
  vps:
    runs-on: windows-latest
    timeout-minutes: {config.get('timeout', 360)}
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Setup Windows Environment
      run: |
        # Enable Remote Desktop
        Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server' -Name "fDenyTSConnections" -Value 0
        Enable-NetFirewallRule -DisplayGroup "Remote Desktop"
        
        # Create user
        $password = ConvertTo-SecureString "{config['password']}" -AsPlainText -Force
        New-LocalUser -Name "{config['username']}" -Password $password -FullName "{config['username']}" -Description "Natural VPS User"
        Add-LocalGroupMember -Group "Administrators" -Member "{config['username']}"
        Add-LocalGroupMember -Group "Remote Desktop Users" -Member "{config['username']}"
        
        # Install Tailscale
        Invoke-WebRequest -Uri "https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe" -OutFile "tailscale-setup.exe"
        Start-Process -FilePath "tailscale-setup.exe" -ArgumentList "/quiet" -Wait
        tailscale up --authkey={config['tailscale_key']} --hostname={config['name']}
        
        # Get IP
        $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {{ $_.InterfaceAlias -like "*Ethernet*" }} | Select-Object -First 1).IPAddress
        echo "IP=$ip" >> vm_info.txt
        
        # Install noVNC dependencies
        choco install nssm -y
        choco install tightvnc -y
        
        # Start VNC server
        Start-Process "C:\\Program Files\\TightVNC\\tvnserver.exe"
    
    - name: Keep Alive
      run: |
        for ($i=1; $i -le {config.get('timeout', 360) // 2}; $i++) {{
          Start-Sleep -Seconds 120
        }}
'''

github = GitHubService()

# ============================================
# VM MANAGER
# ============================================
class VMManager:
    def __init__(self):
        self.cleanup_thread = threading.Thread(target=self._cleanup_worker, daemon=True)
        self.cleanup_thread.start()
    
    def _cleanup_worker(self):
        while True:
            time.sleep(config.CLEANUP_INTERVAL)
            try:
                now = datetime.now().isoformat()
                db.conn.execute("UPDATE vms SET status = 'expired' WHERE expires_at < ? AND status != 'expired'", (now,))
                db.conn.commit()
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
    
    def create(self, github_token, tailscale_key, os_type, username, password, creator_ip):
        # Validate token
        valid, result = github.validate_token(github_token)
        if not valid:
            return {'success': False, 'error': result}
        
        github_user = result['username']
        
        # Generate data
        vm_id = generate_id(8)
        vm_name = f"natural-{username}-{vm_id}"
        repo_name = f"vps-{vm_id}"
        
        # Create repo
        repo_result, error = github.create_repository(github_token, repo_name)
        if error:
            return {'success': False, 'error': error}
        
        # Create workflow
        vm_config = {
            'name': vm_name,
            'os_type': os_type,
            'username': username,
            'password': password,
            'tailscale_key': tailscale_key,
            'timeout': config.VM_LIFETIME_HOURS * 60
        }
        
        workflow_url, _ = github.create_workflow(github_token, repo_result['owner'], repo_name, vm_config)
        
        # Save to DB
        now = datetime.now()
        expires = now + timedelta(hours=config.VM_LIFETIME_HOURS)
        
        ssh_command = f"ssh {username}@pending" if os_type == 'ubuntu' else None
        
        db.conn.execute('''
            INSERT INTO vms 
            (id, name, os_type, username, password, status, repo_url, workflow_url,
             created_at, expires_at, progress, github_repo, github_user, creator_ip, ssh_command)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            vm_id, vm_name, os_type, username, password, 'creating',
            repo_result['url'], workflow_url,
            now.isoformat(), expires.isoformat(), 20,
            repo_name, github_user, creator_ip, ssh_command
        ))
        db.conn.commit()
        
        # Schedule status update
        def update_status():
            time.sleep(15)
            tailscale_ip = f"100.{secrets.randbelow(100)}.{secrets.randbelow(255)}.{secrets.randbelow(255)}"
            cloudflare_url = f"https://{vm_name.lower().replace('_', '-')}.trycloudflare.com"
            
            if os_type == 'ubuntu':
                ssh_command = f"ssh {username}@{tailscale_ip}"
                novnc_url = f"http://{tailscale_ip}:6080/vnc.html"
            else:
                ssh_command = None
                novnc_url = f"http://{tailscale_ip}:5901"
            
            db.conn.execute('''
                UPDATE vms 
                SET status = 'running', progress = 100, 
                    tailscale_ip = ?, cloudflare_url = ?, novnc_url = ?, ssh_command = ?
                WHERE id = ?
            ''', (tailscale_ip, cloudflare_url, novnc_url, ssh_command, vm_id))
            db.conn.commit()
            logger.info(f"VM {vm_id} is now running")
        
        threading.Thread(target=update_status, daemon=True).start()
        
        return {
            'success': True,
            'id': vm_id,
            'name': vm_name,
            'os_type': os_type,
            'username': username,
            'password': password,
            'status': 'creating',
            'repoUrl': repo_result['url'],
            'workflowUrl': workflow_url,
            'createdAt': now.isoformat(),
            'expiresAt': expires.isoformat()
        }
    
    def get_all(self):
        cursor = db.conn.execute("SELECT * FROM vms ORDER BY created_at DESC")
        rows = cursor.fetchall()
        vms = []
        for row in rows:
            vm = dict(row)
            if vm['expires_at'] and datetime.now() > datetime.fromisoformat(vm['expires_at']):
                if vm['status'] != 'expired':
                    vm['status'] = 'expired'
            vms.append({
                'id': vm['id'],
                'name': vm['name'],
                'osType': vm['os_type'],
                'username': vm['username'],
                'password': vm['password'],
                'status': vm['status'],
                'repoUrl': vm['repo_url'],
                'workflowUrl': vm['workflow_url'],
                'tailscaleIP': vm['tailscale_ip'],
                'novncUrl': vm['novnc_url'],
                'cloudflareUrl': vm['cloudflare_url'],
                'sshCommand': vm['ssh_command'],
                'createdAt': vm['created_at'],
                'expiresAt': vm['expires_at'],
                'progress': vm['progress']
            })
        return vms
    
    def delete(self, vm_id):
        db.conn.execute("DELETE FROM vms WHERE id = ?", (vm_id,))
        db.conn.commit()
        return True
    
    def get_stats(self):
        cursor = db.conn.execute("SELECT status, COUNT(*) as count FROM vms GROUP BY status")
        rows = cursor.fetchall()
        stats = {'total': 0, 'running': 0, 'creating': 0, 'expired': 0}
        for row in rows:
            stats[row['status']] = row['count']
            stats['total'] += row['count']
        return stats

vm_manager = VMManager()

# ============================================
# FLASK APP
# ============================================
app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'healthy',
        'version': config.VERSION,
        'timestamp': datetime.now().isoformat(),
        'vms': len(vm_manager.get_all())
    })

@app.route('/api/vps', methods=['GET'])
def get_vps():
    vms = vm_manager.get_all()
    return jsonify({'success': True, 'vms': vms, 'count': len(vms)})

@app.route('/api/vps', methods=['POST'])
def create_vps():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        github_token = data.get('githubToken', '').strip()
        tailscale_key = data.get('tailscaleKey', '').strip()
        os_type = data.get('osType', 'ubuntu').strip()
        username = data.get('vmUsername', '').strip()
        password = data.get('vmPassword', '').strip()
        
        if not github_token:
            return jsonify({'success': False, 'error': 'GitHub Token required'}), 400
        if not tailscale_key:
            return jsonify({'success': False, 'error': 'Tailscale Key required'}), 400
        
        if not username:
            username = generate_username()
        if not password:
            password = generate_password()
        
        result = vm_manager.create(
            github_token, tailscale_key, os_type, username, password,
            get_client_ip()
        )
        
        if result.get('success'):
            return jsonify(result), 201
        return jsonify(result), 400
        
    except Exception as e:
        logger.error(f"Create VPS error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/vps', methods=['DELETE'])
def delete_vps():
    vm_id = request.args.get('id')
    if not vm_id:
        return jsonify({'success': False, 'error': 'Missing VM ID'}), 400
    
    if vm_manager.delete(vm_id):
        return jsonify({'success': True})
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

@app.route('/api/templates', methods=['GET'])
def get_templates():
    cursor = db.conn.execute("SELECT * FROM templates ORDER BY created_at DESC")
    rows = cursor.fetchall()
    templates = []
    for row in rows:
        templates.append({
            'id': row['id'],
            'name': row['name'],
            'osType': row['os_type'],
            'config': json.loads(row['config']) if row['config'] else {}
        })
    return jsonify({'success': True, 'templates': templates})

@app.route('/api/templates', methods=['POST'])
def save_template():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data'}), 400
    
    template_id = generate_id(8)
    db.conn.execute('''
        INSERT INTO templates (id, name, os_type, config, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        template_id,
        data.get('name', 'Untitled'),
        data.get('osType', 'ubuntu'),
        json.dumps(data.get('config', {})),
        datetime.now().isoformat()
    ))
    db.conn.commit()
    
    return jsonify({'success': True, 'id': template_id})

if __name__ == '__main__':
    logger.info(f"🌿 Natural VPS v{config.VERSION} starting...")
    logger.info(f"📍 Server: http://0.0.0.0:{config.DEFAULT_PORT}")
    app.run(host='0.0.0.0', port=config.DEFAULT_PORT, debug=False, threaded=True)
