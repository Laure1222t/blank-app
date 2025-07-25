#!/bin/bash

# 确保脚本在出错时退出
set -e

# 打印欢迎信息
echo "📦 开始安装 Qwen 中文PDF条款合规性分析工具依赖..."

# 更新系统包（针对Debian/Ubuntu系统）
if [ -f /etc/debian_version ]; then
    echo "🔄 更新系统包列表..."
    sudo apt update -y
    sudo apt upgrade -y
fi

# 检查并安装Python3及相关工具
if ! command -v python3 &> /dev/null; then
    echo "🐍 安装Python3..."
    sudo apt install -y python3 python3-pip python3-venv
fi

# 创建并激活虚拟环境
echo "🌱 创建虚拟环境..."
python3 -m venv venv
source venv/bin/activate

# 升级pip
echo "🔧 升级pip..."
pip install --upgrade pip

# 安装依赖包
if [ -f "requirements.txt" ]; then
    echo "📚 安装项目依赖..."
    pip install -r requirements.txt
else
    echo "⚠️ 未找到requirements.txt，使用默认依赖安装..."
    pip install streamlit==1.35.0 PyPDF2==3.0.1 requests==2.31.0 jieba==0.42.1 python-dotenv==1.0.0
fi

# 检查是否安装成功
if command -v streamlit &> /dev/null; then
    echo "✅ 依赖安装完成！"
    echo "▶️ 启动命令: source venv/bin/activate && streamlit run streamlit_app.py"
else
    echo "❌ 安装失败，请检查错误信息并重试"
    exit 1
fi
