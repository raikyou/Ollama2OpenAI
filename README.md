# Ollama2OpenAI

一个将 Ollama 格式的 API 请求转发到 OpenAI 兼容接口的服务。

## 功能特点 ✨

- 🔄 完整支持 Ollama API 格式
- 🎯 自动转换为 OpenAI API 格式
- 🎨 美观的 Web 配置界面
- 🔑 灵活的模型映射配置
- 🌓 自动深色/浅色主题
- ⌨️ 完整的键盘快捷键支持
- 🔒 可选的 API 认证

## 界面预览 ✨

![image](https://github.com/user-attachments/assets/e58293d0-c2ac-442f-be5c-48a0c6de4220)


## 快速开始 🚀

### 使用 Docker Hub（最简单）

```bash
# 创建数据目录
mkdir -p data

# 直接运行容器
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  lynricsy/ollama2openai:latest
```

### 本地构建（开发者）

```bash
# 构建镜像
docker build -t ollama2openai .

# 创建数据目录
mkdir -p data

# 运行容器
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  ollama2openai
```

配置文件会保存在 `data` 目录下，重启容器时会自动加载。

### 手动安装

1. 克隆仓库：
```bash
git clone https://github.com/yourusername/ollama2openai.git
cd ollama2openai
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 运行服务：
```bash
python main.py
```

## 配置说明 ⚙️

访问 `http://localhost:8000` 进入配置界面，可配置以下内容：

- 管理密码：用于登录配置界面
- OpenAI API Key：用于访问 OpenAI 兼容接口
- Ollama API Key：用于 Ollama API 认证（可选）
- OpenAI API Base URL：OpenAI 兼容接口的基础 URL
- 模型映射：配置 Ollama 模型名称到 OpenAI 模型的映射关系

### 模型映射

你可以为 OpenAI 的模型配置在 Ollama 中显示的别名。例如：

```json
{
  "llama2": "gpt-4",
  "mistral": "gpt-3.5-turbo"
}
```

配置界面支持：
- 点击可用模型列表自动创建映射
- 自动生成规范的 Ollama 别名
- 直观的映射关系管理

### 键盘快捷键

- `Alt + 1`: 聚焦管理密码
- `Alt + 2`: 聚焦 OpenAI API Key
- `Alt + 3`: 聚焦 Ollama API Key
- `Alt + 4`: 聚焦 Base URL
- `Alt + 5`: 添加新映射
- `Alt + S`: 保存配置
- `Alt + T`: 切换主题
- `Alt + H`: 显示/隐藏快捷键面板

## API 使用说明 📡

### 模型列表

```bash
curl http://localhost:8000/api/tags
```

### 聊天接口

```bash
curl http://localhost:8000/api/chat -d '{
  "model": "llama2",
  "messages": [
    {
      "role": "user",
      "content": "你好！"
    }
  ]
}'
```

### 生成接口

```bash
curl http://localhost:8000/api/generate -d '{
  "model": "llama2",
  "prompt": "你好！",
  "system": "你是一个友好的助手。"
}'
```

## 注意事项 ⚠️

- 首次使用请修改默认管理密码
- 请妥善保管你的 API 密钥
- Ollama API Key 为可选配置，留空则不使用认证
- 建议使用 HTTPS 代理以保护 API 通信安全
