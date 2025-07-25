import streamlit as st
from PyPDF2 import PdfReader
from difflib import SequenceMatcher
import base64
import re
import requests
import jieba
import time

# 设置页面标题和图标
st.set_page_config(
    page_title="Qwen 中文PDF条款合规性分析工具",
    page_icon="📄",
    layout="wide"
)

# 自定义CSS样式
st.markdown("""
<style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .highlight-conflict { background-color: #ffeeba; padding: 2px 4px; border-radius: 3px; }
    .clause-box { border-left: 4px solid #007bff; padding: 10px; margin: 10px 0; background-color: #f8f9fa; }
    .model-response { background-color: #f0f2f6; padding: 15px; border-radius: 5px; margin: 10px 0; }
    .section-header { background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin: 15px 0; }
</style>
""", unsafe_allow_html=True)

# 配置Qwen API参数
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

def call_qwen_api(prompt, api_key, retry=2):
    """调用Qwen大模型API，带重试机制"""
    if not api_key:
        st.error("Qwen API密钥未设置，请在左侧栏输入密钥")
        return None
        
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        data = {
            "model": "qwen-plus",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 1000
        }
        
        # 带重试机制的API调用
        for attempt in range(retry):
            try:
                response = requests.post(
                    QWEN_API_URL,
                    headers=headers,
                    json=data,
                    timeout=60
                )
                
                if response.status_code == 200:
                    response_json = response.json()
                    if "choices" in response_json and len(response_json["choices"]) > 0:
                        return response_json["choices"][0]["message"]["content"]
                time.sleep(2 **attempt)  # 指数退避
                
            except Exception as e:
                if attempt == retry - 1:
                    st.error(f"API调用失败: {str(e)}")
                
        return None
        
    except Exception as e:
        st.error(f"调用Qwen API失败: {str(e)}")
        return None

def extract_text_from_pdf(file, progress_bar=None):
    """从PDF提取文本"""
    try:
        pdf_reader = PdfReader(file)
        text = ""
        total_pages = len(pdf_reader.pages)
        
        for i, page in enumerate(pdf_reader.pages):
            page_text = page.extract_text() or ""
            # 处理中文空格和换行问题
            page_text = page_text.replace("  ", "").replace("\n", "").replace("\r", "")
            text += page_text
            
            # 更新进度条
            if progress_bar is not None:
                progress = (i + 1) / total_pages
                progress_bar.progress(progress)
        
        return text
    except Exception as e:
        st.error(f"提取文本失败: {str(e)}")
        return ""

def split_into_clauses(text, doc_name="文档"):
    """将文本分割为条款，简化版"""
    # 简化的条款分割模式
    patterns = [
        r'(第[一二三四五六七八九十百]+条\s*[:：]?\s*.*?)(?=第[一二三四五六七八九十百]+条\s*[:：]?\s*|$)',
        r'([一二三四五六七八九十]+、\s*.*?)(?=[一二三四五六七八九十]+、\s*|$)',
        r'(\d+\.\s*.*?)(?=\d+\.\s*|$)',
    ]
    
    # 尝试各种模式，找到最佳分割
    best_clauses = []
    for pattern in patterns:
        clauses = re.findall(pattern, text, re.DOTALL)
        # 过滤过短条款
        clauses = [clause.strip() for clause in clauses if clause.strip() and len(clause.strip()) > 10]
        if len(clauses) > len(best_clauses) and len(clauses) > 2:
            best_clauses = clauses
    
    # 如果找到足够的条款，返回结果
    if best_clauses:
        return best_clauses
    
    # 尝试段落分割作为备选方案
    paragraphs = re.split(r'[。；！？]\s*', text)
    return [p.strip() for p in paragraphs if p.strip() and len(p) > 10]

def chinese_text_similarity(text1, text2):
    """计算中文文本相似度，简化版"""
    # 过滤标点符号和空格
    text1_clean = re.sub(r'[^\w\s]', '', text1)
    text2_clean = re.sub(r'[^\w\s]', '', text2)
    
    # 使用jieba进行中文分词
    words1 = list(jieba.cut(text1_clean))
    words2 = list(jieba.cut(text2_clean))
    
    # 计算分词后的相似度
    return SequenceMatcher(None, words1, words2).ratio()

def match_clauses(clauses1, clauses2, progress_container=None):
    """匹配两个文档中的相似条款，简化版匹配算法"""
    matched_pairs = []
    used_indices = set()
    total = len(clauses1)
    
    for i, clause1 in enumerate(clauses1):
        # 更新进度
        if progress_container is not None:
            progress = (i + 1) / total
            with progress_container:
                st.progress(progress)
        
        best_match = None
        best_ratio = 0.25  # 基础阈值
        best_j = -1
        
        # 只检查未匹配的条款
        candidates = [j for j in range(len(clauses2)) if j not in used_indices]
        
        # 计算相似度
        for j in candidates:
            ratio = chinese_text_similarity(clause1, clauses2[j])
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = clauses2[j]
                best_j = j
        
        if best_match:
            matched_pairs.append((clause1, best_match, best_ratio))
            used_indices.add(best_j)
    
    # 处理未匹配的条款
    unmatched1 = [clause for i, clause in enumerate(clauses1) 
                 if i not in [idx for idx, _ in enumerate(matched_pairs)]]
    unmatched2 = [clause for j, clause in enumerate(clauses2) if j not in used_indices]
    
    return matched_pairs, unmatched1, unmatched2

def create_download_link(content, filename, text):
    """生成下载链接"""
    b64 = base64.b64encode(content.encode()).decode()
    return f'<a href="data:file/txt;base64,{b64}" download="{filename}">{text}</a>'

def analyze_compliance_with_qwen(clause1, clause2, filename1, filename2, api_key):
    """使用Qwen大模型分析条款合规性，简化提示词"""
    prompt = f"""
    请分析以下两个条款是否存在冲突：
    
    {filename1} 条款：{clause1}
    {filename2} 条款：{clause2}
    
    请用中文简要分析：
    1. 相似度评估（高/中/低）
    2. 主要差异点
    3. 合规性判断（无冲突/轻微冲突/严重冲突）
    4. 简要建议
    """
    
    return call_qwen_api(prompt, api_key)

def analyze_single_comparison(base_clauses, compare_text, base_name, compare_name, api_key):
    """分析单个对比文件与基准文件的合规性，简化版"""
    # 分割对比文件条款
    with st.spinner(f"正在分析 {compare_name} 的条款..."):
        compare_clauses = split_into_clauses(compare_text, compare_name)
        st.success(f"{compare_name} 识别出 {len(compare_clauses)} 条条款")
    
    # 匹配条款，显示进度
    progress_container = st.empty()
    with st.spinner(f"正在匹配条款..."):
        matched_pairs, unmatched_base, unmatched_compare = match_clauses(
            base_clauses, 
            compare_clauses,
            progress_container
        )
    progress_container.empty()
    
    # 显示总体统计
    st.divider()
    col1, col2, col3 = st.columns(3)
    col1.metric(f"{base_name} 条款数", len(base_clauses))
    col2.metric(f"{compare_name} 条款数", len(compare_clauses))
    col3.metric("匹配条款数", len(matched_pairs))
    
    # 显示条款对比和合规性分析
    st.divider()
    st.subheader(f"条款合规性分析")
    
    # 创建分析结果的标签页导航
    tab_labels = ["匹配条款"]
    if len(unmatched_base) > 0:
        tab_labels.append(f"{base_name} 独有条款")
    if len(unmatched_compare) > 0:
        tab_labels.append(f"{compare_name} 独有条款")
    
    tabs = st.tabs(tab_labels)
    tab_idx = 0
    
    # 分析每个匹配对的合规性
    with tabs[tab_idx]:
        tab_idx += 1
        
        # 添加筛选功能
        min_similarity = st.slider("最低相似度筛选", 0.0, 1.0, 0.0, 0.05)
        filtered_pairs = [p for p in matched_pairs if p[2] >= min_similarity]
        
        st.write(f"显示 {len(filtered_pairs)} 个匹配项")
        
        for i, (clause1, clause2, ratio) in enumerate(filtered_pairs):
            # 根据相似度设置不同颜色标识
            if ratio > 0.7:
                similarity_color = "#28a745"  # 绿色 - 高相似度
                similarity_label = "高相似度"
            elif ratio > 0.4:
                similarity_color = "#ffc107"  # 黄色 - 中相似度
                similarity_label = "中相似度"
            else:
                similarity_color = "#dc3545"  # 红色 - 低相似度
                similarity_label = "低相似度"
            
            st.markdown(f"### 匹配条款对 {i+1}")
            st.markdown(f'<span style="color:{similarity_color};font-weight:bold">{similarity_label}: {ratio:.2%}</span>', unsafe_allow_html=True)
            
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f'<div class="clause-box"><strong>{base_name} 条款:</strong><br>{clause1}</div>', unsafe_allow_html=True)
            with col_b:
                st.markdown(f'<div class="clause-box"><strong>{compare_name} 条款:</strong><br>{clause2}</div>', unsafe_allow_html=True)
            
            # 添加分析结果折叠框
            with st.expander("查看合规性分析", expanded=False):
                with st.spinner("正在分析..."):
                    analysis = analyze_compliance_with_qwen(clause1, clause2, base_name, compare_name, api_key)
                
                if analysis:
                    st.markdown('<div class="model-response">' + analysis + '</div>', unsafe_allow_html=True)
                else:
                    st.warning("未能获取分析结果")
            
            st.divider()
    
    # 未匹配的条款分析 - 基准文件独有
    if len(unmatched_base) > 0 and tab_idx < len(tabs):
        with tabs[tab_idx]:
            tab_idx += 1
            st.markdown(f"#### {base_name} 中独有的条款 ({len(unmatched_base)})")
            st.text_area("条款内容", unmatched_base[0] if unmatched_base else "", height=200)
    
    # 未匹配的条款分析 - 对比文件独有
    if len(unmatched_compare) > 0 and tab_idx < len(tabs):
        with tabs[tab_idx]:
            tab_idx += 1
            st.markdown(f"#### {compare_name} 中独有的条款 ({len(unmatched_compare)})")
            st.text_area("条款内容", unmatched_compare[0] if unmatched_compare else "", height=200)

# 应用主界面
st.title("📄 中文PDF条款合规性分析工具")
st.markdown("简化版条款对比分析工具")

# Qwen API设置
with st.sidebar:
    st.subheader("Qwen API 设置")
    qwen_api_key = st.text_input("请输入Qwen API密钥", type="password")
    st.markdown(f"API端点：`{QWEN_API_URL}`")

with st.form("upload_form"):
    st.subheader("基准文件")
    base_file = st.file_uploader("选择基准PDF文件", type=["pdf"], key="base_file")
    
    st.subheader("对比文件")
    compare_files = st.file_uploader(
        "选择需要对比的PDF文件", 
        type=["pdf"], 
        key="compare_files",
        accept_multiple_files=True
    )
    
    submitted = st.form_submit_button("开始分析")

if submitted and base_file and compare_files:
    # 创建总体进度跟踪
    overall_progress = st.progress(0)
    total_steps = 1 + len(compare_files) * 2  # 基准文件处理 + 每个对比文件的2个步骤
    current_step = 0
    
    with st.spinner("正在解析基准PDF内容..."):
        # 显示基准文件处理进度
        progress_bar = st.progress(0)
        base_text = extract_text_from_pdf(base_file, progress_bar)
        progress_bar.empty()
        
        current_step += 1
        overall_progress.progress(current_step / total_steps)
        
        if not base_text:
            st.error("无法提取基准文件的文本内容")
        else:
            st.success(f"基准文件 {base_file.name} 文本提取完成")
            
            # 解析基准文件条款
            base_clauses = split_into_clauses(base_text, base_file.name)
            st.success(f"基准文件条款解析完成，共识别出 {len(base_clauses)} 条条款")
            
            # 对每个对比文件进行分析
            for i, compare_file in enumerate(compare_files, 1):
                st.markdown(f"## 分析 {i}/{len(compare_files)}: {compare_file.name}")
                
                # 提取对比文件文本
                with st.spinner(f"正在提取 {compare_file.name} 的文本..."):
                    progress_bar = st.progress(0)
                    compare_text = extract_text_from_pdf(compare_file, progress_bar)
                    progress_bar.empty()
                
                current_step += 1
                overall_progress.progress(current_step / total_steps)
                
                if not compare_text:
                    st.error(f"无法提取 {compare_file.name} 的文本内容，跳过该文件")
                    continue
                
                # 分析当前对比文件与基准文件
                analyze_single_comparison(
                    base_clauses, 
                    compare_text, 
                    base_file.name, 
                    compare_file.name, 
                    qwen_api_key
                )
                
                current_step += 1
                overall_progress.progress(current_step / total_steps)
                
                st.markdown("---")
        
        # 完成所有分析
        overall_progress.empty()
        st.success("所有文档分析已完成！")
        
elif submitted:
    if not base_file:
        st.error("请上传基准PDF文件")
    if not compare_files:
        st.error("请至少上传一个对比PDF文件")
else:
    st.info('请上传一个基准PDF文件和至少一个对比PDF文件，然后点击"开始分析"按钮')

# 添加页脚
st.divider()
st.markdown("""
<div style="text-align: center; color: #666; margin-top: 2rem;">
    中文PDF条款合规性分析工具 | 简化版
</div>
""", unsafe_allow_html=True)
