#!/bin/bash

# 强制卸载所有相关包
pip uninstall -y streamlit rich markdown-it-py mdurl pygments commonmark typing-extensions

# 更新pip到最新版本（优化依赖解析）
pip install --upgrade pip

# 强制安装指定版本，保持 rich 14.0.0 不变
pip install --no-cache-dir --force-reinstall \
    streamlit==1.36.0 \  # 升级streamlit以兼容rich 14+
    PyPDF2==3.0.1 \
    jieba==0.42.1 \
    requests==2.31.0 \
    python-dotenv==1.0.0 \
    numpy==1.25.2 \
    rich==14.0.0 \  # 保持rich版本不变
    markdown-it-py==3.0.0 \  # 适配rich 14.0.0的版本
    mdurl==0.1.2 \
    pygments==2.19.2 \  # 适配rich 14.0.0的版本
    commonmark==0.9.1 \
    typing-extensions==4.8.0
