from datetime import datetime
from dataclasses import dataclass
from typing import Optional

@dataclass
class Message:
    """
    消息模型类，对应Java版本的Message实体
    """
    id: Optional[int] = None
    sender: str = ""
    content: str = ""
    created_at: datetime = None  # 保持字段名不变，但在数据库操作中映射到timestamp
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
    
    def to_dict(self):
        """
        将消息对象转换为字典
        """
        return {
            "id": self.id,
            "sender": self.sender,
            "content": self.content,
            "timestamp": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None
        }
    
    @classmethod
    def from_dict(cls, data):
        """
        从字典创建消息对象
        """
        return cls(
            id=data.get("id"),
            sender=data.get("sender"),
            content=data.get("content"),
            created_at=datetime.strptime(data.get("timestamp"), "%Y-%m-%d %H:%M:%S") if data.get("timestamp") else None
        ) 