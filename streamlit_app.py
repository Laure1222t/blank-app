import streamlit as st
import pdfplumber
import requests
import json
import re
from io import BytesIO
from datetime import datetime

# 设置页面配置
st.set_page_config(
    page_title="PDF条款合规性分析工具",
    page_icon="📄",
    layout="wide"
)

# 页面标题
st.title("📄 PDF条款合规性分析工具")
st.write("上传中文PDF文件，指定一个基准文件，分析其他文件与基准文件的条款合规性差异")

# 侧边栏 - 模型配置
with st.sidebar:
    st.header("模型配置")
    qwen_api_key = st.text_input("Qwen API 密钥", type="password")
    qwen_api_url = st.text_input("Qwen API 地址", value="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    temperature = st.slider("生成温度", 0.0, 1.0, 0.3)
    max_tokens = st.number_input("最大 tokens", 100, 2000, 1500)
    
    st.divider()
    
    st.header("合规性设置")
    compliance_standard = st.text_area(
        "合规性标准（请输入评估依据的法规、标准等）",
        value="中华人民共和国相关法律法规，包括但不限于《民法典》《合同法》等"
    )
    
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
            {"role": "system", "content": "你是一位专业的法律合规分析师，擅长分析中文法律文件和条款的合规性。你的任务是比较不同文件的条款，专注于合规性方面的异同。"},
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

# 工具函数 - 分析单个文件的合规性
def analyze_single_file_compliance(text, compliance_standard, api_key, api_url, temperature, max_tokens):
    """分析单个文件的条款合规性"""
    if not text:
        return None
    
    # 构建提示词，专注于条款合规性分析，忽略无关内容
    prompt = f"""
    请分析以下文本中与条款相关的内容是否符合指定的合规性标准。
    只关注与条款相关的内容，忽略无关条款和信息。
    对于不符合合规性标准的条款，请指出具体问题和可能的风险。
    
    合规性标准:
    {compliance_standard}
    
    文本内容:
    {text[:3000]}  # 限制输入长度，避免超过模型限制
    
    请按照以下结构输出分析结果:
    1. 合规条款总结: 列出符合合规性标准的主要条款
    2. 不合规条款分析: 列出不符合标准的条款，每个条款说明具体问题和风险
    3. 总体合规性评估: 对文件的整体合规性给出评价
    """
    
    return call_qwen_api(prompt, api_key, api_url, temperature, max_tokens)

# 工具函数 - 以一个文件为基准，对比分析其他多个文件
def compare_with_base_file(base_text, base_filename, other_texts, other_filenames, compliance_standard, 
                          api_key, api_url, temperature, max_tokens):
    """以一个基准文件为参考，对比分析其他多个文件的条款合规性"""
    if not base_text or len(other_texts) == 0:
        st.warning("请确保已选择基准文件并至少选择一个对比文件")
        return None
    
    # 构建基准文件摘要
    base_summary = f"基准文件: {base_filename}\n主要条款摘要: {base_text[:800]}..."
    
    # 构建其他文件摘要
    other_summaries = []
    for i, (text, filename) in enumerate(zip(other_texts, other_filenames)):
        other_summaries.append(f"对比文件 {i+1}: {filename}\n主要条款摘要: {text[:500]}...")
    
    # 构建提示词
    prompt = f"""
    请以基准文件为参考，对比分析其他{len(other_texts)}个文件中与条款相关的内容在合规性方面的异同。
    只关注与条款相关的内容，忽略无关条款和信息。
    重点分析它们在符合指定合规性标准方面与基准文件的差异，以及各自的合规风险。
    
    合规性标准:
    {compliance_standard}
    
    基准文件内容摘要:
    {base_summary}
    
    其他文件内容摘要:
    {chr(10).join(other_summaries)}
    
    请按照以下结构输出对比分析结果:
    1. 合规性一致性: 各文件与基准文件在合规性方面的共同之处
    2. 合规性差异点: 各文件与基准文件在合规性方面的不同之处，包括更严格或更宽松的条款
    3. 合规风险对比: 各文件相对于基准文件的合规风险评估
    4. 条款匹配度: 各文件与基准文件条款的匹配程度和偏离情况
    5. 总体评估: 对各文件相对于基准文件的合规性综合评价
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
        
        # 提取文本
        with st.spinner("正在提取PDF文本..."):
            # 提取基准文件文本
            base_file_bytes = BytesIO(base_file.getvalue())
            base_text = extract_text_from_pdf(base_file_bytes)
            
            if base_text:
                with st.expander(f"查看基准文件 {base_file.name} 的文本预览"):
                    st.text_area("", base_text[:1000] + "...", height=200, disabled=True)
            else:
                st.warning(f"无法从基准文件 {base_file.name} 中提取文本")
                return
            
            # 提取其他文件文本
            other_texts = []
            other_filenames = []
            for file in other_files:
                other_filenames.append(file.name)
                
                file_bytes = BytesIO(file.getvalue())
                text = extract_text_from_pdf(file_bytes)
                
                if text:
                    other_texts.append(text)
                    with st.expander(f"查看对比文件 {file.name} 的文本预览"):
                        st.text_area("", text[:1000] + "...", height=200, disabled=True)
                else:
                    st.warning(f"无法从对比文件 {file.name} 中提取文本")
        
        # 分析按钮
        if st.button("开始合规性对比分析", disabled=not (base_text and other_texts)):
            with st.spinner("正在进行合规性对比分析，请稍候..."):
                # 先显示基准文件的合规性分析
                st.subheader(f"📊 基准文件 {base_file.name} 的合规性分析")
                base_result = analyze_single_file_compliance(
                    base_text, 
                    compliance_standard,
                    qwen_api_key,
                    qwen_api_url,
                    temperature,
                    max_tokens
                )
                if base_result:
                    st.write(base_result)
                    st.divider()
                
                # 显示各对比文件的单独分析
                with st.expander("查看各对比文件的单独合规性分析", expanded=False):
                    for text, filename in zip(other_texts, other_filenames):
                        st.subheader(f"{filename} 的合规性分析")
                        result = analyze_single_file_compliance(
                            text, 
                            compliance_standard,
                            qwen_api_key,
                            qwen_api_url,
                            temperature,
                            max_tokens
                        )
                        if result:
                            st.write(result)
                        st.divider()
                
                # 显示与基准文件的对比分析
                st.subheader(f"📊 与基准文件 {base_file.name} 的合规性对比分析")
                comparison_result = compare_with_base_file(
                    base_text,
                    base_file.name,
                    other_texts,
                    other_filenames,
                    compliance_standard,
                    qwen_api_key,
                    qwen_api_url,
                    temperature,
                    max_tokens
                )
                
                if comparison_result:
                    st.write(comparison_result)
                    
                    # 提供下载结果选项
                    st.download_button(
                        label="下载对比分析结果",
                        data=comparison_result,
                        file_name=f"与{base_file.name}_的合规性对比分析_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                        mime="text/plain"
                    )
    
    elif uploaded_files and len(uploaded_files) == 1:
        st.warning("请至少上传两个文件（一个作为基准文件，一个作为对比文件）")
    
    # 页面底部信息
    st.divider()
    st.caption("注意：本工具仅提供初步分析参考，不构成法律意见。重要合规性问题请咨询专业法律人士。")

if __name__ == "__main__":
    main()
    
