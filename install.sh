#!/bin/bash

# 确保apt包管理器是最新的
sudo apt-get update -y
sudo apt-get upgrade -y

# 安装pdf2image所需的系统级依赖
sudo apt-get install -y poppler-utils libpoppler-cpp-dev

# 安装Python工具和相关库
sudo apt-get install -y python3 python3-pip python3-dev build-essential

# 升级pip到最新版本
pip install --upgrade pip

# 彻底清理可能冲突的包
pip uninstall -y streamlit rich pdf2image pytesseract Pillow

# 按顺序安装Python依赖，先解决版本冲突
pip install --no-cache-dir rich==13.7.1
pip install --no-cache-dir streamlit==1.35.0

# 专门处理pdf2image的安装
pip install --no-cache-dir pdf2image==1.17.0

# 安装其他依赖
pip install --no-cache-dir PyPDF2==3.0.1
pip install --no-cache-dir requests==2.31.0
pip install --no-cache-dir jieba==0.42.1
pip install --no-cache-dir python-dotenv==1.0.0
pip install --no-cache-dir pytesseract==0.3.10
pip install --no-cache-dir Pillow==10.2.0
pip install --no-cache-dir numpy==1.26.4

# 安装OCR所需的系统依赖
sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim

# 验证安装
echo "验证关键包版本..."
pip show rich | grep Version
pip show streamlit | grep Version
pip show pdf2image | grep Version

echo "安装完成！可以通过以下命令启动应用："
echo "streamlit run streamlit_app.py"
    
