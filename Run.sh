#!/bin/bash
# run.sh - Chạy toàn bộ dự án Singularity Club
# Dùng cho Ubuntu / Termux

set -e

# Màu sắc
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}=========================================="
echo "🚀 SINGULARITY CLUB - START SERVER"
echo "==========================================${NC}"

# ============================================ #
# KIỂM TRA VÀ TẠO THƯ MỤC
# ============================================ #
cd ~
mkdir -p singularity-vm/backend
mkdir -p singularity-vm/frontend
cd singularity-vm

# ============================================ #
# TẠO BACKEND (app.py)
# ============================================ #
echo -e "${YELLOW}📝 Tạo backend...${NC}"
cat > backend/app.py << 'EOF'
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import time
import random
import string
import threading
from datetime import datetime, timedelta

app = Flask(__name__, static_folder='../frontend', static_url_path='')
CORS(app)

vms = {}
vm_counter = 0

def generate_username():
    chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
    return ''.join(random.choices(chars, k=8))

def generate_password():
    upper = 'ABCDEFGHJKLMNPQRSTUVWXYZ'
    lower = 'abcdefghijkmnopqrstuvwxyz'
    numbers = '0123456789'
    special = '!@#$%^&*'
    all_chars = upper + lower + numbers + special
    password = [random.choice(upper), random.choice(lower), random.choice(numbers), random.choice(special)]
    password.extend(random.choices(all_chars, k=random.randint(8, 12)))
    random.shuffle(password)
    return ''.join(password)

@app.route('/')
def index():
    return send_from_directory('../frontend', 'index.html')

@app.route('/api/vps', methods=['GET'])
def get_vms():
    return jsonify({'success': True, 'vms': list(vms.values())})

@app.route('/api/vps', methods=['DELETE'])
def delete_vm():
    vm_id = request.args.get('id')
    if vm_id and vm_id in vms:
        del vms[vm_id]
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Không tìm thấy VM'})

@app.route('/api/vps', methods=['POST'])
def create_vm():
    global vm_counter
    data = request.get_json()
    github_token = data.get('githubToken', '')
    tailscale_key = data.get('tailscaleKey', '')
    username = data.get('vmUsername', '') or generate_username()
    password = data.get('vmPassword', '') or generate_password()
    
    if not github_token:
        return jsonify({'success': False, 'error': 'Vui lòng nhập GitHub Token'})
    if not tailscale_key:
        return jsonify({'success': False, 'error': 'Vui lòng nhập Tailscale Key'})
    
    vm_counter += 1
    new_vm = {
        'id': str(vm_counter),
        'name': f'vm-{int(time.time())}-{random.randint(1000,9999)}',
        'username': username,
        'password': password,
        'status': 'creating',
        'tailscaleIP': None,
        'novncUrl': None,
        'repoUrl': None,
        'workflowUrl': None,
        'createdAt': datetime.now().isoformat(),
        'expiresAt': (datetime.now() + timedelta(hours=6)).isoformat()
    }
    vms[new_vm['id']] = new_vm
    
    def simulate():
        time.sleep(5)
        if new_vm['id'] in vms:
            new_vm['status'] = 'running'
            new_vm['tailscaleIP'] = f'100.64.{random.randint(1,255)}.{random.randint(1,255)}'
            new_vm['novncUrl'] = f'http://{new_vm["tailscaleIP"]}:6080/vnc.html'
            new_vm['repoUrl'] = 'https://github.com/demo/vm-repo'
            new_vm['workflowUrl'] = 'https://github.com/demo/vm-repo/actions'
    
    threading.Thread(target=simulate).start()
    
    return jsonify({'success': True, **new_vm, 'message': f'✅ VM "{username}" đang được tạo!'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
EOF

# ============================================ #
# TẠO FRONTEND (index.html)
# ============================================ #
echo -e "${YELLOW}🎨 Tạo frontend...${NC}"
cat > frontend/index.html << 'HTMLEOF'
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Singularity Club | VPS Generator</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        :root {
            --primary: #8b5cf6;
            --secondary: #ec4899;
            --success: #10b981;
            --warning: #f59e0b;
            --error: #ef4444;
            --bg: #0f0f1a;
            --card: rgba(30,30,50,0.8);
            --border: rgba(255,255,255,0.08);
            --text: #f1f5f9;
            --text-muted: #94a3b8;
        }
        
        body { background: var(--bg); font-family: 'Inter', sans-serif; color: var(--text); min-height: 100vh; }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        
        .header { text-align: center; margin-bottom: 30px; }
        .logo { font-size: 2rem; font-weight: 700; background: linear-gradient(135deg, #fff, var(--primary), var(--secondary)); -webkit-background-clip: text; background-clip: text; color: transparent; }
        .subtitle { color: var(--text-muted); font-size: 0.8rem; margin-top: 6px; }
        .badge-container { display: flex; justify-content: center; gap: 10px; margin-top: 15px; flex-wrap: wrap; }
        .badge { background: var(--card); border: 1px solid var(--border); border-radius: 50px; padding: 5px 12px; font-size: 0.7rem; }
        
        .stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 30px; }
        @media (max-width: 768px) { .stats-grid { grid-template-columns: repeat(2, 1fr); } }
        .stat-card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 16px; transition: all 0.2s; }
        .stat-card:hover { border-color: var(--primary); transform: translateY(-2px); }
        .stat-label { font-size: 0.7rem; color: var(--text-muted); margin-bottom: 6px; }
        .stat-value { font-size: 1.8rem; font-weight: 700; background: linear-gradient(135deg, var(--primary), var(--secondary)); -webkit-background-clip: text; background-clip: text; color: transparent; }
        
        .two-columns { display: grid; grid-template-columns: 1fr 1.2fr; gap: 24px; }
        @media (max-width: 900px) { .two-columns { grid-template-columns: 1fr; } }
        
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 20px; padding: 24px; backdrop-filter: blur(10px); }
        .card-title { font-size: 1.1rem; font-weight: 600; margin-bottom: 20px; display: flex; align-items: center; gap: 8px; }
        
        .input-group { margin-bottom: 18px; }
        .input-label { font-size: 0.75rem; color: var(--text-muted); margin-bottom: 6px; display: block; }
        .input-field { width: 100%; background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; color: var(--text); font-size: 0.85rem; }
        .input-field:focus { outline: none; border-color: var(--primary); }
        .input-row { display: flex; gap: 10px; align-items: center; }
        .input-row .input-group { flex: 1; margin-bottom: 0; }
        .random-btn { background: rgba(139,92,246,0.15); border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px; color: var(--primary); cursor: pointer; font-size: 0.75rem; white-space: nowrap; display: inline-flex; align-items: center; gap: 6px; }
        .random-btn:hover { background: rgba(139,92,246,0.3); }
        
        .btn { padding: 12px 20px; border-radius: 12px; font-weight: 600; font-size: 0.85rem; cursor: pointer; border: none; display: inline-flex; align-items: center; justify-content: center; gap: 8px; width: 100%; margin-top: 10px; }
        .btn-primary { background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }
        .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 8px 20px rgba(139,92,246,0.3); }
        .btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
        
        .quick-actions { display: flex; gap: 10px; margin-top: 20px; flex-wrap: wrap; }
        .quick-btn { flex: 1; background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 10px; padding: 8px 10px; font-size: 0.7rem; cursor: pointer; text-align: center; display: inline-flex; align-items: center; justify-content: center; gap: 5px; }
        .quick-btn:hover { background: rgba(139,92,246,0.15); border-color: var(--primary); }
        
        .progress-container { margin-top: 18px; display: none; }
        .progress-steps { display: flex; justify-content: space-between; margin-bottom: 10px; gap: 6px; }
        .progress-step { flex: 1; text-align: center; font-size: 0.55rem; opacity: 0.4; padding: 4px; border-radius: 8px; }
        .progress-step i { display: block; margin-bottom: 3px; font-size: 0.7rem; }
        .progress-step.active { opacity: 1; color: var(--primary); background: rgba(139,92,246,0.15); }
        .progress-step.completed { opacity: 1; color: var(--success); }
        .progress-bar { background: rgba(0,0,0,0.3); border-radius: 20px; height: 4px; overflow: hidden; }
        .progress-fill { background: linear-gradient(90deg, var(--primary), var(--secondary)); width: 0%; height: 100%; transition: width 0.3s; }
        .progress-text { font-size: 0.65rem; text-align: center; margin-top: 8px; color: var(--text-muted); }
        
        .vm-controls { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
        .vm-search { flex: 1; background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 30px; padding: 8px 14px; color: var(--text); font-size: 0.8rem; }
        .vm-filter, .vm-sort { background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 30px; padding: 8px 14px; color: var(--text); font-size: 0.75rem; cursor: pointer; }
        .vm-count { background: rgba(139,92,246,0.15); border-radius: 30px; padding: 8px 14px; font-size: 0.75rem; display: flex; align-items: center; gap: 6px; }
        
        .vm-list { display: flex; flex-direction: column; gap: 12px; }
        .vm-item { background: rgba(0,0,0,0.25); border-radius: 16px; border: 1px solid var(--border); overflow: hidden; }
        .vm-item:hover { border-color: var(--primary); background: rgba(0,0,0,0.35); }
        .vm-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; cursor: pointer; }
        .vm-info { display: flex; align-items: center; gap: 12px; }
        .vm-icon { width: 40px; height: 40px; background: linear-gradient(135deg, rgba(139,92,246,0.2), rgba(236,72,153,0.2)); border-radius: 12px; display: flex; align-items: center; justify-content: center; }
        .vm-name { font-weight: 600; font-size: 0.9rem; }
        .vm-time { font-size: 0.6rem; color: var(--text-muted); margin-top: 3px; }
        .vm-status { font-size: 0.65rem; padding: 3px 10px; border-radius: 50px; }
        .status-creating { background: rgba(245,158,11,0.2); color: var(--warning); }
        .status-running { background: rgba(16,185,129,0.2); color: var(--success); }
        .vm-expand-icon { transition: transform 0.2s; }
        .vm-item.open .vm-expand-icon { transform: rotate(180deg); }
        .vm-detail { max-height: 0; overflow: hidden; transition: max-height 0.3s; border-top: 1px solid transparent; }
        .vm-item.open .vm-detail { max-height: 350px; border-top-color: var(--border); padding: 16px; }
        
        .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
        @media (max-width: 640px) { .info-grid { grid-template-columns: 1fr; } }
        .info-box { background: rgba(0,0,0,0.2); border-radius: 12px; padding: 12px; }
        .info-title { font-size: 0.65rem; text-transform: uppercase; color: var(--text-muted); margin-bottom: 10px; }
        .info-value { font-family: monospace; font-size: 0.8rem; display: flex; justify-content: space-between; align-items: center; gap: 6px; }
        .copy-btn { background: rgba(139,92,246,0.2); border: none; color: var(--primary); padding: 4px 8px; border-radius: 6px; font-size: 0.65rem; cursor: pointer; }
        .copy-btn:hover { background: rgba(139,92,246,0.4); }
        
        .vm-links { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
        .vm-link { background: rgba(59,130,246,0.15); padding: 6px 12px; border-radius: 8px; font-size: 0.7rem; text-decoration: none; color: #3b82f6; display: inline-flex; align-items: center; gap: 5px; }
        .vm-delete { background: rgba(239,68,68,0.15); color: var(--error); padding: 6px 12px; border-radius: 8px; font-size: 0.7rem; cursor: pointer; border: none; display: inline-flex; align-items: center; gap: 5px; }
        
        .debug-panel { background: var(--card); border: 1px solid var(--border); border-radius: 16px; margin-top: 24px; overflow: hidden; }
        .debug-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: rgba(0,0,0,0.2); cursor: pointer; }
        .debug-title { font-size: 0.8rem; font-weight: 500; display: flex; align-items: center; gap: 8px; }
        .debug-content { padding: 12px 16px; max-height: 200px; overflow-y: auto; font-family: monospace; font-size: 0.65rem; }
        .debug-content.hidden { display: none; }
        .debug-log { padding: 4px 0; border-bottom: 1px solid var(--border); display: flex; gap: 10px; }
        .debug-time { color: var(--text-muted); min-width: 65px; }
        .debug-success { color: var(--success); }
        .debug-error { color: var(--error); }
        .debug-info { color: #3b82f6; }
        
        .toast { position: fixed; bottom: 20px; right: 20px; background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 10px 16px; transform: translateX(400px); transition: transform 0.3s; z-index: 1000; border-left: 3px solid var(--primary); }
        .toast.show { transform: translateX(0); }
        .empty-state { text-align: center; padding: 40px; color: var(--text-muted); }
        .spinner { width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.3); border-top-color: white; border-radius: 50%; animation: spin 0.6s linear infinite; display: inline-block; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .footer { text-align: center; padding: 20px; margin-top: 24px; border-top: 1px solid var(--border); color: var(--text-muted); font-size: 0.65rem; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo"><i class="fas fa-infinity"></i> SINGULARITY CLUB</div>
            <div class="subtitle">Virtual Machine Platform • Powered by GitHub Actions</div>
            <div class="badge-container">
                <div class="badge"><i class="fab fa-github"></i> GitHub Actions</div>
                <div class="badge"><i class="fas fa-network-wired"></i> Tailscale</div>
                <div class="badge"><i class="fas fa-shield-alt"></i> Quantum Security</div>
            </div>
        </div>

        <div class="stats-grid">
            <div class="stat-card"><div class="stat-label">TOTAL VMS</div><div class="stat-value" id="statTotal">0</div></div>
            <div class="stat-card"><div class="stat-label">ACTIVE VMS</div><div class="stat-value" id="statActive">0</div></div>
            <div class="stat-card"><div class="stat-label">UPTIME</div><div class="stat-value" id="statUptime">00:00:00</div></div>
            <div class="stat-card"><div class="stat-label">SUCCESS RATE</div><div class="stat-value" id="statRate">100%</div></div>
        </div>

        <div class="two-columns">
            <div class="card">
                <div class="card-title"><i class="fas fa-rocket"></i> Khởi tạo Virtual Machine</div>
                <div class="input-group"><label class="input-label"><i class="fab fa-github"></i> GitHub Token</label><input type="password" class="input-field" id="githubToken" placeholder="ghp_xxxxxxxxxxxx"></div>
                <div class="input-group"><label class="input-label"><i class="fas fa-network-wired"></i> Tailscale Key</label><input type="password" class="input-field" id="tailscaleKey" placeholder="tskey-xxxxxxxxxxxx"></div>
                <div class="input-row"><div class="input-group"><label class="input-label"><i class="fas fa-user"></i> Tên đăng nhập</label><input type="text" class="input-field" id="vmUsername" placeholder="username"></div><button class="random-btn" id="randomUserBtn"><i class="fas fa-dice"></i> Random</button></div>
                <div class="input-row"><div class="input-group"><label class="input-label"><i class="fas fa-lock"></i> Mật khẩu</label><input type="password" class="input-field" id="vmPassword" placeholder="password"></div><button class="random-btn" id="randomPassBtn"><i class="fas fa-dice"></i> Random</button></div>
                <div class="progress-container" id="progressContainer"><div class="progress-steps" id="progressSteps"><div class="progress-step"><i class="fas fa-key"></i> Token</div><div class="progress-step"><i class="fas fa-folder-plus"></i> Repo</div><div class="progress-step"><i class="fas fa-file-code"></i> Workflow</div><div class="progress-step"><i class="fas fa-play"></i> Trigger</div><div class="progress-step"><i class="fas fa-check-circle"></i> Done</div></div><div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div><div class="progress-text" id="progressText">Sẵn sàng</div></div>
                <button class="btn btn-primary" id="createBtn"><i class="fas fa-play"></i> Tạo VM Ngay</button>
                <div class="quick-actions"><div class="quick-btn" id="demoBtn"><i class="fas fa-flask"></i> Demo</div><div class="quick-btn" id="clearBtn"><i class="fas fa-eraser"></i> Xóa</div><div class="quick-btn" id="refreshBtn"><i class="fas fa-sync-alt"></i> Làm mới</div><div class="quick-btn" id="saveConfigBtn"><i class="fas fa-save"></i> Lưu</div><div class="quick-btn" id="loadConfigBtn"><i class="fas fa-folder-open"></i> Tải</div></div>
            </div>

            <div class="card">
                <div class="card-title"><i class="fas fa-server"></i> Virtual Machines</div>
                <div class="vm-controls"><input type="text" class="vm-search" id="searchInput" placeholder="🔍 Tìm kiếm..."><select class="vm-filter" id="filterSelect"><option value="all">Tất cả</option><option value="running">Đang chạy</option><option value="creating">Đang tạo</option></select><select class="vm-sort" id="sortSelect"><option value="newest">Mới nhất</option><option value="oldest">Cũ nhất</option></select><div class="vm-count"><span id="vmCount">0</span></div></div>
                <div id="vmList"><div class="empty-state">✨ Chưa có VM nào ✨</div></div>
            </div>
        </div>

        <div class="debug-panel"><div class="debug-header" id="debugHeader"><div><i class="fas fa-terminal"></i> Debug Console</div><div><button class="debug-clear" id="clearLogsBtn">Xóa</button> <span id="debugToggle">▼</span></div></div><div class="debug-content" id="debugLogs"><div class="debug-log"><span class="debug-time">--:--:--</span><span class="debug-info">🚀 Khởi động</span></div></div></div>
        <div class="footer">© 2026 Singularity Club | <i class="fab fa-github"></i> GitHub</div>
    </div>
    <div id="toast" class="toast"><i class="fas fa-check-circle"></i> <span id="toastMsg"></span></div>

    <script>
        const API_URL = 'http://100.126.19.77:5000/api/vps';
        let vms = [], sessionStart = Date.now();
        let currentFilter = 'all', currentSort = 'newest';
        let totalCreations = 0, successfulCreations = 0;
        
        const elements = {
            githubToken: document.getElementById('githubToken'),
            tailscaleKey: document.getElementById('tailscaleKey'),
            vmUsername: document.getElementById('vmUsername'),
            vmPassword: document.getElementById('vmPassword'),
            createBtn: document.getElementById('createBtn'),
            vmList: document.getElementById('vmList'),
            searchInput: document.getElementById('searchInput'),
            filterSelect: document.getElementById('filterSelect'),
            sortSelect: document.getElementById('sortSelect'),
            vmCount: document.getElementById('vmCount'),
            statTotal: document.getElementById('statTotal'),
            statActive: document.getElementById('statActive'),
            statUptime: document.getElementById('statUptime'),
            statRate: document.getElementById('statRate'),
            progressContainer: document.getElementById('progressContainer'),
            progressFill: document.getElementById('progressFill'),
            progressText: document.getElementById('progressText'),
            progressSteps: document.getElementById('progressSteps'),
            toast: document.getElementById('toast'),
            toastMsg: document.getElementById('toastMsg'),
            debugLogs: document.getElementById('debugLogs')
        };
        
        function addLog(msg, type) {
            const time = new Date().toLocaleTimeString();
            const div = document.createElement('div');
            div.className = 'debug-log';
            div.innerHTML = `<span class="debug-time">${time}</span><span class="debug-${type || 'info'}">${msg}</span>`;
            elements.debugLogs.insertBefore(div, elements.debugLogs.firstChild);
        }
        
        function showToast(msg, type) {
            elements.toastMsg.textContent = msg;
            elements.toast.classList.add('show');
            setTimeout(() => elements.toast.classList.remove('show'), 3000);
            addLog(msg, type);
        }
        
        function randomUsername() {
            return Math.random().toString(36).substring(2, 10);
        }
        
        function randomPassword() {
            const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*';
            let result = '';
            for (let i = 0; i < 12; i++) result += chars[Math.floor(Math.random() * chars.length)];
            return result;
        }
        
        function updateStats() {
            elements.statTotal.textContent = vms.length;
            elements.statActive.textContent = vms.filter(v => v.status === 'running').length;
            const rate = totalCreations > 0 ? Math.floor((successfulCreations / totalCreations) * 100) : 100;
            elements.statRate.textContent = rate + '%';
            const elapsed = Math.floor((Date.now() - sessionStart) / 1000);
            elements.statUptime.textContent = `${Math.floor(elapsed/3600).toString().padStart(2,'0')}:${Math.floor((elapsed%3600)/60).toString().padStart(2,'0')}:${(elapsed%60).toString().padStart(2,'0')}`;
        }
        
        function updateCreateProgress(step, percent, text) {
            elements.progressFill.style.width = percent + '%';
            elements.progressText.textContent = text;
            const steps = elements.progressSteps.children;
            for (let i = 0; i < steps.length; i++) {
                steps[i].classList.remove('active', 'completed');
                if (i < step) steps[i].classList.add('completed');
                else if (i === step) steps[i].classList.add('active');
            }
        }
        
        function renderVMList() {
            let filtered = [...vms];
            const search = elements.searchInput.value.toLowerCase();
            if (search) filtered = filtered.filter(v => (v.name || '').toLowerCase().includes(search) || (v.username || '').toLowerCase().includes(search));
            if (currentFilter !== 'all') filtered = filtered.filter(v => v.status === currentFilter);
            if (currentSort === 'newest') filtered.sort((a,b) => new Date(b.createdAt) - new Date(a.createdAt));
            else filtered.sort((a,b) => new Date(a.createdAt) - new Date(b.createdAt));
            elements.vmCount.textContent = filtered.length;
            updateStats();
            if (filtered.length === 0) { elements.vmList.innerHTML = '<div class="empty-state">✨ Chưa có VM nào ✨</div>'; return; }
            elements.vmList.innerHTML = filtered.map(vm => `
                <div class="vm-item" data-id="${vm.id}">
                    <div class="vm-header" onclick="toggleVM('${vm.id}')">
                        <div class="vm-info"><div class="vm-icon"><i class="fas ${vm.status === 'running' ? 'fa-play-circle' : 'fa-spinner fa-pulse'}"></i></div><div><div class="vm-name">${vm.name || vm.id.substring(0,15)}</div><div class="vm-time">${new Date(vm.createdAt).toLocaleString()}</div></div></div>
                        <div style="display:flex; gap:10px;"><span class="vm-status status-${vm.status}">${vm.status}</span><i class="fas fa-chevron-down vm-expand-icon"></i></div>
                    </div>
                    <div class="vm-detail">
                        <div class="info-grid">
                            <div class="info-box"><div class="info-title">THÔNG TIN ĐĂNG NHẬP</div>
                                <div class="info-value"><span>${vm.username}</span><button class="copy-btn" onclick="copyText('${vm.username}')">Sao chép</button></div>
                                <div class="info-value" style="margin-top:8px;"><span>••••••••</span><button class="copy-btn" onclick="copyText('${vm.password}')">Sao chép</button></div>
                            </div>
                            <div class="info-box"><div class="info-title">THỜI GIAN</div>
                                <div class="info-value">Tạo: ${new Date(vm.createdAt).toLocaleString()}</div>
                                <div class="info-value">Hết hạn: ${new Date(vm.expiresAt).toLocaleString()}</div>
                            </div>
                        </div>
                        ${vm.tailscaleIP ? `<div class="info-box"><div class="info-title">KẾT NỐI</div><div class="info-value"><span>Tailscale IP: ${vm.tailscaleIP}</span><button class="copy-btn" onclick="copyText('${vm.tailscaleIP}')">Sao chép</button></div></div>` : ''}
                        <div class="vm-links">${vm.repoUrl ? `<a href="${vm.repoUrl}" target="_blank" class="vm-link"><i class="fab fa-github"></i> Repository</a>` : ''}<button class="vm-delete" onclick="deleteVM('${vm.id}')"><i class="fas fa-trash"></i> Xóa VM</button></div>
                    </div>
                </div>
            `).join('');
        }
        
        window.toggleVM = function(id) { document.querySelector(`.vm-item[data-id="${id}"]`).classList.toggle('open'); };
        window.copyText = function(text) { navigator.clipboard.writeText(text); showToast('Đã sao chép!'); };
        
        async function loadVMs() {
            try { const res = await fetch(API_URL); const data = await res.json(); if (data.success) { vms = data.vms; renderVMList(); } } catch(e) { console.log(e); }
        }
        
        window.deleteVM = async function(id) {
            if (!confirm('Xóa VM này?')) return;
            try { await fetch(`${API_URL}?id=${id}`, { method: 'DELETE' }); showToast('Đã xóa VM'); await loadVMs(); } catch(e) { showToast('Lỗi xóa', 'error'); }
        };
        
        async function createVM() {
            const githubToken = elements.githubToken.value.trim();
            const tailscaleKey = elements.tailscaleKey.value.trim();
            let username = elements.vmUsername.value.trim() || randomUsername();
            let password = elements.vmPassword.value.trim() || randomPassword();
            if (!githubToken) { showToast('Nhập GitHub Token', 'error'); return; }
            if (!tailscaleKey) { showToast('Nhập Tailscale Key', 'error'); return; }
            
            elements.progressContainer.style.display = 'block';
            elements.createBtn.disabled = true;
            elements.createBtn.innerHTML = '<span class="spinner"></span> Đang tạo...';
            
            updateCreateProgress(0, 10, '🔑 Đang xác thực token...');
            await new Promise(r => setTimeout(r, 800));
            updateCreateProgress(1, 30, '📁 Đang tạo repository...');
            await new Promise(r => setTimeout(r, 1200));
            updateCreateProgress(2, 55, '📝 Đang tạo workflow...');
            await new Promise(r => setTimeout(r, 1500));
            updateCreateProgress(3, 80, '🚀 Đang trigger...');
            await new Promise(r => setTimeout(r, 1000));
            
            try {
                const res = await fetch(API_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ githubToken, tailscaleKey, vmUsername: username, vmPassword: password }) });
                const data = await res.json();
                totalCreations++;
                if (data.success) { successfulCreations++; updateCreateProgress(4, 100, '✅ Hoàn tất!'); showToast(`✅ VM "${username}" đã được tạo!`); await loadVMs(); elements.githubToken.value = ''; elements.tailscaleKey.value = ''; setTimeout(() => { elements.progressContainer.style.display = 'none'; }, 2000); }
                else { updateCreateProgress(0, 0, '❌ Thất bại!'); showToast(data.error || 'Tạo thất bại', 'error'); setTimeout(() => { elements.progressContainer.style.display = 'none'; }, 3000); }
            } catch(e) { showToast('Lỗi kết nối', 'error'); elements.progressContainer.style.display = 'none'; }
            elements.createBtn.disabled = false;
            elements.createBtn.innerHTML = '<i class="fas fa-play"></i> Tạo VM Ngay';
        }
        
        document.getElementById('createBtn').onclick = createVM;
        document.getElementById('randomUserBtn').onclick = () => { elements.vmUsername.value = randomUsername(); showToast('Username random'); };
        document.getElementById('randomPassBtn').onclick = () => { elements.vmPassword.value = randomPassword(); showToast('Password random'); };
        document.getElementById('demoBtn').onclick = () => { elements.githubToken.value = 'ghp_demo'; elements.tailscaleKey.value = 'tskey_demo'; showToast('Demo token'); };
        document.getElementById('clearBtn').onclick = () => { elements.githubToken.value = ''; elements.tailscaleKey.value = ''; elements.vmUsername.value = ''; elements.vmPassword.value = ''; };
        document.getElementById('refreshBtn').onclick = () => { loadVMs(); };
        document.getElementById('saveConfigBtn').onclick = () => { localStorage.setItem('vm_config', JSON.stringify({ token: elements.githubToken.value, key: elements.tailscaleKey.value })); showToast('Đã lưu'); };
        document.getElementById('loadConfigBtn').onclick = () => { const cfg = JSON.parse(localStorage.getItem('vm_config') || '{}'); if (cfg.token) elements.githubToken.value = cfg.token; if (cfg.key) elements.tailscaleKey.value = cfg.key; showToast('Đã tải'); };
        
        elements.filterSelect.onchange = (e) => { currentFilter = e.target.value; renderVMList(); };
        elements.sortSelect.onchange = (e) => { currentSort = e.target.value; renderVMList(); };
        elements.searchInput.oninput = () => { renderVMList(); };
        
        let debugVisible = true;
        document.getElementById('debugHeader').onclick = () => {
            debugVisible = !debugVisible;
            document.querySelector('.debug-content').classList.toggle('hidden', !debugVisible);
            document.getElementById('debugToggle').textContent = debugVisible ? '▼' : '▲';
        };
        document.getElementById('clearLogsBtn').onclick = () => { elements.debugLogs.innerHTML = ''; addLog('Đã xóa console'); };
        
        elements.vmUsername.value = randomUsername();
        elements.vmPassword.value = randomPassword();
        loadVMs();
        setInterval(loadVMs, 10000);
        setInterval(updateStats, 1000);
        addLog('🚀 Khởi động thành công!');
    </script>
</body>
</html>
HTMLEOF

# ============================================ #
# CÀI ĐẶT PYTHON PACKAGES
# ============================================ #
echo -e "${YELLOW}📦 Cài đặt Python packages...${NC}"
cd ~/singularity-vm/backend
pip3 install flask flask-cors requests --quiet

# ============================================ #
# CHẠY SERVER
# ============================================ #
echo -e "${GREEN}=========================================="
echo "🚀 ĐANG CHẠY SERVER..."
echo "==========================================${NC}"
echo ""
echo -e "${BLUE}📱 TRUY CẬP WEB:${NC}"
echo "   http://100.126.19.77:5000"
echo ""
echo -e "${YELLOW}⚠️  Nhấn Ctrl+C để dừng server${NC}"
echo ""

# Chạy Flask
python3 app.py
EOF

# ============================================ #
# CẤP QUYỀN VÀ CHẠY
# ============================================ #
chmod +x run.sh
./run.sh
