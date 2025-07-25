# 先卸载冲突的rich版本
pip uninstall -y rich

# 再重新安装所有依赖
pip install -r requirements.txt
