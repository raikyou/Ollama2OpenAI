import json
from pydantic import BaseModel
from typing import Dict, Optional
import os

class Config(BaseModel):
    admin_password: str = "admin"  # 默认密码，建议修改
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com"
    model_mapping: Dict[str, str] = {}

    @classmethod
    def load(cls):
        if os.path.exists("config.json"):
            with open("config.json", "r") as f:
                data = json.load(f)
                return cls(**data)
        return cls()

    def save(self):
        with open("config.json", "w") as f:
            json.dump(self.dict(), f, indent=2)

# 全局配置实例
config = Config.load() 