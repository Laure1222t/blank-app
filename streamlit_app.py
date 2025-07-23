import streamlit as st
import pdfplumber
import requests
import json
import re
from io import BytesIO
from datetime import datetime

# 设置页面配置
st.set_page_config(
    page_title="PDF条款对比分析工具",
    page_icon="📄",
    layout="wide"
)

# 页面标题
st.title("📄 PDF条款对比分析工具")
st.write("上传中文PDF文件，指定基准文件，自动匹配相似条款并分析相似度与合规性")

# 侧边栏 - 模型配置
with st.sidebar:
    st.header("模型配置")
    qwen_api_key = st.text_input("Qwen API 密钥", type="password")
    qwen_api_url = st.text_input("Qwen API 地址", value="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    temperature = st.slider("生成温度", 0.0, 1.0, 0.2)
    max_tokens = st.number_input("最大 tokens", 500, 3000, 2000)
    
    st.divider()
    
    st.header("匹配设置")
    similarity_threshold = st.slider("相似度阈值（仅分析高于此阈值的条款）", 
                                    0.0, 1.0, 0.5, 0.05)
    
    st.divider()
    st.info("提示：请确保已正确配置Qwen API密钥和地址以使用完整功能")

# 工具函数 - 提取PDF文本
@st.cache_data
def extract_text_from_pdf(pdf_file):
    """从PDF文件中提取文本内容"""
    text = ""
    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n\n"
        
        # 清理文本
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    except Exception as e:
        st.error(f"提取PDF文本时出错: {str(e)}")
        return None

# 工具函数 - 调用Qwen API
def call_qwen_api(prompt, api_key, api_url, temperature=0.3, max_tokens=1000):
    """调用Qwen大模型API"""
    if not api_key:
        st.error("请先在侧边栏输入Qwen API密钥")
        return None
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    data = {
        "model": "qwen-plus",  # 可根据需要更换为其他Qwen模型
        "messages": [
            {"role": "system", "content": "你是一位专业的法律条款分析师，擅长识别和对比中文法律文件中的条款，能够准确评估条款之间的相似度和合规性。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    
    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        st.error(f"调用Qwen API时出错: {str(e)}")
        st.text(f"响应内容: {response.text if 'response' in locals() else '无响应'}")
        return None

# 工具函数 - 从文本中提取独立条款
def extract_clauses(text, api_key, api_url, temperature, max_tokens):
    """从文本中提取独立的条款"""
    if not text:
        return None
    
    prompt = f"""
    请从以下文本中提取所有独立的条款，每个条款作为一个单独的条目。
    只提取具有明确规定性、约束性或说明性的内容作为条款。
    忽略无关的描述性文字、标题和格式内容。
    每个条款用数字编号，确保条款的完整性和独立性。
    
    文本内容:
    {text[:3000]}
    
    输出格式:
    1. [条款内容1]
    2. [条款内容2]
    ...
    """
    
    result = call_qwen_api(prompt, api_key, api_url, temperature, max_tokens)
    if result:
        # 简单解析提取的条款
        clauses = []
        for line in result.split('\n'):
            line = line.strip()
            if line.startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.')):
                clause = re.sub(r'^\d+\.\s*', '', line)
                if clause:
                    clauses.append(clause)
        return clauses
    return None

# 工具函数 - 对比条款相似度和合规性
def compare_clauses(base_clauses, base_filename, other_clauses_list, other_filenames,
                   similarity_threshold, api_key, api_url, temperature, max_tokens):
    """对比条款相似度和合规性"""
    if not base_clauses or not other_clauses_list:
        st.warning("请确保已提取基准文件和对比文件的条款")
        return None
    
    # 构建条款对比提示
    prompt = f"""
    作为专业法律条款分析师，请对比分析基准文件与其他文件中的条款。
    只关注相似的条款，忽略未匹配的条款。
    对于每对相似条款，评估它们的相似度（0-100%）和合规性。
    仅分析相似度高于{similarity_threshold*100}%的条款对。
    
    基准文件: {base_filename}
    基准文件条款:
    {chr(10).join([f"{i+1}. {clause}" for i, clause in enumerate(base_clauses[:10])])}  # 限制条款数量
    
    {chr(10).join([
        f"对比文件 {i+1}: {filename}\n条款: {chr(10).join([f"{j+1}. {clause}" for j, clause in enumerate(clauses[:10])])}"
        for i, (filename, clauses) in enumerate(zip(other_filenames, other_clauses_list))
    ])}
    
    请按照以下结构输出分析结果:
    1. 条款匹配概述: 各文件与基准文件的条款匹配数量和总体相似度
    2. 详细条款对比: 对每对相似条款（按相似度从高到低）:
       - 基准条款内容
       - 对比条款内容
       - 相似度评分（0-100%）
       - 合规性分析：说明对比条款是否符合基准条款的要求，存在哪些差异
       - 差异影响：这些差异可能带来的影响和风险
    3. 合规性总结: 各文件相对于基准文件的总体合规性评价
    """
    
    return call_qwen_api(prompt, api_key, api_url, temperature, max_tokens)

# 主界面
def main():
    # 文件上传
    uploaded_files = st.file_uploader(
        "选择要分析的PDF文件（包括基准文件和对比文件）", 
        type="pdf", 
        accept_multiple_files=True
    )
    
    if uploaded_files and len(uploaded_files) >= 2:
        # 选择基准文件
        base_file_index = st.selectbox(
            "选择基准文件",
            options=range(len(uploaded_files)),
            format_func=lambda x: uploaded_files[x].name
        )
        base_file = uploaded_files[base_file_index]
        
        # 显示上传的文件和基准文件信息
        st.subheader("文件信息")
        st.info(f"📌 基准文件: {base_file.name}")
        
        other_files = [f for i, f in enumerate(uploaded_files) if i != base_file_index]
        st.write("对比文件:")
        for file in other_files:
            st.write(f"- {file.name} ({file.size} bytes)")
        
        # 提取文本和条款
        with st.spinner("正在提取PDF文本和条款..."):
            # 提取基准文件文本和条款
            base_file_bytes = BytesIO(base_file.getvalue())
            base_text = extract_text_from_pdf(base_file_bytes)
            
            base_clauses = None
            if base_text:
                with st.expander(f"查看基准文件 {base_file.name} 的文本预览"):
                    st.text_area("", base_text[:1000] + "...", height=200, disabled=True)
                
                # 提取条款
                with st.spinner(f"正在从基准文件 {base_file.name} 中提取条款..."):
                    base_clauses = extract_clauses(
                        base_text, 
                        qwen_api_key,
                        qwen_api_url,
                        temperature,
                        max_tokens
                    )
                
                if base_clauses:
                    st.success(f"从基准文件 {base_file.name} 中提取到 {len(base_clauses)} 条条款")
                    with st.expander("查看提取的基准条款"):
                        for i, clause in enumerate(base_clauses[:10]):  # 只显示前10条
                            st.write(f"{i+1}. {clause}")
                        if len(base_clauses) > 10:
                            st.write(f"... 共 {len(base_clauses)} 条条款")
                else:
                    st.warning(f"无法从基准文件 {base_file.name} 中提取条款")
                    return
            else:
                st.warning(f"无法从基准文件 {base_file.name} 中提取文本")
                return
            
            # 提取其他文件文本和条款
            other_clauses_list = []
            other_filenames = []
            
            for file in other_files:
                other_filenames.append(file.name)
                
                file_bytes = BytesIO(file.getvalue())
                text = extract_text_from_pdf(file_bytes)
                
                if text:
                    with st.expander(f"查看对比文件 {file.name} 的文本预览"):
                        st.text_area("", text[:1000] + "...", height=200, disabled=True)
                    
                    # 提取条款
                    with st.spinner(f"正在从对比文件 {file.name} 中提取条款..."):
                        clauses = extract_clauses(
                            text, 
                            qwen_api_key,
                            qwen_api_url,
                            temperature,
                            max_tokens
                        )
                    
                    if clauses:
                        other_clauses_list.append(clauses)
                        st.success(f"从对比文件 {file.name} 中提取到 {len(clauses)} 条条款")
                        with st.expander(f"查看提取的 {file.name} 条款"):
                            for i, clause in enumerate(clauses[:10]):  # 只显示前10条
                                st.write(f"{i+1}. {clause}")
                            if len(clauses) > 10:
                                st.write(f"... 共 {len(clauses)} 条条款")
                    else:
                        st.warning(f"无法从对比文件 {file.name} 中提取条款")
                else:
                    st.warning(f"无法从对比文件 {file.name} 中提取文本")
        
        # 分析按钮
        if st.button("开始条款对比分析", disabled=not (base_clauses and other_clauses_list)):
            with st.spinner("正在进行条款相似度和合规性分析，请稍候..."):
                # 进行条款对比分析
                st.subheader(f"📊 条款相似度与合规性对比分析结果")
                comparison_result = compare_clauses(
                    base_clauses,
                    base_file.name,
                    other_clauses_list,
                    other_filenames,
                    similarity_threshold,
                    qwen_api_key,
                    qwen_api_url,
                    temperature,
                    max_tokens
                )
                
                if comparison_result:
                    st.write(comparison_result)
                    
                    # 提供下载结果选项
                    st.download_button(
                        label="下载条款对比分析结果",
                        data=comparison_result,
                        file_name=f"{base_file.name}_条款对比分析_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                        mime="text/plain"
                    )
    
    elif uploaded_files and len(uploaded_files) == 1:
        st.warning("请至少上传两个文件（一个作为基准文件，一个作为对比文件）")
    
    # 页面底部信息
    st.divider()
    st.caption("注意：本工具仅提供初步分析参考，不构成法律意见。重要合规性问题请咨询专业法律人士。")

if __name__ == "__main__":
    main()
    
