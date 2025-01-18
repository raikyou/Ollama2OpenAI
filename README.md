# Ollama2OpenAI

这是一个API转发服务，可以将Ollama格式的API请求转发到OpenAI兼容的API接口。

## 功能特点

- 支持异步并发处理请求
- 使用FastAPI框架，性能优异
- Docker容器化部署
- 通过环境变量配置API密钥和目标接口

## 快速开始

### 构建Docker镜像

```bash
docker build -t ollama2openai .
```

### 运行容器

```bash
docker run -d \
  -p 8000:8000 \
  -e OPENAI_API_KEY=你的OpenAI密钥 \
  -e OPENAI_API_BASE=https://你的API基础地址 \
  -e OLLAMA_API_KEY=你的Ollama密钥 \
  ollama2openai
```

## 环境变量说明

- `OPENAI_API_KEY`: OpenAI兼容接口的API密钥
- `OPENAI_API_BASE`: OpenAI兼容接口的基础URL
- `OLLAMA_API_KEY`: Ollama的API密钥（如果需要）

## API使用

服务启动后，可以向 `http://localhost:8000/v1/chat/completions` 发送Ollama格式的请求，服务会自动转换为OpenAI格式并转发。

## 注意事项

- 请确保环境变量正确配置
- 默认监听端口为8000
- 支持异步并发处理多个请求 