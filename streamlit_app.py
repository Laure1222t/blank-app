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
st.write("上传中文PDF文件，分析条款合规性，并支持多文件对比分析")

# 侧边栏 - 模型配置
with st.sidebar:
    st.header("模型配置")
    qwen_api_key = st.text_input("Qwen API 密钥", type="password")
    qwen_api_url = st.text_input("Qwen API 地址", value="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    temperature = st.slider("生成温度", 0.0, 1.0, 0.3)
    max_tokens = st.number_input("最大 tokens", 100, 2000, 1000)
    
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
            {"role": "system", "content": "你是一位专业的法律合规分析师，擅长分析中文法律文件和条款的合规性。"},
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

# 工具函数 - 分析单文件合规性
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

# 工具函数 - 对比分析多个文件
def compare_multiple_files(texts, filenames, compliance_standard, api_key, api_url, temperature, max_tokens):
    """对比分析多个文件的条款合规性"""
    if len(texts) < 2:
        st.warning("至少需要两个文件进行对比分析")
        return None
    
    # 构建文件内容摘要
    file_summaries = []
    for i, (text, filename) in enumerate(zip(texts, filenames)):
        file_summaries.append(f"文件 {i+1}: {filename}\n主要条款摘要: {text[:500]}...")
    
    # 构建提示词
    prompt = f"""
    请对比分析以下{len(texts)}个文件中与条款相关的内容在合规性方面的异同。
    只关注与条款相关的内容，忽略无关条款和信息。
    重点分析它们在符合和不符合指定合规性标准方面的差异。
    
    合规性标准:
    {compliance_standard}
    
    文件内容摘要:
    {chr(10).join(file_summaries)}
    
    请按照以下结构输出对比分析结果:
    1. 合规性共同点: 所有文件在合规性方面的共同之处
    2. 合规性差异点: 各文件在合规性方面的不同之处
    3. 合规风险对比: 各文件面临的合规风险比较
    4. 总体对比结论: 对各文件的合规性进行综合评价和排序
    """
    
    return call_qwen_api(prompt, api_key, api_url, temperature, max_tokens)

# 主界面
def main():
    # 文件上传
    uploaded_files = st.file_uploader(
        "选择要分析的PDF文件", 
        type="pdf", 
        accept_multiple_files=True
    )
    
    if uploaded_files:
        # 显示上传的文件
        st.subheader("已上传文件")
        for file in uploaded_files:
            st.write(f"- {file.name} ({file.size} bytes)")
        
        # 提取文本
        with st.spinner("正在提取PDF文本..."):
            texts = []
            filenames = []
            for file in uploaded_files:
                # 保存文件名
                filenames.append(file.name)
                
                # 提取文本
                file_bytes = BytesIO(file.getvalue())
                text = extract_text_from_pdf(file_bytes)
                
                if text:
                    texts.append(text)
                    # 显示提取的文本预览
                    with st.expander(f"查看 {file.name} 的文本预览"):
                        st.text_area("", text[:1000] + "...", height=200, disabled=True)
                else:
                    st.warning(f"无法从 {file.name} 中提取文本")
        
        # 分析按钮
        if st.button("开始分析合规性", disabled=not texts):
            with st.spinner("正在分析合规性，请稍候..."):
                # 单文件分析
                if len(texts) == 1:
                    st.subheader(f"📊 {filenames[0]} 的合规性分析结果")
                    result = analyze_single_file_compliance(
                        texts[0], 
                        compliance_standard,
                        qwen_api_key,
                        qwen_api_url,
                        temperature,
                        max_tokens
                    )
                    
                    if result:
                        st.write(result)
                        
                        # 提供下载结果选项
                        st.download_button(
                            label="下载分析结果",
                            data=result,
                            file_name=f"{filenames[0]}_合规性分析_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                            mime="text/plain"
                        )
                
                # 多文件对比分析
                else:
                    st.subheader("📊 多文件合规性对比分析结果")
                    
                    # 先显示各文件的单独分析
                    with st.expander("查看各文件单独分析结果", expanded=False):
                        for text, filename in zip(texts, filenames):
                            st.subheader(f"{filename} 的分析")
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
                    
                    # 再显示对比分析
                    comparison_result = compare_multiple_files(
                        texts, 
                        filenames,
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
                            file_name=f"多文件合规性对比分析_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                            mime="text/plain"
                        )
    
    # 页面底部信息
    st.divider()
    st.caption("注意：本工具仅提供初步分析参考，不构成法律意见。重要合规性问题请咨询专业法律人士。")

if __name__ == "__main__":
    main()
