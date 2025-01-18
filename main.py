import os
import json
import asyncio
from fastapi import FastAPI, Request, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import httpx
import uvicorn
from typing import Dict, Any
from config import config

app = FastAPI()
client = httpx.AsyncClient()
templates = Jinja2Templates(directory="templates")
security = HTTPBasic()

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
    openai_api_base: str = Form(...),
    model_mapping: str = Form(...),
    _=Depends(is_authenticated)
):
    try:
        # 验证并更新配置
        model_mapping_dict = json.loads(model_mapping)
        config.admin_password = admin_password
        config.openai_api_key = openai_api_key
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

@app.get("/v1/models")
async def list_models():
    try:
        # 获取Ollama可用模型列表
        response = await client.get("http://localhost:11434/api/tags")
        ollama_models = response.json()
        
        # 转换为OpenAI格式
        models = []
        for model in ollama_models.get("models", []):
            model_name = model.get("name", "")
            models.append({
                "id": model_name,
                "object": "model",
                "created": 1677610602,
                "owned_by": "ollama",
                "permission": [],
                "root": model_name,
                "parent": None
            })
        
        return {"object": "list", "data": models}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        # 获取原始请求数据
        body = await request.json()
        
        # 将Ollama格式转换为OpenAI格式
        model = body.get("model", "gpt-3.5-turbo")
        messages = body.get("messages", [])
        
        # 准备OpenAI请求体
        openai_body = {
            "model": config.model_mapping.get(model, model),  # 使用配置的映射
            "messages": messages,
            "temperature": body.get("temperature", 0.7),
            "max_tokens": body.get("max_tokens", None),
            "stream": body.get("stream", False)
        }
        
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
        
        return response.json()
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 