"""
Database Models
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class VM:
    """VM Data Model"""
    id: str
    name: str
    username: str
    password: str
    status: str  # 'creating', 'running', 'expired'
    repo_url: Optional[str] = None
    workflow_url: Optional[str] = None
    tailscale_ip: Optional[str] = None
    novnc_url: Optional[str] = None
    created_at: str = None
    expires_at: str = None
    progress: int = 0
    github_repo: Optional[str] = None
    github_user: Optional[str] = None
    creator_ip: Optional[str] = None
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'username': self.username,
            'password': self.password,
            'status': self.status,
            'repoUrl': self.repo_url,
            'workflowUrl': self.workflow_url,
            'tailscaleIP': self.tailscale_ip,
            'novncUrl': self.novnc_url,
            'createdAt': self.created_at,
            'expiresAt': self.expires_at,
            'progress': self.progress,
            'githubRepo': self.github_repo,
            'githubUser': self.github_user
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create VM from dictionary"""
        return cls(
            id=data.get('id'),
            name=data.get('name'),
            username=data.get('username'),
            password=data.get('password'),
            status=data.get('status', 'creating'),
            repo_url=data.get('repoUrl'),
            workflow_url=data.get('workflowUrl'),
            tailscale_ip=data.get('tailscaleIP'),
            novnc_url=data.get('novncUrl'),
            created_at=data.get('createdAt'),
            expires_at=data.get('expiresAt'),
            progress=data.get('progress', 0),
            github_repo=data.get('githubRepo'),
            github_user=data.get('githubUser'),
            creator_ip=data.get('creatorIP')
        )

@dataclass
class RateLimit:
    """Rate Limit Model"""
    ip: str
    count: int
    reset_at: str
