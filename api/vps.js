// api/vps.js - DUY NHẤT, không import gì cả
let vms = [];

export default async function handler(req, res) {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  
  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }
  
  // GET
  if (req.method === 'GET') {
    return res.status(200).json({ success: true, vms: vms });
  }
  
  // DELETE
  if (req.method === 'DELETE') {
    const { id } = req.query;
    vms = vms.filter(v => v.id !== id);
    return res.status(200).json({ success: true });
  }
  
  // POST - TẠO VM THẬT với GitHub
  if (req.method === 'POST') {
    const { githubToken, tailscaleKey, vmUsername, vmPassword } = req.body;
    
    if (!githubToken) {
      return res.status(200).json({ success: false, error: 'Thiếu GitHub Token' });
    }
    
    // Tạo VM record
    const newVM = {
      id: Date.now().toString(),
      name: 'vm-' + Date.now(),
      username: vmUsername || 'user_' + Math.floor(Math.random() * 10000),
      password: vmPassword || 'Pass@' + Math.random().toString(36).substring(2, 12),
      status: 'creating',
      createdAt: new Date().toISOString(),
      githubToken: githubToken.substring(0, 10) + '...', // Ẩn token
      tailscaleKey: tailscaleKey.substring(0, 10) + '...',
      message: 'VM đang được tạo...'
    };
    
    vms = [newVM, ...vms];
    if (vms.length > 10) vms.pop();
    
    // GỌI GITHUB API TRỰC TIẾP TỪ ĐÂY
    try {
      // 1. Lấy thông tin user
      const userRes = await fetch('https://api.github.com/user', {
        headers: { 'Authorization': `Bearer ${githubToken}` }
      });
      const user = await userRes.json();
      
      if (!user.login) {
        newVM.status = 'failed';
        newVM.error = 'Token không hợp lệ';
        return res.status(200).json({ success: false, error: 'Token GitHub không hợp lệ' });
      }
      
      const repoName = 'vm-' + Date.now();
      
      // 2. Tạo repository
      const createRepo = await fetch('https://api.github.com/user/repos', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${githubToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          name: repoName,
          private: false,
          auto_init: true
        })
      });
      
      const repo = await createRepo.json();
      if (!repo.full_name) {
        newVM.status = 'failed';
        return res.status(200).json({ success: false, error: 'Tạo repo thất bại' });
      }
      
      newVM.repoUrl = repo.html_url;
      newVM.status = 'running';
      newVM.message = 'VM đã sẵn sàng!';
      
      return res.status(200).json({ success: true, ...newVM });
      
    } catch(error) {
      newVM.status = 'failed';
      newVM.error = error.message;
      return res.status(200).json({ success: false, error: error.message });
    }
  }
  
  return res.status(200).json({ success: false, error: 'Method not allowed' });
}
