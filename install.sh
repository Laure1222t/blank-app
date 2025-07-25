#!/bin/bash

# 升级pip到最新版本
pip install --upgrade pip

# 先卸载可能冲突的包
pip uninstall -y streamlit rich pdf2image

# 按兼容顺序安装
pip install rich==13.7.1
pip install streamlit==1.35.0
pip install pdf2image==1.17.0
pip install PyPDF2==3.0.1 requests==2.31.0 jieba==0.42.1
pip install python-dotenv==1.0.0 pytesseract==0.3.10 Pillow==10.2.0 numpy==1.26.4

# 安装系统依赖（适用于Debian/Ubuntu系统）
sudo apt-get update
sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-chi-sim
    
