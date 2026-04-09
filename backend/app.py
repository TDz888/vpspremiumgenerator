# backend/app.py
# Singularity Club - VPS Generator v1.0
# Backend Flask cho Termux / Ubuntu VPS

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
# LƯU TRỮ DỮ LIỆU
# ============================================ #
vms = {}
vm_counter = 0
monitor_threads = {}

# ============================================ #
# HÀM TIỆN ÍCH
# ============================================ #
def generate_username():
    """Tạo username 8 ký tự ngẫu nhiên"""
    chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
    return ''.join(random.choices(chars, k=8))

def generate_password():
    """Tạo mật khẩu mạnh 12-16 ký tự"""
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
    password.extend(random.choices(all_chars, k=random.randint(8, 12)))
    random.shuffle(password)
    return ''.join(password)

def generate_repo_name():
    """Tạo tên repository ngẫu nhiên"""
    return f'vm-{int(time.time())}-{random.randint(1000, 9999)}'

# ============================================ #
# GITHUB API FUNCTIONS
# ============================================ #
def create_github_repo(token, name, description):
    """Tạo repository trên GitHub"""
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }
    data = {
        'name': name,
        'description': description,
        'private': False,
        'auto_init': True
    }
    response = requests.post('https://api.github.com/user/repos', headers=headers, json=data)
    if response.status_code == 201:
        return response.json()
    return None

def create_workflow_file(token, owner, repo, username, password):
    """Tạo workflow file trong repository"""
    workflow_content = f'''name: Create Windows VM

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
      
      - name: Keep Alive
        shell: pwsh
        run: |
          $end = (Get-Date).AddHours(6)
          while ((Get-Date) -lt $end) {{
            Write-Host "VM running... expires in $([math]::Round(($end - (Get-Date)).TotalMinutes)) minutes"
            Start-Sleep -Seconds 300
          }}
'''
    
    encoded = base64.b64encode(workflow_content.encode()).decode()
    url = f'https://api.github.com/repos/{owner}/{repo}/contents/.github/workflows/create-vm.yml'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }
    data = {
        'message': 'Add GitHub Actions workflow',
        'content': encoded,
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
        'inputs': {'tailscale_key': tailscale_key}
    }
    response = requests.post(url, headers=headers, json=data)
    return response.status_code == 204

def get_workflow_logs(token, owner, repo, run_id):
    """Lấy logs từ workflow run"""
    url = f'https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/logs'
    headers = {'Authorization': f'Bearer {token}'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.text
    return ""

def monitor_workflow(vm_id, token, owner, repo):
    """Theo dõi workflow và cập nhật IP"""
    max_attempts = 36  # 6 phút
    attempt = 0
    
    while attempt < max_attempts and vm_id in vms:
        time.sleep(10)
        attempt += 1
        
        try:
            # Lấy danh sách workflow runs
            url = f'https://api.github.com/repos/{owner}/{repo}/actions/runs'
            headers = {'Authorization': f'Bearer {token}'}
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                runs = response.json().get('workflow_runs', [])
                if runs:
                    latest_run = runs[0]
                    status = latest_run.get('status')
                    conclusion = latest_run.get('conclusion')
                    
                    if status == 'completed' and conclusion == 'success':
                        # Lấy logs để tìm IP
                        logs = get_workflow_logs(token, owner, repo, latest_run.get('id'))
                        ip_match = re.search(r'Tailscale IP: (\d+\.\d+\.\d+\.\d+)', logs)
                        
                        if vm_id in vms:
                            vms[vm_id]['status'] = 'running'
                            if ip_match:
                                vms[vm_id]['tailscaleIP'] = ip_match.group(1)
                                vms[vm_id]['novncUrl'] = f'http://{ip_match.group(1)}:6080/vnc.html'
                            break
                    elif status == 'completed' and conclusion != 'success':
                        if vm_id in vms:
                            vms[vm_id]['status'] = 'failed'
                        break
        except:
            pass

# ============================================ #
# API ENDPOINTS
# ============================================ #
@app.route('/api/vps', methods=['GET'])
def get_vms():
    """Lấy danh sách VM"""
    return jsonify({
        'success': True,
        'vms': list(vms.values())
    })

@app.route('/api/vps', methods=['DELETE'])
def delete_vm():
    """Xóa VM"""
    vm_id = request.args.get('id')
    if vm_id and vm_id in vms:
        if vm_id in monitor_threads:
            pass  # Thread sẽ tự dừng
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
        password = generate_password()
    
    try:
        # Lấy thông tin user GitHub
        user_res = requests.get('https://api.github.com/user', headers={
            'Authorization': f'Bearer {github_token}'
        })
        if user_res.status_code != 200:
            return jsonify({'success': False, 'error': 'Token GitHub không hợp lệ'})
        
        user = user_res.json()
        owner = user.get('login')
        
        # Tạo repository
        repo_name = generate_repo_name()
        repo = create_github_repo(github_token, repo_name, f'VM by {username}')
        
        if not repo:
            return jsonify({'success': False, 'error': 'Tạo repository thất bại'})
        
        time.sleep(2)
        
        # Tạo workflow file
        if not create_workflow_file(github_token, owner, repo_name, username, password):
            return jsonify({'success': False, 'error': 'Tạo workflow thất bại'})
        
        time.sleep(2)
        
        # Trigger workflow
        if not trigger_workflow(github_token, owner, repo_name, tailscale_key):
            return jsonify({'success': False, 'error': 'Trigger workflow thất bại'})
        
        vm_counter += 1
        new_vm = {
            'id': str(vm_counter),
            'name': repo_name,
            'owner': owner,
            'username': username,
            'password': password,
            'status': 'creating',
            'repoUrl': repo['html_url'],
            'workflowUrl': f'https://github.com/{owner}/{repo_name}/actions',
            'tailscaleIP': None,
            'novncUrl': None,
            'createdAt': datetime.now().isoformat(),
            'expiresAt': (datetime.now() + timedelta(hours=6)).isoformat()
        }
        
        vms[new_vm['id']] = new_vm
        
        # Bắt đầu monitor
        thread = threading.Thread(target=monitor_workflow, args=(new_vm['id'], github_token, owner, repo_name))
        thread.daemon = True
        thread.start()
        monitor_threads[new_vm['id']] = thread
        
        return jsonify({'success': True, **new_vm})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
