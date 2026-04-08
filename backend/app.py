# backend/app.py
# Singularity Club - Virtual Machine Platform
# Python Flask API cho Ubuntu VPS

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import json
import time
import random
import string
import os
import logging
from datetime import datetime, timedelta
from functools import wraps

# ============================================ #
# CẤU HÌNH
# ============================================ #
app = Flask(__name__, static_folder='../frontend', static_url_path='')
CORS(app)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Lưu trữ VM trong bộ nhớ (có thể thay bằng database sau)
vms = {}
vm_counter = 0

# ============================================ #
# HÀM TIỆN ÍCH
# ============================================ #
def generate_strong_password():
    """Tạo mật khẩu mạnh 23 ký tự"""
    upper = string.ascii_uppercase
    lower = string.ascii_lowercase
    digits = string.digits
    special = '!@#$%^&*'
    all_chars = upper + lower + digits + special
    
    password = [
        random.choice(upper),
        random.choice(lower),
        random.choice(digits),
        random.choice(special)
    ]
    password.extend(random.choices(all_chars, k=19))
    random.shuffle(password)
    return ''.join(password)

def generate_username():
    """Tạo username 8 ký tự"""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=8))

def generate_repo_name():
    """Tạo tên repository ngẫu nhiên"""
    return f'vm-{int(time.time())}-{random.randint(1000, 9999)}'

def create_workflow_content(username, password):
    """Tạo nội dung workflow GitHub Actions"""
    return f'''name: Create Windows VM

on:
  workflow_dispatch:
    inputs:
      tailscale_key:
        description: 'Tailscale Auth Key'
        required: true
        type: string

jobs:
  create-vm:
    runs-on: windows-latest
    timeout-minutes: 480
    
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      
      - name: Install Python
        shell: pwsh
        run: |
          Write-Host "Installing Python..."
          $pythonUrl = "https://www.python.org/ftp/python/3.11.0/python-3.11.0-amd64.exe"
          $installer = "$env:TEMP\\python-installer.exe"
          Invoke-WebRequest -Uri $pythonUrl -OutFile $installer
          Start-Process -FilePath $installer -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait -NoNewWindow
      
      - name: Install Tailscale
        shell: pwsh
        run: |
          Write-Host "Installing Tailscale..."
          $url = "https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe"
          $installer = "$env:TEMP\\tailscale.exe"
          Invoke-WebRequest -Uri $url -OutFile $installer
          Start-Process -FilePath $installer -ArgumentList "/S" -Wait -NoNewWindow
      
      - name: Connect Tailscale
        shell: pwsh
        run: |
          & "C:\\Program Files\\Tailscale\\Tailscale.exe" up --auth-key "${{{{ github.event.inputs.tailscale_key }}}}"
          Start-Sleep -Seconds 15
          $ip = & "C:\\Program Files\\Tailscale\\Tailscale.exe" ip -4
          echo "TAILSCALE_IP=$ip" >> $env:GITHUB_ENV
          Write-Host "Tailscale IP: $ip"
      
      - name: Configure Windows
        shell: pwsh
        run: |
          Set-ItemProperty -Path "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server" -Name "fDenyTSConnections" -Value 0
          Set-ItemProperty -Path "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp" -Name "UserAuthentication" -Value 0
          net user {username} {password} /add
          net localgroup Administrators {username} /add
          net localgroup "Remote Desktop Users" {username} /add
          New-NetFirewallRule -DisplayName "RDP" -Direction Inbound -Protocol TCP -LocalPort 3389 -Action Allow
      
      - name: Setup noVNC
        shell: pwsh
        run: |
          git clone https://github.com/novnc/noVNC.git C:\\novnc
          git clone https://github.com/novnc/websockify.git C:\\websockify
          Start-Process -NoNewWindow -FilePath python -ArgumentList "C:\\websockify\\websockify.py", "--web=C:\\novnc", "6080", "localhost:3389"
          New-NetFirewallRule -DisplayName "noVNC" -Direction Inbound -Protocol TCP -LocalPort 6080 -Action Allow
          Write-Host "noVNC started on port 6080"
      
      - name: Display Info
        shell: pwsh
        run: |
          Write-Host "=================================================="
          Write-Host "WINDOWS VM READY"
          Write-Host "Tailscale IP: $env:TAILSCALE_IP"
          Write-Host "Username: {username}"
          Write-Host "Password: {password}"
          Write-Host "noVNC URL: http://$env:TAILSCALE_IP:6080/vnc.html"
          Write-Host "=================================================="
      
      - name: Keep Alive
        shell: pwsh
        run: |
          $end = (Get-Date).AddHours(6)
          while ((Get-Date) -lt $end) {{
            $remaining = [math]::Round(($end - (Get-Date)).TotalMinutes)
            Write-Host "VM running... expires in $remaining minutes"
            Start-Sleep -Seconds 300
          }}
          Write-Host "VM expired. Shutting down..."
'''

# ============================================ #
# API ENDPOINTS
# ============================================ #

@app.route('/api/vps', methods=['GET'])
def get_vms():
    """Lấy danh sách VM"""
    logger.info(f"GET /api/vps - Total VMs: {len(vms)}")
    return jsonify({
        'success': True,
        'vms': list(vms.values()),
        'stats': {
            'total': len(vms),
            'running': len([v for v in vms.values() if v.get('status') == 'running']),
            'creating': len([v for v in vms.values() if v.get('status') == 'creating'])
        }
    })

@app.route('/api/vps', methods=['DELETE'])
def delete_vm():
    """Xóa VM theo ID"""
    global vms
    vm_id = request.args.get('id')
    
    if not vm_id:
        return jsonify({'success': False, 'error': 'Thiếu ID VM'})
    
    if vm_id in vms:
        del vms[vm_id]
        logger.info(f"DELETE /api/vps - Deleted VM: {vm_id}")
        return jsonify({'success': True, 'message': 'Đã xóa VM'})
    
    return jsonify({'success': False, 'error': 'Không tìm thấy VM'})

@app.route('/api/vps', methods=['POST'])
def create_vm():
    """Tạo VM mới - Gọi GitHub API"""
    global vm_counter, vms
    
    data = request.get_json()
    github_token = data.get('githubToken', '')
    tailscale_key = data.get('tailscaleKey', '')
    username = data.get('vmUsername', '')
    password = data.get('vmPassword', '')
    
    # Validate input
    if not github_token:
        return jsonify({'success': False, 'error': 'Vui lòng nhập GitHub Token'})
    
    if not tailscale_key:
        return jsonify({'success': False, 'error': 'Vui lòng nhập Tailscale Key'})
    
    # Tạo username/password mặc định
    if not username:
        username = generate_username()
    if not password:
        password = generate_strong_password()
    
    logger.info(f"POST /api/vps - Creating VM for user: {username}")
    
    repo_url = None
    workflow_url = None
    status = 'creating'
    error_msg = None
    owner = None
    repo_name = None
    
    headers = {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'Singularity-Club'
    }
    
    try:
        # Bước 1: Xác thực GitHub Token
        logger.info("Step 1: Validating GitHub token...")
        user_res = requests.get('https://api.github.com/user', headers=headers, timeout=30)
        
        if user_res.status_code != 200:
            status = 'failed'
            error_msg = 'Token GitHub không hợp lệ hoặc đã hết hạn'
            logger.error(f"Token validation failed: {user_res.status_code}")
        else:
            user = user_res.json()
            owner = user.get('login')
            logger.info(f"GitHub user: {owner}")
            
            # Bước 2: Tạo repository
            repo_name = generate_repo_name()
            logger.info(f"Step 2: Creating repository: {repo_name}")
            
            create_data = {
                'name': repo_name,
                'description': f'Virtual Machine created by {username}',
                'private': False,
                'auto_init': True
            }
            
            create_res = requests.post(
                'https://api.github.com/user/repos',
                headers=headers,
                json=create_data,
                timeout=30
            )
            
            if create_res.status_code == 201:
                repo = create_res.json()
                repo_url = repo.get('html_url')
                workflow_url = f'https://github.com/{owner}/{repo_name}/actions'
                status = 'running'
                logger.info(f"Repository created: {repo_url}")
                
                # Bước 3: Tạo workflow file (nếu muốn)
                # Có thể thêm logic tạo workflow file ở đây
                
            else:
                status = 'failed'
                error_msg = create_res.json().get('message', 'Không thể tạo repository')
                logger.error(f"Create repo failed: {error_msg}")
                
    except requests.exceptions.Timeout:
        status = 'failed'
        error_msg = 'Timeout khi kết nối GitHub API'
        logger.error("GitHub API timeout")
    except Exception as e:
        status = 'failed'
        error_msg = str(e)
        logger.error(f"Unexpected error: {e}")
    
    # Tạo VM record
    vm_counter += 1
    new_vm = {
        'id': str(vm_counter),
        'name': repo_name or f'vm-{int(time.time())}',
        'owner': owner,
        'username': username,
        'password': password,
        'status': status,
        'repoUrl': repo_url,
        'workflowUrl': workflow_url,
        'error': error_msg,
        'createdAt': datetime.now().isoformat(),
        'expiresAt': (datetime.now() + timedelta(hours=6)).isoformat()
    }
    
    vms[new_vm['id']] = new_vm
    
    if status == 'running':
        logger.info(f"VM created successfully: {username}")
        return jsonify({
            'success': True,
            **new_vm,
            'message': f'✅ VM "{username}" đã được tạo thành công!'
        })
    else:
        logger.error(f"VM creation failed: {error_msg}")
        return jsonify({
            'success': False,
            'error': error_msg,
            **new_vm
        })

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'vms_count': len(vms)
    })

@app.route('/')
def serve_frontend():
    """Phục vụ file frontend"""
    return send_from_directory('../frontend', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    """Phục vụ static files"""
    return send_from_directory('../frontend', path)

# ============================================ #
# MAIN
# ============================================ #
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
