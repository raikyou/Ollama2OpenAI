#!/bin/bash

# 获取最新的版本号
latest_version=$(git tag -l "v*" | sort -V | tail -n 1)

if [ -z "$latest_version" ]; then
    latest_version="v1.0.0"
fi

# 提取版本号各个部分
major=$(echo $latest_version | cut -d. -f1 | tr -d 'v')
minor=$(echo $latest_version | cut -d. -f2)
patch=$(echo $latest_version | cut -d. -f3)

# 增加补丁版本号
new_patch=$((patch + 1))
new_version="v$major.$minor.$new_patch"

# 创建新的 Git 标签
git tag -a $new_version -m "🔖 Release $new_version"
git push origin $new_version

# 构建并推送 Docker 镜像
docker build -t lynricsy/ollama2openai:$new_version .
docker tag lynricsy/ollama2openai:$new_version lynricsy/ollama2openai:latest
docker push lynricsy/ollama2openai:$new_version
docker push lynricsy/ollama2openai:latest

echo "✨ 版本已更新到 $new_version"
echo "✅ Docker 镜像已推送到 Docker Hub" 