#!/bin/bash
# ============================================
# Auto Tailscale - Chạy trên Ubuntu
# ============================================

TOKEN="tskey-auth-kN15hVdZyD11CNTRL-xxui6m8VFYJE9cpQs5EPYJLP7baA6y4h4"

echo "========================================"
echo "🚀 Đang cài đặt Tailscale..."
echo "========================================"

# Cài Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

echo "✅ Tailscale đã được cài đặt!"

echo "========================================"
echo "🔌 Đang kết nối Tailscale..."
echo "========================================"

# Kết nối
sudo tailscale up --auth-key="$TOKEN"

# Đợi kết nối
sleep 10

# Lấy IP
IP=$(tailscale ip -4)

echo "========================================"
echo "✅ KẾT NỐI THÀNH CÔNG!"
echo "========================================"
echo "🌐 Tailscale IP: $IP"
echo "========================================"
