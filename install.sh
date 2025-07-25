#!/bin/bash

# 强制卸载所有相关包
pip uninstall -y streamlit rich markdown-it-py mdurl pygments commonmark typing-extensions

# 更新pip到最新版本
pip install --upgrade pip

# 强制安装指定版本，忽略缓存和已有安装
pip install --no-cache-dir --force-reinstall \
    streamlit==1.35.0 \
    PyPDF2==3.0.1 \
    jieba==0.42.1 \
    requests==2.31.0 \
    python-dotenv==1.0.0 \
    numpy==1.25.2 \
    rich==13.7.1 \
    markdown-it-py==2.2.0 \
    mdurl==0.1.2 \
    pygments==2.16.1 \
    commonmark==0.9.1 \
    typing-extensions==4.8.0
    
