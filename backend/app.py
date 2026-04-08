# backend/app.py
# Singularity Club - VPS Premium Generator v1.0 (beta-version)
# Nâng cấp: Tạo workflow, trigger Actions, monitor logs

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import json
import time
import random
import string
import base64
import re
import threading
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# ============================================ #
# CẤU HÌNH VÀ LƯU TRỮ
# ============================================ #
vms = {}
vm_counter = 0
monitor_threads = {}

# ============================================ #
# HÀM TIỆN ÍCH
# ============================================ #
def generate_strong_password():
    """Tạo mật khẩu mạnh 23 ký tự"""
    upper = 'ABCDEFGHJKLMNPQRSTUVWXYZ'
    lower = 'abcdefghijkmnopqrstuvwxyz'
    numbers = '0123456789'
    special = '!@#$%^&*'
    all_chars = upper + lower + numbers + special
    
    password = [
        random.choice(upper),
        random.choice(lower),
        random.choice(numbers),
        random.choice(special)
    ]
    password.extend(random.choices(all_chars, k=19))
    random.shuffle(password)
    return ''.join(password)

def generate_username():
    """Tạo username 8 ký tự"""
    chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
    return ''.join(random.choices(chars, k=8))

def generate_repo_name():
    """Tạo tên repository ngẫu nhiên"""
    return f'vm-{int(time.time())}-{random.randint(1000, 9999)}'

# ============================================ #
# TẠO WORKFLOW YML
# ============================================ #
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
      
      - name: Configure Windows RDP
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
      
      - name: Keep VM Alive
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

def create_workflow_file(token, owner, repo, username, password):
    """Tạo workflow file trong repository"""
    workflow_content = create_workflow_content(username, password)
    encoded_content = base64.b64encode(workflow_content.encode()).decode()
    
    url = f'https://api.github.com/repos/{owner}/{repo}/contents/.github/workflows/create-vm.yml'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }
    data = {
        'message': 'Add GitHub Actions workflow for VM creation',
        'content': encoded_content,
        'branch': 'main'
    }
    
    response = requests.put(url, headers=headers, json=data)
    return response.status_code == 201

def trigger_workflow(token, owner, repo, tailscale_key):
    """Trigger GitHub Actions workflow"""
    url = f'https://api.github.com/repos/{owner}/{repo}/actions/workflows/create-vm.yml/dispatches'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }
    data = {
        'ref': 'main',
        'inputs': {
            'tailscale_key': tailscale_key
        }
    }
    
    response = requests.post(url, headers=headers, json=data)
    return response.status_code == 204

def get_workflow_runs(token, owner, repo):
    """Lấy thông tin workflow runs"""
    url = f'https://api.github.com/repos/{owner}/{repo}/actions/runs'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get('workflow_runs', [])
    return []

def get_workflow_logs(token, owner, repo, run_id):
    """Lấy logs của workflow run"""
    url = f'https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/logs'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.text
    return ""

# ============================================ #
# MONITOR WORKFLOW (LẤY IP VÀ noVNC)
# ============================================ #
def monitor_workflow(vm_id, token, owner, repo, run_id):
    """Theo dõi workflow và lấy thông tin IP/noVNC"""
    max_attempts = 36  # 6 phút (10s * 36)
    attempt = 0
    
    while attempt < max_attempts:
        time.sleep(10)
        attempt += 1
        
        if vm_id not in vms:
            break
            
        # Lấy thông tin workflow run
        runs = get_workflow_runs(token, owner, repo)
        if not runs:
            continue
            
        current_run = runs[0]
        status = current_run.get('status')
        conclusion = current_run.get('conclusion')
        
        if status == 'completed':
            if conclusion == 'success':
                # Lấy logs để tìm IP
                logs = get_workflow_logs(token, owner, repo, current_run.get('id'))
                
                # Tìm Tailscale IP
                ip_match = re.search(r'Tailscale IP: (\d+\.\d+\.\d+\.\d+)', logs)
                if ip_match:
                    tailscale_ip = ip_match.group(1)
                    vms[vm_id]['tailscaleIP'] = tailscale_ip
                    vms[vm_id]['novncUrl'] = f'http://{tailscale_ip}:6080/vnc.html'
                
                vms[vm_id]['status'] = 'running'
                vms[vm_id]['completedAt'] = datetime.now().isoformat()
            else:
                vms[vm_id]['status'] = 'failed'
                vms[vm_id]['error'] = f'Workflow {conclusion}'
            break
        elif status == 'in_progress':
            vms[vm_id]['status'] = 'creating'
    
    if vm_id in monitor_threads:
        del monitor_threads[vm_id]

# ============================================ #
# API ENDPOINTS
# ============================================ #
@app.route('/api/vps', methods=['GET'])
def get_vms():
    """Lấy danh sách VM"""
    return jsonify({
        'success': True,
        'vms': list(vms.values()),
        'stats': {
            'total': len(vms),
            'running': len([v for v in vms.values() if v.get('status') == 'running'])
        }
    })

@app.route('/api/vps', methods=['DELETE'])
def delete_vm():
    """Xóa VM"""
    vm_id = request.args.get('id')
    if vm_id and vm_id in vms:
        del vms[vm_id]
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Không tìm thấy VM'})

@app.route('/api/vps', methods=['POST'])
def create_vm():
    """Tạo VM mới"""
    global vm_counter
    
    data = request.get_json()
    github_token = data.get('githubToken', '')
    tailscale_key = data.get('tailscaleKey', '')
    username = data.get('vmUsername', '')
    password = data.get('vmPassword', '')
    
    if not github_token:
        return jsonify({'success': False, 'error': 'Vui lòng nhập GitHub Token'})
    if not tailscale_key:
        return jsonify({'success': False, 'error': 'Vui lòng nhập Tailscale Key'})
    
    if not username:
        username = generate_username()
    if not password:
        password = generate_strong_password()
    
    headers = {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'Singularity-Club'
    }
    
    try:
        # Bước 1: Xác thực token
        user_res = requests.get('https://api.github.com/user', headers=headers)
        if user_res.status_code != 200:
            return jsonify({'success': False, 'error': 'Token GitHub không hợp lệ'})
        
        user = user_res.json()
        owner = user.get('login')
        
        # Bước 2: Tạo repository
        repo_name = generate_repo_name()
        create_data = {
            'name': repo_name,
            'description': f'VM by {username}',
            'private': False,
            'auto_init': True
        }
        create_res = requests.post('https://api.github.com/user/repos', headers=headers, json=create_data)
        
        if create_res.status_code != 201:
            return jsonify({'success': False, 'error': 'Tạo repository thất bại'})
        
        repo = create_res.json()
        repo_url = repo.get('html_url')
        
        time.sleep(3)
        
        # Bước 3: Tạo workflow file
        if not create_workflow_file(github_token, owner, repo_name, username, password):
            return jsonify({'success': False, 'error': 'Tạo workflow thất bại'})
        
        time.sleep(2)
        
        # Bước 4: Trigger workflow
        if not trigger_workflow(github_token, owner, repo_name, tailscale_key):
            return jsonify({'success': False, 'error': 'Trigger workflow thất bại'})
        
        time.sleep(3)
        
        # Lấy run ID
        runs = get_workflow_runs(github_token, owner, repo_name)
        run_id = runs[0].get('id') if runs else None
        
        # Tạo VM record
        vm_counter += 1
        new_vm = {
            'id': str(vm_counter),
            'name': repo_name,
            'owner': owner,
            'username': username,
            'password': password,
            'status': 'creating',
            'repoUrl': repo_url,
            'workflowUrl': f'https://github.com/{owner}/{repo_name}/actions',
            'runId': run_id,
            'tailscaleIP': None,
            'novncUrl': None,
            'createdAt': datetime.now().isoformat(),
            'expiresAt': (datetime.now() + timedelta(hours=6)).isoformat()
        }
        
        vms[new_vm['id']] = new_vm
        
        # Bắt đầu monitor
        if run_id:
            thread = threading.Thread(target=monitor_workflow, args=(new_vm['id'], github_token, owner, repo_name, run_id))
            thread.daemon = True
            thread.start()
            monitor_threads[new_vm['id']] = thread
        
        return jsonify({'success': True, **new_vm})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'vms_count': len(vms)
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
