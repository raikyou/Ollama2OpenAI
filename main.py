import os
import json
import asyncio
from fastapi import FastAPI, Request, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import httpx
import uvicorn
from typing import Dict, Any, List, Optional
from config import config
from pydantic import BaseModel

app = FastAPI()
client = httpx.AsyncClient()
templates = Jinja2Templates(directory="templates")
security = HTTPBasic()

# 数据模型
class Message(BaseModel):
    role: str
    content: str

class GenerateRequest(BaseModel):
    model: str
    prompt: str
    system: Optional[str] = None
    template: Optional[str] = None
    context: Optional[List[int]] = None
    stream: Optional[bool] = True
    raw: Optional[bool] = False
    format: Optional[str] = None
    options: Optional[Dict] = None

class ChatRequest(BaseModel):
    model: str
    messages: List[Message]
    stream: Optional[bool] = True
    format: Optional[str] = None
    options: Optional[Dict] = None

# 会话管理（简单实现，生产环境建议使用更安全的方式）
sessions = set()

def is_authenticated(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    if password == config.admin_password:
        session_id = os.urandom(16).hex()
        sessions.add(session_id)
        response = RedirectResponse(url="/config", status_code=302)
        response.set_cookie(key="session_id", value=session_id)
        return response
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "密码错误"},
        status_code=401
    )

@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request, _=Depends(is_authenticated)):
    return templates.TemplateResponse(
        "config.html",
        {
            "request": request,
            "config": config,
            "model_mapping_json": json.dumps(config.model_mapping, indent=2)
        }
    )

@app.post("/config")
async def save_config(
    request: Request,
    admin_password: str = Form(...),
    openai_api_key: str = Form(...),
    ollama_api_key: str = Form(None),
    openai_api_base: str = Form(...),
    model_mapping: str = Form(...),
    _=Depends(is_authenticated)
):
    try:
        model_mapping_dict = json.loads(model_mapping)
        config.admin_password = admin_password
        config.openai_api_key = openai_api_key
        config.ollama_api_key = ollama_api_key if ollama_api_key else None
        config.openai_api_base = openai_api_base
        config.model_mapping = model_mapping_dict
        config.save()
        
        return templates.TemplateResponse(
            "config.html",
            {
                "request": request,
                "config": config,
                "model_mapping_json": model_mapping,
                "success": "配置已保存"
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "config.html",
            {
                "request": request,
                "config": config,
                "model_mapping_json": model_mapping,
                "error": f"保存失败: {str(e)}"
            }
        )

@app.get("/api/tags")
async def list_models():
    try:
        # 获取OpenAI可用模型列表
        headers = {
            "Authorization": f"Bearer {config.openai_api_key}",
            "Content-Type": "application/json"
        }
        response = await client.get(
            f"{config.openai_api_base}/v1/models",
            headers=headers
        )
        openai_models = response.json()
        
        # 转换为Ollama格式
        models = []
        model_details = {
            "format": "gguf",
            "family": "llama",
            "families": ["llama"],
            "parameter_size": "7B",
            "quantization_level": "Q4_0"
        }
        
        # 添加所有原始模型
        for model in openai_models.get("data", []):
            model_id = model.get("id", "")
            models.append({
                "name": model_id,
                "modified_at": model.get("created"),
                "size": 0,
                "digest": "",
                "details": model_details
            })
            
            # 添加映射的别名
            aliases = [k for k, v in config.model_mapping.items() if v == model_id]
            for alias in aliases:
                models.append({
                    "name": alias,
                    "modified_at": model.get("created"),
                    "size": 0,
                    "digest": "",
                    "details": model_details,
                    "alias_for": model_id  # 添加一个字段表明这是别名
                })
        
        return {"models": models}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat(request: ChatRequest):
    try:
        # 将Ollama格式转换为OpenAI格式
        openai_body = {
            "model": config.model_mapping.get(request.model, request.model),
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": request.stream
        }
        
        if request.options:
            # 转换Ollama选项到OpenAI参数
            if "temperature" in request.options:
                openai_body["temperature"] = request.options["temperature"]
            if "top_p" in request.options:
                openai_body["top_p"] = request.options["top_p"]
            if "num_ctx" in request.options:
                openai_body["max_tokens"] = request.options["num_ctx"]
        
        # 准备请求头
        headers = {
            "Authorization": f"Bearer {config.openai_api_key}",
            "Content-Type": "application/json"
        }
        
        print(f"发送请求到 OpenAI: {openai_body}")  # 添加日志
        
        # 发送请求到OpenAI兼容接口
        response = await client.post(
            f"{config.openai_api_base}/v1/chat/completions",
            json=openai_body,
            headers=headers
        )
        
        if response.status_code != 200:
            error_detail = await response.text()
            print(f"OpenAI API 错误: {error_detail}")  # 添加日志
            raise HTTPException(
                status_code=response.status_code,
                detail=f"OpenAI API 错误: {error_detail}"
            )
        
        if request.stream:
            # 处理流式响应
            async def stream_response():
                async for chunk in response.aiter_lines():
                    if chunk:
                        try:
                            data = json.loads(chunk.removeprefix("data: "))
                            if "choices" in data and len(data["choices"]) > 0:
                                choice = data["choices"][0]
                                if "delta" in choice and "content" in choice["delta"]:
                                    yield json.dumps({
                                        "model": request.model,
                                        "created_at": data.get("created", ""),
                                        "message": {
                                            "role": "assistant",
                                            "content": choice["delta"]["content"]
                                        },
                                        "done": choice.get("finish_reason") is not None
                                    }) + "\n"
                        except json.JSONDecodeError as e:
                            print(f"JSON 解析错误: {e}, chunk: {chunk}")  # 添加日志
                            continue
                
                # 发送最后一个完成消息
                yield json.dumps({
                    "model": request.model,
                    "created_at": "",
                    "done": True
                }) + "\n"
            
            return StreamingResponse(stream_response(), media_type="text/event-stream")
        else:
            # 处理非流式响应
            data = response.json()
            if "choices" in data and len(data["choices"]) > 0:
                return {
                    "model": request.model,
                    "created_at": data.get("created", ""),
                    "message": {
                        "role": "assistant",
                        "content": data["choices"][0]["message"]["content"]
                    },
                    "done": True
                }
            else:
                print(f"OpenAI 响应缺少 choices: {data}")  # 添加日志
                raise HTTPException(status_code=500, detail="OpenAI API 返回了无效的响应格式")
        
    except httpx.RequestError as e:
        print(f"请求错误: {str(e)}")  # 添加日志
        raise HTTPException(status_code=500, detail=f"请求 OpenAI API 失败: {str(e)}")
    except json.JSONDecodeError as e:
        print(f"JSON 解析错误: {str(e)}")  # 添加日志
        raise HTTPException(status_code=500, detail=f"解析 OpenAI 响应失败: {str(e)}")
    except Exception as e:
        print(f"未知错误: {str(e)}")  # 添加日志
        raise HTTPException(status_code=500, detail=f"处理请求时发生错误: {str(e)}")

@app.post("/api/generate")
async def generate(request: GenerateRequest):
    try:
        # 构建消息列表
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        
        # 准备OpenAI请求体
        openai_body = {
            "model": config.model_mapping.get(request.model, request.model),
            "messages": messages,
            "stream": request.stream
        }
        
        if request.options:
            # 转换Ollama选项到OpenAI参数
            if "temperature" in request.options:
                openai_body["temperature"] = request.options["temperature"]
            if "top_p" in request.options:
                openai_body["top_p"] = request.options["top_p"]
            if "num_ctx" in request.options:
                openai_body["max_tokens"] = request.options["num_ctx"]
        
        # 准备请求头
        headers = {
            "Authorization": f"Bearer {config.openai_api_key}",
            "Content-Type": "application/json"
        }
        
        # 发送请求到OpenAI兼容接口
        response = await client.post(
            f"{config.openai_api_base}/v1/chat/completions",
            json=openai_body,
            headers=headers
        )
        
        if request.stream:
            # 处理流式响应
            async def stream_response():
                async for chunk in response.aiter_lines():
                    if chunk:
                        try:
                            data = json.loads(chunk.removeprefix("data: "))
                            if "choices" in data and len(data["choices"]) > 0:
                                choice = data["choices"][0]
                                if "delta" in choice and "content" in choice["delta"]:
                                    yield json.dumps({
                                        "model": request.model,
                                        "created_at": data.get("created", ""),
                                        "response": choice["delta"]["content"],
                                        "done": choice.get("finish_reason") is not None
                                    }) + "\n"
                        except json.JSONDecodeError:
                            continue
                
                # 发送最后一个完成消息
                yield json.dumps({
                    "model": request.model,
                    "created_at": "",
                    "done": True
                }) + "\n"
            
            return StreamingResponse(stream_response(), media_type="text/event-stream")
        else:
            # 处理非流式响应
            data = response.json()
            if "choices" in data and len(data["choices"]) > 0:
                return {
                    "model": request.model,
                    "created_at": data.get("created", ""),
                    "response": data["choices"][0]["message"]["content"],
                    "done": True
                }
            else:
                raise HTTPException(status_code=500, detail="No response from model")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 