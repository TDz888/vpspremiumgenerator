// netlify/functions/vps.js
let vms = [];

exports.handler = async (event, context) => {
  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Content-Type': 'application/json'
  };

  if (event.httpMethod === 'OPTIONS') {
    return { statusCode: 204, headers, body: '' };
  }

  if (event.httpMethod === 'GET') {
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({ success: true, vms: vms })
    };
  }

  if (event.httpMethod === 'DELETE') {
    const id = event.queryStringParameters?.id;
    if (id) vms = vms.filter(v => v.id !== id);
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({ success: true })
    };
  }

  if (event.httpMethod === 'POST') {
    try {
      const body = JSON.parse(event.body || '{}');
      const { githubToken, tailscaleKey, vmUsername, vmPassword } = body;

      if (!githubToken) {
        return {
          statusCode: 200,
          headers,
          body: JSON.stringify({ success: false, error: 'Thiếu GitHub Token' })
        };
      }

      const username = vmUsername || 'user_' + Math.floor(Math.random() * 10000);
      const password = vmPassword || 'Pass@' + Math.random().toString(36).substring(2, 12);

      let repoUrl = null, workflowUrl = null, status = 'creating', error = null, owner = null;

      try {
        const userRes = await fetch('https://api.github.com/user', {
          headers: { 'Authorization': `Bearer ${githubToken}` }
        });
        const user = await userRes.json();

        if (!user.login) {
          status = 'failed';
          error = 'Token GitHub không hợp lệ';
        } else {
          owner = user.login;
          const repoName = 'vm-' + Date.now() + '-' + Math.random().toString(36).substring(2, 8);
          const createRes = await fetch('https://api.github.com/user/repos', {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${githubToken}`,
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({
              name: repoName,
              description: `VM by ${username}`,
              private: false,
              auto_init: true
            })
          });
          const repo = await createRes.json();

          if (repo.html_url) {
            repoUrl = repo.html_url;
            workflowUrl = `https://github.com/${owner}/${repoName}/actions`;
            status = 'running';
          } else {
            status = 'failed';
            error = repo.message || 'Tạo repository thất bại';
          }
        }
      } catch (err) {
        status = 'failed';
        error = err.message;
      }

      const newVM = {
        id: Date.now().toString(),
        name: 'vm-' + Date.now(),
        owner: owner,
        username: username,
        password: password,
        status: status,
        repoUrl: repoUrl,
        workflowUrl: workflowUrl,
        error: error,
        createdAt: new Date().toISOString(),
        expiresAt: new Date(Date.now() + 6 * 60 * 60 * 1000).toISOString()
      };

      vms = [newVM, ...vms];
      if (vms.length > 20) vms.pop();

      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({ success: true, ...newVM })
      };
    } catch (error) {
      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({ success: false, error: error.message })
      };
    }
  }

  return {
    statusCode: 200,
    headers,
    body: JSON.stringify({ success: false, error: 'Method not allowed' })
  };
};
