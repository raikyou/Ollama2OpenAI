import json
import os

class Config:
    def __init__(self):
        self.admin_password = "admin"  # 默认管理密码
        self.openai_api_key = ""  # OpenAI API Key
        self.ollama_api_key = None  # Ollama API Key，允许为空
        self.openai_api_base = "https://api.openai.com"  # OpenAI API Base URL
        self.model_mapping = {}  # 模型映射关系
        self.load()

    def load(self):
        """从配置文件加载配置"""
        if os.path.exists("config.json"):
            try:
                with open("config.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.admin_password = data.get("admin_password", self.admin_password)
                    self.openai_api_key = data.get("openai_api_key", self.openai_api_key)
                    self.ollama_api_key = data.get("ollama_api_key", None)  # 允许为空
                    self.openai_api_base = data.get("openai_api_base", self.openai_api_base)
                    self.model_mapping = data.get("model_mapping", self.model_mapping)
            except Exception as e:
                print(f"加载配置文件失败: {e}")

    def save(self):
        """保存配置到文件"""
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump({
                    "admin_password": self.admin_password,
                    "openai_api_key": self.openai_api_key,
                    "ollama_api_key": self.ollama_api_key,  # 可以为 None
                    "openai_api_base": self.openai_api_base,
                    "model_mapping": self.model_mapping
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置文件失败: {e}")

config = Config() 