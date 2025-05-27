import os
import json
import asyncio
from fastapi import FastAPI, Request, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import httpx
import uvicorn
from typing import Dict, Any, List, Optional, Union
from config import config
from pydantic import BaseModel
from datetime import datetime, timezone

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

class EmbeddingRequest(BaseModel):
    model: str
    prompt: Union[str, List[str]]
    options: Optional[Dict] = None

class ShowRequest(BaseModel):
    model: str

# 会话管理（简单实现，生产环境建议使用更安全的方式）
sessions = set()

def is_authenticated(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise RedirectResponse(url="/login", status_code=302)
    return True

@app.get("/", response_class=JSONResponse)
async def root_status():
    return {"status": "Ollama is running"}

@app.get("/login", response_class=HTMLResponse)
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

        models = []
        # 修改后的 model_details 基础模板
        base_model_details = {
            "parent_model": "",
            "format": "gguf",
            "family": "openai",
            "families": ["openai"],
            "parameter_size": "N/A",
            "quantization_level": "N/A"
        }

        # 添加所有原始模型
        for model in openai_models.get("data", []):
            model_id = model.get("id", "")
            if not model_id: # 如果 model_id 为空则跳过
                continue

            # 不添加 :latest 后缀，直接使用原始模型名
            created_timestamp = model.get("created")

            if created_timestamp:
                # 将 Unix 时间戳转换为带时区的 ISO 8601 格式字符串
                modified_at_iso = datetime.fromtimestamp(created_timestamp, timezone.utc).isoformat()
            else:
                # 如果 OpenAI API 没有提供 created 时间戳，使用当前时间并格式化
                modified_at_iso = datetime.now(timezone.utc).isoformat()

            current_details = base_model_details.copy()
            # 可选：更细致的 family 推断可以后续添加
            # if "gpt" in model_id.lower():
            #     current_details["family"] = "gpt"
            #     current_details["families"] = ["gpt"]

            models.append({
                "name": model_id,
                "model": model_id,
                "modified_at": modified_at_iso,
                "size": 0,
                "digest": "",
                "details": current_details
            })

            # 添加映射的别名
            aliases = [k for k, v in config.model_mapping.items() if v == model_id]
            for alias in aliases:
                alias_details = base_model_details.copy()
                # 别名也使用相同的 details 结构和时间戳，不添加 :latest 后缀
                models.append({
                    "name": alias,
                    "model": alias,
                    "modified_at": modified_at_iso, # 使用原始模型的时间戳
                    "size": 0,
                    "digest": "",
                    "details": alias_details
                })

        return {"models": models}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/show")
async def show_model(request: ShowRequest):
    """
    显示模型信息的接口，返回写死的参数以兼容 Ollama API
    """
    try:
        model_name = request.model

        # 检查模型是否存在于映射中或者是有效的模型
        mapped_model = config.model_mapping.get(model_name, model_name)

        # 返回写死的模型信息，模拟 Ollama 的响应格式
        modelfile_content = f"""# Modelfile generated by "ollama show"
# To build a new Modelfile based on this one, replace the FROM line with:
# FROM {mapped_model}

FROM {mapped_model}
TEMPLATE \"\"\"{{{{ if .System }}}}{{{{ .System }}}}{{{{ end }}}}{{{{ if .Prompt }}}}### Human: {{{{ .Prompt }}}}{{{{ end }}}}

### Assistant: \"\"\"
PARAMETER stop "### Human:"
PARAMETER stop "### Assistant:\""""

        response =        {
            "license": "                                 Apache License\n                           Version 2.0, January 2004\n                        http://www.apache.org/licenses/\n\n   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION\n\n   1. Definitions.\n\n      \"License\" shall mean the terms and conditions for use, reproduction,\n      and distribution as defined by Sections 1 through 9 of this document.\n\n      \"Licensor\" shall mean the copyright owner or entity authorized by\n      the copyright owner that is granting the License.\n\n      \"Legal Entity\" shall mean the union of the acting entity and all\n      other entities that control, are controlled by, or are under common\n      control with that entity. For the purposes of this definition,\n      \"control\" means (i) the power, direct or indirect, to cause the\n      direction or management of such entity, whether by contract or\n      otherwise, or (ii) ownership of fifty percent (50%) or more of the\n      outstanding shares, or (iii) beneficial ownership of such entity.\n\n      \"You\" (or \"Your\") shall mean an individual or Legal Entity\n      exercising permissions granted by this License.\n\n      \"Source\" form shall mean the preferred form for making modifications,\n      including but not limited to software source code, documentation\n      source, and configuration files.\n\n      \"Object\" form shall mean any form resulting from mechanical\n      transformation or translation of a Source form, including but\n      not limited to compiled object code, generated documentation,\n      and conversions to other media types.\n\n      \"Work\" shall mean the work of authorship, whether in Source or\n      Object form, made available under the License, as indicated by a\n      copyright notice that is included in or attached to the work\n      (an example is provided in the Appendix below).\n\n      \"Derivative Works\" shall mean any work, whether in Source or Object\n      form, that is based on (or derived from) the Work and for which the\n      editorial revisions, annotations, elaborations, or other modifications\n      represent, as a whole, an original work of authorship. For the purposes\n      of this License, Derivative Works shall not include works that remain\n      separable from, or merely link (or bind by name) to the interfaces of,\n      the Work and Derivative Works thereof.\n\n      \"Contribution\" shall mean any work of authorship, including\n      the original version of the Work and any modifications or additions\n      to that Work or Derivative Works thereof, that is intentionally\n      submitted to Licensor for inclusion in the Work by the copyright owner\n      or by an individual or Legal Entity authorized to submit on behalf of\n      the copyright owner. For the purposes of this definition, \"submitted\"\n      means any form of electronic, verbal, or written communication sent\n      to the Licensor or its representatives, including but not limited to\n      communication on electronic mailing lists, source code control systems,\n      and issue tracking systems that are managed by, or on behalf of, the\n      Licensor for the purpose of discussing and improving the Work, but\n      excluding communication that is conspicuously marked or otherwise\n      designated in writing by the copyright owner as \"Not a Contribution.\"\n\n      \"Contributor\" shall mean Licensor and any individual or Legal Entity\n      on behalf of whom a Contribution has been received by Licensor and\n      subsequently incorporated within the Work.\n\n   2. Grant of Copyright License. Subject to the terms and conditions of\n      this License, each Contributor hereby grants to You a perpetual,\n      worldwide, non-exclusive, no-charge, royalty-free, irrevocable\n      copyright license to reproduce, prepare Derivative Works of,\n      publicly display, publicly perform, sublicense, and distribute the\n      Work and such Derivative Works in Source or Object form.\n\n   3. Grant of Patent License. Subject to the terms and conditions of\n      this License, each Contributor hereby grants to You a perpetual,\n      worldwide, non-exclusive, no-charge, royalty-free, irrevocable\n      (except as stated in this section) patent license to make, have made,\n      use, offer to sell, sell, import, and otherwise transfer the Work,\n      where such license applies only to those patent claims licensable\n      by such Contributor that are necessarily infringed by their\n      Contribution(s) alone or by combination of their Contribution(s)\n      with the Work to which such Contribution(s) was submitted. If You\n      institute patent litigation against any entity (including a\n      cross-claim or counterclaim in a lawsuit) alleging that the Work\n      or a Contribution incorporated within the Work constitutes direct\n      or contributory patent infringement, then any patent licenses\n      granted to You under this License for that Work shall terminate\n      as of the date such litigation is filed.\n\n   4. Redistribution. You may reproduce and distribute copies of the\n      Work or Derivative Works thereof in any medium, with or without\n      modifications, and in Source or Object form, provided that You\n      meet the following conditions:\n\n      (a) You must give any other recipients of the Work or\n          Derivative Works a copy of this License; and\n\n      (b) You must cause any modified files to carry prominent notices\n          stating that You changed the files; and\n\n      (c) You must retain, in the Source form of any Derivative Works\n          that You distribute, all copyright, patent, trademark, and\n          attribution notices from the Source form of the Work,\n          excluding those notices that do not pertain to any part of\n          the Derivative Works; and\n\n      (d) If the Work includes a \"NOTICE\" text file as part of its\n          distribution, then any Derivative Works that You distribute must\n          include a readable copy of the attribution notices contained\n          within such NOTICE file, excluding those notices that do not\n          pertain to any part of the Derivative Works, in at least one\n          of the following places: within a NOTICE text file distributed\n          as part of the Derivative Works; within the Source form or\n          documentation, if provided along with the Derivative Works; or,\n          within a display generated by the Derivative Works, if and\n          wherever such third-party notices normally appear. The contents\n          of the NOTICE file are for informational purposes only and\n          do not modify the License. You may add Your own attribution\n          notices within Derivative Works that You distribute, alongside\n          or as an addendum to the NOTICE text from the Work, provided\n          that such additional attribution notices cannot be construed\n          as modifying the License.\n\n      You may add Your own copyright statement to Your modifications and\n      may provide additional or different license terms and conditions\n      for use, reproduction, or distribution of Your modifications, or\n      for any such Derivative Works as a whole, provided Your use,\n      reproduction, and distribution of the Work otherwise complies with\n      the conditions stated in this License.\n\n   5. Submission of Contributions. Unless You explicitly state otherwise,\n      any Contribution intentionally submitted for inclusion in the Work\n      by You to the Licensor shall be under the terms and conditions of\n      this License, without any additional terms or conditions.\n      Notwithstanding the above, nothing herein shall supersede or modify\n      the terms of any separate license agreement you may have executed\n      with Licensor regarding such Contributions.\n\n   6. Trademarks. This License does not grant permission to use the trade\n      names, trademarks, service marks, or product names of the Licensor,\n      except as required for reasonable and customary use in describing the\n      origin of the Work and reproducing the content of the NOTICE file.\n\n   7. Disclaimer of Warranty. Unless required by applicable law or\n      agreed to in writing, Licensor provides the Work (and each\n      Contributor provides its Contributions) on an \"AS IS\" BASIS,\n      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or\n      implied, including, without limitation, any warranties or conditions\n      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A\n      PARTICULAR PURPOSE. You are solely responsible for determining the\n      appropriateness of using or redistributing the Work and assume any\n      risks associated with Your exercise of permissions under this License.\n\n   8. Limitation of Liability. In no event and under no legal theory,\n      whether in tort (including negligence), contract, or otherwise,\n      unless required by applicable law (such as deliberate and grossly\n      negligent acts) or agreed to in writing, shall any Contributor be\n      liable to You for damages, including any direct, indirect, special,\n      incidental, or consequential damages of any character arising as a\n      result of this License or out of the use or inability to use the\n      Work (including but not limited to damages for loss of goodwill,\n      work stoppage, computer failure or malfunction, or any and all\n      other commercial damages or losses), even if such Contributor\n      has been advised of the possibility of such damages.\n\n   9. Accepting Warranty or Additional Liability. While redistributing\n      the Work or Derivative Works thereof, You may choose to offer,\n      and charge a fee for, acceptance of support, warranty, indemnity,\n      or other liability obligations and/or rights consistent with this\n      License. However, in accepting such obligations, You may act only\n      on Your own behalf and on Your sole responsibility, not on behalf\n      of any other Contributor, and only if You agree to indemnify,\n      defend, and hold each Contributor harmless for any liability\n      incurred by, or claims asserted against, such Contributor by reason\n      of your accepting any such warranty or additional liability.\n\n   END OF TERMS AND CONDITIONS\n\n   APPENDIX: How to apply the Apache License to your work.\n\n      To apply the Apache License to your work, attach the following\n      boilerplate notice, with the fields enclosed by brackets \"[]\"\n      replaced with your own identifying information. (Don't include\n      the brackets!)  The text should be enclosed in the appropriate\n      comment syntax for the file format. We also recommend that a\n      file or class name and description of purpose be included on the\n      same \"printed page\" as the copyright notice for easier\n      identification within third-party archives.\n   Copyright 2024 Alibaba Cloud\n   Licensed under the Apache License, Version 2.0 (the \"License\");\n   you may not use this file except in compliance with the License.\n   You may obtain a copy of the License at\n       http://www.apache.org/licenses/LICENSE-2.0\n   Unless required by applicable law or agreed to in writing, software\n   distributed under the License is distributed on an \"AS IS\" BASIS,\n   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.\n   See the License for the specific language governing permissions and\n   limitations under the License.",
            "modelfile": "# Modelfile generated by \"ollama show\"\n# To build a new Modelfile based on this, replace FROM with:\n# FROM qwen3:235b\n\nFROM /work/ollama/models/blobs/sha256-aeacdadecbed8a07e42026d1a1d3cd30715bb2994ebe4e4ca4009e1a4abe8d5d\nTEMPLATE \"\"\"{{- if .Messages }}\n{{- if or .System .Tools }}\u003c|im_start|\u003esystem\n{{- if .System }}\n{{ .System }}\n{{- end }}\n{{- if .Tools }}\n\n# Tools\n\nYou may call one or more functions to assist with the user query.\n\nYou are provided with function signatures within \u003ctools\u003e\u003c/tools\u003e XML tags:\n\u003ctools\u003e\n{{- range .Tools }}\n{\"type\": \"function\", \"function\": {{ .Function }}}\n{{- end }}\n\u003c/tools\u003e\n\nFor each function call, return a json object with function name and arguments within \u003ctool_call\u003e\u003c/tool_call\u003e XML tags:\n\u003ctool_call\u003e\n{\"name\": \u003cfunction-name\u003e, \"arguments\": \u003cargs-json-object\u003e}\n\u003c/tool_call\u003e\n{{- end }}\u003c|im_end|\u003e\n{{ end }}\n{{- range $i, $_ := .Messages }}\n{{- $last := eq (len (slice $.Messages $i)) 1 -}}\n{{- if eq .Role \"user\" }}\u003c|im_start|\u003euser\n{{ .Content }}\u003c|im_end|\u003e\n{{ else if eq .Role \"assistant\" }}\u003c|im_start|\u003eassistant\n{{ if .Content }}{{ .Content }}\n{{- else if .ToolCalls }}\u003ctool_call\u003e\n{{ range .ToolCalls }}{\"name\": \"{{ .Function.Name }}\", \"arguments\": {{ .Function.Arguments }}}\n{{ end }}\u003c/tool_call\u003e\n{{- end }}{{ if not $last }}\u003c|im_end|\u003e\n{{ end }}\n{{- else if eq .Role \"tool\" }}\u003c|im_start|\u003euser\n\u003ctool_response\u003e\n{{ .Content }}\n\u003c/tool_response\u003e\u003c|im_end|\u003e\n{{ end }}\n{{- if and (ne .Role \"assistant\") $last }}\u003c|im_start|\u003eassistant\n{{ end }}\n{{- end }}\n{{- else }}\n{{- if .System }}\u003c|im_start|\u003esystem\n{{ .System }}\u003c|im_end|\u003e\n{{ end }}{{ if .Prompt }}\u003c|im_start|\u003euser\n{{ .Prompt }}\u003c|im_end|\u003e\n{{ end }}\u003c|im_start|\u003eassistant\n{{ end }}{{ .Response }}{{ if .Response }}\u003c|im_end|\u003e{{ end }}\"\"\"\nPARAMETER temperature 0.6\nPARAMETER top_k 20\nPARAMETER top_p 0.95\nPARAMETER repeat_penalty 1\nPARAMETER stop \u003c|im_start|\u003e\nPARAMETER stop \u003c|im_end|\u003e\nLICENSE \"\"\"                                 Apache License\n                           Version 2.0, January 2004\n                        http://www.apache.org/licenses/\n\n   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION\n\n   1. Definitions.\n\n      \"License\" shall mean the terms and conditions for use, reproduction,\n      and distribution as defined by Sections 1 through 9 of this document.\n\n      \"Licensor\" shall mean the copyright owner or entity authorized by\n      the copyright owner that is granting the License.\n\n      \"Legal Entity\" shall mean the union of the acting entity and all\n      other entities that control, are controlled by, or are under common\n      control with that entity. For the purposes of this definition,\n      \"control\" means (i) the power, direct or indirect, to cause the\n      direction or management of such entity, whether by contract or\n      otherwise, or (ii) ownership of fifty percent (50%) or more of the\n      outstanding shares, or (iii) beneficial ownership of such entity.\n\n      \"You\" (or \"Your\") shall mean an individual or Legal Entity\n      exercising permissions granted by this License.\n\n      \"Source\" form shall mean the preferred form for making modifications,\n      including but not limited to software source code, documentation\n      source, and configuration files.\n\n      \"Object\" form shall mean any form resulting from mechanical\n      transformation or translation of a Source form, including but\n      not limited to compiled object code, generated documentation,\n      and conversions to other media types.\n\n      \"Work\" shall mean the work of authorship, whether in Source or\n      Object form, made available under the License, as indicated by a\n      copyright notice that is included in or attached to the work\n      (an example is provided in the Appendix below).\n\n      \"Derivative Works\" shall mean any work, whether in Source or Object\n      form, that is based on (or derived from) the Work and for which the\n      editorial revisions, annotations, elaborations, or other modifications\n      represent, as a whole, an original work of authorship. For the purposes\n      of this License, Derivative Works shall not include works that remain\n      separable from, or merely link (or bind by name) to the interfaces of,\n      the Work and Derivative Works thereof.\n\n      \"Contribution\" shall mean any work of authorship, including\n      the original version of the Work and any modifications or additions\n      to that Work or Derivative Works thereof, that is intentionally\n      submitted to Licensor for inclusion in the Work by the copyright owner\n      or by an individual or Legal Entity authorized to submit on behalf of\n      the copyright owner. For the purposes of this definition, \"submitted\"\n      means any form of electronic, verbal, or written communication sent\n      to the Licensor or its representatives, including but not limited to\n      communication on electronic mailing lists, source code control systems,\n      and issue tracking systems that are managed by, or on behalf of, the\n      Licensor for the purpose of discussing and improving the Work, but\n      excluding communication that is conspicuously marked or otherwise\n      designated in writing by the copyright owner as \"Not a Contribution.\"\n\n      \"Contributor\" shall mean Licensor and any individual or Legal Entity\n      on behalf of whom a Contribution has been received by Licensor and\n      subsequently incorporated within the Work.\n\n   2. Grant of Copyright License. Subject to the terms and conditions of\n      this License, each Contributor hereby grants to You a perpetual,\n      worldwide, non-exclusive, no-charge, royalty-free, irrevocable\n      copyright license to reproduce, prepare Derivative Works of,\n      publicly display, publicly perform, sublicense, and distribute the\n      Work and such Derivative Works in Source or Object form.\n\n   3. Grant of Patent License. Subject to the terms and conditions of\n      this License, each Contributor hereby grants to You a perpetual,\n      worldwide, non-exclusive, no-charge, royalty-free, irrevocable\n      (except as stated in this section) patent license to make, have made,\n      use, offer to sell, sell, import, and otherwise transfer the Work,\n      where such license applies only to those patent claims licensable\n      by such Contributor that are necessarily infringed by their\n      Contribution(s) alone or by combination of their Contribution(s)\n      with the Work to which such Contribution(s) was submitted. If You\n      institute patent litigation against any entity (including a\n      cross-claim or counterclaim in a lawsuit) alleging that the Work\n      or a Contribution incorporated within the Work constitutes direct\n      or contributory patent infringement, then any patent licenses\n      granted to You under this License for that Work shall terminate\n      as of the date such litigation is filed.\n\n   4. Redistribution. You may reproduce and distribute copies of the\n      Work or Derivative Works thereof in any medium, with or without\n      modifications, and in Source or Object form, provided that You\n      meet the following conditions:\n\n      (a) You must give any other recipients of the Work or\n          Derivative Works a copy of this License; and\n\n      (b) You must cause any modified files to carry prominent notices\n          stating that You changed the files; and\n\n      (c) You must retain, in the Source form of any Derivative Works\n          that You distribute, all copyright, patent, trademark, and\n          attribution notices from the Source form of the Work,\n          excluding those notices that do not pertain to any part of\n          the Derivative Works; and\n\n      (d) If the Work includes a \"NOTICE\" text file as part of its\n          distribution, then any Derivative Works that You distribute must\n          include a readable copy of the attribution notices contained\n          within such NOTICE file, excluding those notices that do not\n          pertain to any part of the Derivative Works, in at least one\n          of the following places: within a NOTICE text file distributed\n          as part of the Derivative Works; within the Source form or\n          documentation, if provided along with the Derivative Works; or,\n          within a display generated by the Derivative Works, if and\n          wherever such third-party notices normally appear. The contents\n          of the NOTICE file are for informational purposes only and\n          do not modify the License. You may add Your own attribution\n          notices within Derivative Works that You distribute, alongside\n          or as an addendum to the NOTICE text from the Work, provided\n          that such additional attribution notices cannot be construed\n          as modifying the License.\n\n      You may add Your own copyright statement to Your modifications and\n      may provide additional or different license terms and conditions\n      for use, reproduction, or distribution of Your modifications, or\n      for any such Derivative Works as a whole, provided Your use,\n      reproduction, and distribution of the Work otherwise complies with\n      the conditions stated in this License.\n\n   5. Submission of Contributions. Unless You explicitly state otherwise,\n      any Contribution intentionally submitted for inclusion in the Work\n      by You to the Licensor shall be under the terms and conditions of\n      this License, without any additional terms or conditions.\n      Notwithstanding the above, nothing herein shall supersede or modify\n      the terms of any separate license agreement you may have executed\n      with Licensor regarding such Contributions.\n\n   6. Trademarks. This License does not grant permission to use the trade\n      names, trademarks, service marks, or product names of the Licensor,\n      except as required for reasonable and customary use in describing the\n      origin of the Work and reproducing the content of the NOTICE file.\n\n   7. Disclaimer of Warranty. Unless required by applicable law or\n      agreed to in writing, Licensor provides the Work (and each\n      Contributor provides its Contributions) on an \"AS IS\" BASIS,\n      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or\n      implied, including, without limitation, any warranties or conditions\n      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A\n      PARTICULAR PURPOSE. You are solely responsible for determining the\n      appropriateness of using or redistributing the Work and assume any\n      risks associated with Your exercise of permissions under this License.\n\n   8. Limitation of Liability. In no event and under no legal theory,\n      whether in tort (including negligence), contract, or otherwise,\n      unless required by applicable law (such as deliberate and grossly\n      negligent acts) or agreed to in writing, shall any Contributor be\n      liable to You for damages, including any direct, indirect, special,\n      incidental, or consequential damages of any character arising as a\n      result of this License or out of the use or inability to use the\n      Work (including but not limited to damages for loss of goodwill,\n      work stoppage, computer failure or malfunction, or any and all\n      other commercial damages or losses), even if such Contributor\n      has been advised of the possibility of such damages.\n\n   9. Accepting Warranty or Additional Liability. While redistributing\n      the Work or Derivative Works thereof, You may choose to offer,\n      and charge a fee for, acceptance of support, warranty, indemnity,\n      or other liability obligations and/or rights consistent with this\n      License. However, in accepting such obligations, You may act only\n      on Your own behalf and on Your sole responsibility, not on behalf\n      of any other Contributor, and only if You agree to indemnify,\n      defend, and hold each Contributor harmless for any liability\n      incurred by, or claims asserted against, such Contributor by reason\n      of your accepting any such warranty or additional liability.\n\n   END OF TERMS AND CONDITIONS\n\n   APPENDIX: How to apply the Apache License to your work.\n\n      To apply the Apache License to your work, attach the following\n      boilerplate notice, with the fields enclosed by brackets \"[]\"\n      replaced with your own identifying information. (Don't include\n      the brackets!)  The text should be enclosed in the appropriate\n      comment syntax for the file format. We also recommend that a\n      file or class name and description of purpose be included on the\n      same \"printed page\" as the copyright notice for easier\n      identification within third-party archives.\n   Copyright 2024 Alibaba Cloud\n   Licensed under the Apache License, Version 2.0 (the \"License\");\n   you may not use this file except in compliance with the License.\n   You may obtain a copy of the License at\n       http://www.apache.org/licenses/LICENSE-2.0\n   Unless required by applicable law or agreed to in writing, software\n   distributed under the License is distributed on an \"AS IS\" BASIS,\n   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.\n   See the License for the specific language governing permissions and\n   limitations under the License.\"\"\"\n",
            "parameters": "top_p                          0.95\nrepeat_penalty                 1\nstop                           \"\u003c|im_start|\u003e\"\nstop                           \"\u003c|im_end|\u003e\"\ntemperature                    0.6\ntop_k                          20",
            "template": "{{- if .Messages }}\n{{- if or .System .Tools }}\u003c|im_start|\u003esystem\n{{- if .System }}\n{{ .System }}\n{{- end }}\n{{- if .Tools }}\n\n# Tools\n\nYou may call one or more functions to assist with the user query.\n\nYou are provided with function signatures within \u003ctools\u003e\u003c/tools\u003e XML tags:\n\u003ctools\u003e\n{{- range .Tools }}\n{\"type\": \"function\", \"function\": {{ .Function }}}\n{{- end }}\n\u003c/tools\u003e\n\nFor each function call, return a json object with function name and arguments within \u003ctool_call\u003e\u003c/tool_call\u003e XML tags:\n\u003ctool_call\u003e\n{\"name\": \u003cfunction-name\u003e, \"arguments\": \u003cargs-json-object\u003e}\n\u003c/tool_call\u003e\n{{- end }}\u003c|im_end|\u003e\n{{ end }}\n{{- range $i, $_ := .Messages }}\n{{- $last := eq (len (slice $.Messages $i)) 1 -}}\n{{- if eq .Role \"user\" }}\u003c|im_start|\u003euser\n{{ .Content }}\u003c|im_end|\u003e\n{{ else if eq .Role \"assistant\" }}\u003c|im_start|\u003eassistant\n{{ if .Content }}{{ .Content }}\n{{- else if .ToolCalls }}\u003ctool_call\u003e\n{{ range .ToolCalls }}{\"name\": \"{{ .Function.Name }}\", \"arguments\": {{ .Function.Arguments }}}\n{{ end }}\u003c/tool_call\u003e\n{{- end }}{{ if not $last }}\u003c|im_end|\u003e\n{{ end }}\n{{- else if eq .Role \"tool\" }}\u003c|im_start|\u003euser\n\u003ctool_response\u003e\n{{ .Content }}\n\u003c/tool_response\u003e\u003c|im_end|\u003e\n{{ end }}\n{{- if and (ne .Role \"assistant\") $last }}\u003c|im_start|\u003eassistant\n{{ end }}\n{{- end }}\n{{- else }}\n{{- if .System }}\u003c|im_start|\u003esystem\n{{ .System }}\u003c|im_end|\u003e\n{{ end }}{{ if .Prompt }}\u003c|im_start|\u003euser\n{{ .Prompt }}\u003c|im_end|\u003e\n{{ end }}\u003c|im_start|\u003eassistant\n{{ end }}{{ .Response }}{{ if .Response }}\u003c|im_end|\u003e{{ end }}",
            "details": {
                "parent_model": "",
                "format": "gguf",
                "family": "qwen3moe",
                "families": ["qwen3moe"],
                "parameter_size": "235.1B",
                "quantization_level": "Q4_K_M"
            },
            "model_info": {
                "general.architecture": "qwen3moe",
                "general.basename": "Qwen3",
                "general.file_type": 15,
                "general.license": "apache-2.0",
                "general.license.link": "https://huggingface.co/Qwen/Qwen3-235B-A22B/blob/main/LICENSE",
                "general.parameter_count": 235093634560,
                "general.quantization_version": 2,
                "general.size_label": "235B-A22B",
                "general.tags": ["text-generation"],
                "general.type": "model",
                "qwen3moe.attention.head_count": 64,
                "qwen3moe.attention.head_count_kv": 4,
                "qwen3moe.attention.key_length": 128,
                "qwen3moe.attention.layer_norm_rms_epsilon": 0.000001,
                "qwen3moe.attention.value_length": 128,
                "qwen3moe.block_count": 94,
                "qwen3moe.context_length": 40960,
                "qwen3moe.embedding_length": 4096,
                "qwen3moe.expert_count": 128,
                "qwen3moe.expert_feed_forward_length": 1536,
                "qwen3moe.expert_used_count": 8,
                "qwen3moe.feed_forward_length": 12288,
                "qwen3moe.rope.freq_base": 1000000,
                "tokenizer.ggml.bos_token_id": 151643,
                "tokenizer.ggml.eos_token_id": 151645,
                "tokenizer.ggml.model": "gpt2",
                "tokenizer.ggml.padding_token_id": 151643,
                "tokenizer.ggml.pre": "qwen2"
            },
            "tensors": [{
                "name": "output.weight",
                "type": "Q4_K_S",
                "shape": [4096, 151936]
            }, {
                "name": "blk.93.ffn_up_exps.weight",
                "type": "Q3_K_M",
                "shape": [4096, 1536, 128]
            }],
            "capabilities": ["completion", "tools"],
            "modified_at": "2025-04-30T04:22:06.070778397+08:00"
        }

        return response

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
                            # 移除 "data: " 前缀
                            if chunk.startswith("data: "):
                                chunk = chunk[6:]

                            # 跳过 [DONE] 标记
                            if chunk.strip() == "[DONE]":
                                continue

                            data = json.loads(chunk)
                            if "choices" in data and len(data["choices"]) > 0:
                                choice = data["choices"][0]
                                finish_reason = choice.get("finish_reason")

                                # 构建 Ollama 格式的响应
                                current_timestamp = datetime.now(timezone.utc).isoformat()

                                if "delta" in choice and "content" in choice["delta"]:
                                    # 流式内容响应
                                    ollama_response = {
                                        "model": request.model,
                                        "created_at": current_timestamp,
                                        "message": {
                                            "role": "assistant",
                                            "content": choice["delta"]["content"]
                                        },
                                        "done": False
                                    }
                                    yield json.dumps(ollama_response) + "\n"
                                elif finish_reason:
                                    # 最后一条消息，包含统计信息
                                    ollama_response = {
                                        "model": request.model,
                                        "created_at": current_timestamp,
                                        "message": {
                                            "role": "assistant",
                                            "content": ""
                                        },
                                        "done_reason": finish_reason,
                                        "done": True,
                                        "total_duration": 12105404265,
                                        "load_duration": 6092733488,
                                        "prompt_eval_count": 10,
                                        "prompt_eval_duration": 450223496,
                                        "eval_count": 193,
                                        "eval_duration": 5560613051
                                    }
                                    yield json.dumps(ollama_response) + "\n"

                        except json.JSONDecodeError as e:
                            print(f"JSON 解析错误: {e}, chunk: {chunk}")  # 添加日志
                            continue

                # 流式响应结束，OpenAI 会发送 finish_reason，上面已经处理了

            return StreamingResponse(stream_response(), media_type="text/event-stream")
        else:
            # 处理非流式响应
            data = response.json()
            if "choices" in data and len(data["choices"]) > 0:
                current_timestamp = datetime.now(timezone.utc).isoformat()
                return {
                    "model": request.model,
                    "created_at": current_timestamp,
                    "message": {
                        "role": "assistant",
                        "content": data["choices"][0]["message"]["content"]
                    },
                    "done_reason": "stop",
                    "done": True,
                    "total_duration": 12105404265,
                    "load_duration": 6092733488,
                    "prompt_eval_count": 10,
                    "prompt_eval_duration": 450223496,
                    "eval_count": 193,
                    "eval_duration": 5560613051
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

@app.post("/api/embeddings")
async def create_embedding(request: EmbeddingRequest):
    try:
        # 将 Ollama 格式转换为 OpenAI 格式
        openai_body = {
            "model": config.model_mapping.get(request.model, request.model),
            "input": request.prompt
        }

        if request.options:
            # 转换 Ollama 选项到 OpenAI 参数
            if "dimensions" in request.options:
                openai_body["dimensions"] = request.options["dimensions"]

        # 准备请求头
        headers = {
            "Authorization": f"Bearer {config.openai_api_key}",
            "Content-Type": "application/json"
        }

        print(f"发送 embedding 请求到 OpenAI: {openai_body}")  # 添加日志

        # 发送请求到 OpenAI 兼容接口
        response = await client.post(
            f"{config.openai_api_base}/v1/embeddings",
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

        # 处理响应
        data = response.json()
        if "data" in data and len(data["data"]) > 0:
            embeddings = [item["embedding"] for item in data["data"]]
            return {
                "embedding": embeddings[0] if isinstance(request.prompt, str) else embeddings
            }
        else:
            print(f"OpenAI 响应缺少 embeddings: {data}")  # 添加日志
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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)