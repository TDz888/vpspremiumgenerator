#!/bin/bash
# deploy.sh - Deploy script cho Ubuntu VPS

echo "========================================="
echo "Singularity Club - Deploy Script"
echo "========================================="

# Cập nhật hệ thống
echo "📦 Updating system..."
sudo apt update && sudo apt upgrade -y

# Cài đặt Python và pip
echo "🐍 Installing Python..."
sudo apt install python3 python3-pip python3-venv -y

# Cài đặt Nginx
echo "🌐 Installing Nginx..."
sudo apt install nginx -y

# Cài đặt Git
echo "📁 Installing Git..."
sudo apt install git -y

# Tạo thư mục dự án
echo "📂 Creating project directory..."
mkdir -p /home/ubuntu/singularity-vm
cd /home/ubuntu/singularity-vm

# Tạo virtual environment
echo "🔧 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Cài đặt dependencies
echo "📦 Installing Python dependencies..."
pip install flask flask-cors requests gunicorn

# Tạo file app.py
echo "📝 Creating app.py..."
cat > app.py << 'EOF'
# Nội dung file app.py ở trên
EOF

# Tạo file requirements.txt
echo "📝 Creating requirements.txt..."
cat > requirements.txt << 'EOF'
flask==2.3.3
flask-cors==4.0.0
requests==2.31.0
gunicorn==21.2.0
EOF

# Tạo service systemd
echo "⚙️ Creating systemd service..."
sudo cat > /etc/systemd/system/singularity-vm.service << 'EOF'
[Unit]
Description=Singularity VM API
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/singularity-vm
ExecStart=/home/ubuntu/singularity-vm/venv/bin/gunicorn -w 4 -b 0.0.0.0:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Cấu hình Nginx
echo "🌐 Configuring Nginx..."
sudo cat > /etc/nginx/sites-available/singularity-vm << 'EOF'
server {
    listen 80;
    server_name _;
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# Kích hoạt site
sudo ln -s /etc/nginx/sites-available/singularity-vm /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

# Khởi động service
echo "🚀 Starting service..."
sudo systemctl daemon-reload
sudo systemctl enable singularity-vm
sudo systemctl start singularity-vm

# Mở port trên firewall
echo "🔥 Configuring firewall..."
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 5000
sudo ufw --force enable

echo "========================================="
echo "✅ DEPLOY COMPLETED!"
echo "========================================="
echo "🌐 Web: http://YOUR_VPS_IP"
echo "🔗 API: http://YOUR_VPS_IP:5000/api/vps"
echo "========================================="
