import streamlit as st
from PyPDF2 import PdfReader
from difflib import SequenceMatcher
import base64
import re
import requests
import jieba
import hashlib
import time
from functools import lru_cache
from collections import defaultdict

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
    .stFileUploader { width: 100%; }
    .highlight-conflict { background-color: #ffeeba; padding: 2px 4px; border-radius: 3px; }
    .clause-box { border-left: 4px solid #007bff; padding: 10px; margin: 10px 0; background-color: #f8f9fa; }
    .compliance-ok { border-left: 4px solid #28a745; }
    .compliance-warning { border-left: 4px solid #ffc107; }
    .compliance-conflict { border-left: 4px solid #dc3545; }
    .model-response { background-color: #f0f2f6; padding: 15px; border-radius: 5px; margin: 10px 0; }
    .processing-bar { background-color: #e9ecef; border-radius: 5px; padding: 3px; margin: 10px 0; }
    .processing-progress { background-color: #007bff; height: 10px; border-radius: 3px; }
    .section-header { background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin: 15px 0; }
</style>
""", unsafe_allow_html=True)

# 配置Qwen API参数
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# 缓存管理
cache = defaultdict(dict)

def get_cache_key(*args):
    """生成缓存键"""
    return hashlib.md5(str(args).encode()).hexdigest()

def cached_func(func):
    """函数缓存装饰器"""
    def wrapper(*args, **kwargs):
        key = get_cache_key(args, kwargs)
        if key in cache[func.__name__]:
            return cache[func.__name__][key]
        result = func(*args, **kwargs)
        cache[func.__name__][key] = result
        return result
    return wrapper

@cached_func
def call_qwen_api(prompt, api_key, retry=3):
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
            "max_tokens": 4000
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
                    else:
                        st.warning(f"API返回格式不符合预期 (尝试 {attempt+1}/{retry})")
                else:
                    st.warning(f"API请求失败，状态码: {response.status_code} (尝试 {attempt+1}/{retry})")
                
                time.sleep(2** attempt)  # 指数退避
                
            except requests.exceptions.Timeout:
                st.warning(f"API请求超时 (尝试 {attempt+1}/{retry})")
                time.sleep(2 **attempt)
            except Exception as e:
                st.warning(f"API调用异常: {str(e)} (尝试 {attempt+1}/{retry})")
                time.sleep(2** attempt)
                
        st.error("API调用多次失败，请稍后重试")
        return None
        
    except Exception as e:
        st.error(f"调用Qwen API失败: {str(e)}")
        return None

def extract_text_from_pdf(file, progress_bar=None):
    """从PDF提取文本，支持大文件处理和进度显示"""
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
                progress_bar.text(f"提取文本: 第 {i+1}/{total_pages} 页")
        
        return text
    except Exception as e:
        st.error(f"提取文本失败: {str(e)}")
        return ""

def split_into_clauses(text, doc_name="文档"):
    """将文本分割为条款，增强中文条款识别和大文档处理"""
    # 增强中文条款模式识别，更全面的模式库
    patterns = [
        # 主要条款模式
        r'(第[一二三四五六七八九十百千]+条(?:之[一二三四五六七八九十]+)?\s*[:：]?\s*.*?)(?=第[一二三四五六七八九十百千]+条(?:之[一二三四五六七八九十]+)?\s*[:：]?\s*|$)',
        r'([一二三四五六七八九十百千]+、\s*.*?)(?=[一二三四五六七八九十百千]+、\s*|$)',
        r'(\d+\.\s*.*?)(?=\d+\.\s*|$)',
        r'(\(\s*[一二三四五六七八九十]+\s*\)\s*.*?)(?=\(\s*[一二三四五六七八九十]+\s*\)\s*|$)',
        r'(\(\s*[1-9]+\d*\s*\)\s*.*?)(?=\(\s*[1-9]+\d*\s*\)\s*|$)',
        r'([Ａ-Ｚａ-ｚ]\.\s*.*?)(?=[Ａ-Ｚａ-ｚ]\.\s*|$)',
        r'(【[^】]+】\s*.*?)(?=【[^】]+】\s*|$)',
        r'(第[一二三四五六七八九十百千]+款\s*.*?)(?=第[一二三四五六七八九十百千]+款\s*|$)',
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
    paragraphs = [p.strip() for p in paragraphs if p.strip() and len(p) > 10]
    
    # 如果段落数量仍然很少，尝试按固定长度分块（处理非常大的文档）
    if len(paragraphs) < 3 and len(text) > 5000:
        chunk_size = 1000  # 每个块大约1000字符
        paragraphs = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        st.warning(f"{doc_name} 条款结构不明显，已按 {chunk_size} 字符长度分块处理")
    
    return paragraphs

@lru_cache(maxsize=1000)
def chinese_text_similarity(text1, text2):
    """计算中文文本相似度，使用分词后匹配，结果缓存"""
    # 过滤标点符号和空格
    text1_clean = re.sub(r'[^\w\s]', '', text1)
    text2_clean = re.sub(r'[^\w\s]', '', text2)
    
    # 使用jieba进行中文分词
    words1 = list(jieba.cut(text1_clean))
    words2 = list(jieba.cut(text2_clean))
    
    # 计算分词后的相似度
    return SequenceMatcher(None, words1, words2).ratio()

def extract_key_terms(text):
    """提取文本中的关键术语，用于增强匹配"""
    terms = set()
    
    # 提取条款号
    clause_numbers = re.findall(r'第[一二三四五六七八九十百千]+条', text)
    terms.update(clause_numbers)
    
    # 提取可能的关键名词
    nouns = re.findall(r'【[^】]+】', text)
    terms.update(nouns)
    
    return terms

def match_clauses(clauses1, clauses2, progress_container=None):
    """匹配两个文档中的相似条款，优化中文匹配和大文档处理"""
    # 预先计算所有条款的关键术语
    terms1 = [extract_key_terms(clause) for clause in clauses1]
    terms2 = [extract_key_terms(clause) for clause in clauses2]
    
    # 先基于关键术语进行初步匹配
    term_matches = defaultdict(list)
    for i, terms in enumerate(terms1):
        if terms:
            for j, other_terms in enumerate(terms2):
                overlap = len(terms & other_terms)
                if overlap > 0:
                    term_matches[i].append((j, overlap))
    
    matched_pairs = []
    used_indices = set()
    total = len(clauses1)
    
    for i, clause1 in enumerate(clauses1):
        # 更新进度
        if progress_container is not None:
            progress = (i + 1) / total
            with progress_container:
                st.progress(progress)
                st.text(f"匹配条款: {i+1}/{total}")
        
        best_match = None
        best_ratio = 0.25  # 基础阈值
        best_j = -1
        
        # 优先考虑有关键术语匹配的条款
        candidates = []
        if i in term_matches:
            # 按术语重叠度排序
            for j, _ in sorted(term_matches[i], key=lambda x: x[1], reverse=True):
                if j not in used_indices:
                    candidates.append(j)
        
        # 如果没有术语匹配，考虑所有未匹配的条款
        if not candidates:
            candidates = [j for j in range(len(clauses2)) if j not in used_indices]
        
        # 计算相似度
        for j in candidates:
            ratio = chinese_text_similarity(clause1, clauses2[j])
            
            # 如果有关键术语匹配，适当提高相似度分数
            if i in term_matches and any(j == k for k, _ in term_matches[i]):
                ratio = min(1.0, ratio * 1.1)  # 提高10%
                
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
    """使用Qwen大模型分析条款合规性，优化中文提示词"""
    prompt = f"""
    请仔细分析以下两个中文条款的合规性，判断它们是否存在冲突：
    
    {filename1} 条款：{clause1}
    
    {filename2} 条款：{clause2}
    
    请按照以下结构用中文进行详细分析：
    1. 相似度评估：评估两个条款的相似程度（高/中/低）
    2. 差异点分析：简要指出两个条款在表述、范围、要求等方面的主要差异
    3. 合规性判断：判断是否存在冲突（无冲突/轻微冲突/严重冲突）
    4. 冲突原因：如果存在冲突，请具体说明冲突的原因和可能带来的影响
    5. 建议：针对发现的问题，给出专业的处理建议
    
    分析时请特别注意中文法律/合同条款中常用表述的细微差别，
    如"应当"与"必须"、"不得"与"禁止"、"可以"与"有权"等词语的区别。
    """
    
    return call_qwen_api(prompt, api_key)

def analyze_standalone_clause_with_qwen(clause, doc_name, api_key):
    """使用Qwen大模型分析独立条款（未匹配的条款）"""
    prompt = f"""
    请分析以下中文条款的内容：
    
    {doc_name} 中的条款：{clause}
    
    请用中文评估该条款的主要内容、核心要求、潜在影响和可能存在的问题，
    并给出简要分析和建议。分析时请注意中文表述的准确性和专业性。
    """
    
    return call_qwen_api(prompt, api_key)

def analyze_document_structure(text, doc_name, api_key):
    """分析文档结构，获取文档概述和主要章节"""
    if not api_key:
        return None
        
    prompt = f"""
    请分析以下文档的结构并提供概述：
    
    文档名称：{doc_name}
    文档内容：{text[:3000]}  # 只取前3000字符进行分析
    
    请提供：
    1. 文档类型和主题概述（100字以内）
    2. 主要章节或条款分类
    3. 文档的核心目的和适用范围
    
    分析应简洁明了，重点突出文档的结构特点。
    """
    
    return call_qwen_api(prompt, api_key)

def chunk_large_document(text, chunk_size=5000, overlap=500):
    """将大文档分块处理"""
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        # 下一块与当前块重叠，保持上下文连续性
        start = end - overlap
        
        if start >= text_length:
            break
            
    return chunks

def analyze_single_comparison(base_clauses, compare_text, base_name, compare_name, api_key, file_index):
    """分析单个对比文件与基准文件的合规性，支持大文档处理"""
    # 检查文档大小，决定是否分块处理
    if len(compare_text) > 10000:  # 超过10000字符的文档视为大文档
        st.info(f"{compare_name} 是一个大文档（{len(compare_text)}字符），将进行分块处理")
        chunks = chunk_large_document(compare_text)
        st.info(f"文档已分为 {len(chunks)} 个处理块")
        
        all_compare_clauses = []
        for i, chunk in enumerate(chunks):
            # 使用更安全的key命名方式
            expander_key = f"chunk_exp_{file_index}_{i}_{hash(chunk)}"
            with st.expander(f"处理块 {i+1}/{len(chunks)}", expanded=False, key=expander_key):
                chunk_clauses = split_into_clauses(chunk, f"{compare_name} (块 {i+1})")
                st.success(f"块 {i+1} 识别出 {len(chunk_clauses)} 条条款")
                all_compare_clauses.extend(chunk_clauses)
        
        compare_clauses = all_compare_clauses
    else:
        # 分割对比文件条款
        with st.spinner(f"正在分析 {compare_name} 的条款结构..."):
            compare_clauses = split_into_clauses(compare_text, compare_name)
            st.success(f"{compare_name} 条款分析完成，识别出 {len(compare_clauses)} 条条款")
    
    # 匹配条款，显示进度
    progress_container = st.empty()
    with st.spinner(f"正在匹配 {base_name} 与 {compare_name} 的相似条款..."):
        matched_pairs, unmatched_base, unmatched_compare = match_clauses(
            base_clauses, 
            compare_clauses,
            progress_container
        )
    progress_container.empty()
    
    # 显示总体统计
    st.divider()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(f"{base_name} 条款数", len(base_clauses))
    col2.metric(f"{compare_name} 条款数", len(compare_clauses))
    col3.metric("匹配条款数", len(matched_pairs))
    col4.metric("未匹配条款数", len(unmatched_base) + len(unmatched_compare))
    
    # 显示条款对比和合规性分析
    st.divider()
    st.subheader(f"📊 {compare_name} 与 {base_name} 条款合规性详细分析（Qwen大模型）")
    
    # 创建分析结果的标签页导航
    tab_labels = ["全部匹配项"]
    if len(unmatched_base) > 0:
        tab_labels.append(f"{base_name} 独有条款")
    if len(unmatched_compare) > 0:
        tab_labels.append(f"{compare_name} 独有条款")
    
    tabs = st.tabs(tab_labels)
    tab_idx = 0
    
    # 分析每个匹配对的合规性
    with tabs[tab_idx]:
        tab_idx += 1
        
        # 添加筛选功能 - 使用更安全的key命名方式
        slider_key = f"sim_slider_{file_index}_{hash(str(base_clauses[:5]))}"
        min_similarity = st.slider(
            "最低相似度筛选", 
            0.0, 1.0, 0.0, 0.05,
            key=slider_key
        )
        filtered_pairs = [p for p in matched_pairs if p[2] >= min_similarity]
        
        st.write(f"显示 {len(filtered_pairs)} 个匹配项（筛选后）")
        
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
            
            # 添加分析结果折叠框 - 使用更安全的key命名方式
            expander_key = f"analysis_exp_{file_index}_{i}_{hash(clause1[:20])}_{hash(clause2[:20])}"
            with st.expander("查看Qwen大模型合规性分析", expanded=False, key=expander_key):
                with st.spinner("正在调用Qwen大模型进行中文合规性分析..."):
                    analysis = analyze_compliance_with_qwen(clause1, clause2, base_name, compare_name, api_key)
                
                if analysis:
                    st.markdown('<div class="model-response"><strong>Qwen大模型分析结果:</strong><br>' + analysis + '</div>', unsafe_allow_html=True)
                else:
                    st.warning("未能获取合规性分析结果")
            
            st.divider()
    
    # 未匹配的条款分析 - 基准文件独有
    if len(unmatched_base) > 0 and tab_idx < len(tabs):
        with tabs[tab_idx]:
            tab_idx += 1
            st.markdown(f"#### {base_name} 中独有的条款 ({len(unmatched_base)})")
            
            # 允许用户选择查看特定条款 - 使用更安全的key命名方式
            select_key = f"unmatched_base_sel_{file_index}_{hash(str(unmatched_base[:5]))}"
            selected_clause = st.selectbox(
                "选择要查看的条款",
                range(len(unmatched_base)),
                format_func=lambda x: f"条款 {x+1}（{min(50, len(unmatched_base[x]))}字）",
                key=select_key
            )
            
            clause = unmatched_base[selected_clause]
            st.markdown(f'<div class="clause-box"><strong>条款 {selected_clause+1}:</strong><br>{clause}</div>', unsafe_allow_html=True)
            
            with st.spinner("Qwen大模型正在分析此条款..."):
                analysis = analyze_standalone_clause_with_qwen(clause, base_name, api_key)
            
            if analysis:
                st.markdown('<div class="model-response"><strong>Qwen分析:</strong><br>' + analysis + '</div>', unsafe_allow_html=True)
    
    # 未匹配的条款分析 - 对比文件独有
    if len(unmatched_compare) > 0 and tab_idx < len(tabs):
        with tabs[tab_idx]:
            tab_idx += 1
            st.markdown(f"#### {compare_name} 中独有的条款 ({len(unmatched_compare)})")
            
            # 允许用户选择查看特定条款 - 使用更安全的key命名方式
            select_key = f"unmatched_comp_sel_{file_index}_{hash(str(unmatched_compare[:5]))}"
            selected_clause = st.selectbox(
                "选择要查看的条款",
                range(len(unmatched_compare)),
                format_func=lambda x: f"条款 {x+1}（{min(50, len(unmatched_compare[x]))}字）",
                key=select_key
            )
            
            clause = unmatched_compare[selected_clause]
            st.markdown(f'<div class="clause-box"><strong>条款 {selected_clause+1}:</strong><br>{clause}</div>', unsafe_allow_html=True)
            
            with st.spinner("Qwen大模型正在分析此条款..."):
                analysis = analyze_standalone_clause_with_qwen(clause, compare_name, api_key)
            
            if analysis:
                st.markdown('<div class="model-response"><strong>Qwen分析:</strong><br>' + analysis + '</div>', unsafe_allow_html=True)

def main():
    """主函数，控制应用流程"""
    st.title("📄 Qwen 中文PDF条款合规性分析工具")
    st.write("上传基准PDF文档和需要对比的PDF文档，系统将自动分析条款合规性")
    
    # 侧边栏设置
    with st.sidebar:
        st.header("🔧 设置")
        api_key = st.text_input("Qwen API 密钥", type="password", help="请输入您的阿里云DashScope API密钥")
        st.markdown("""
        提示：API密钥可从 [阿里云DashScope控制台](https://dashscope.console.aliyun.com/) 获取
        """)
    
    # 主内容区
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📋 基准文档（例如：标准条款）")
        base_file = st.file_uploader("上传基准PDF文件", type="pdf", key="base_file")
    
    with col2:
        st.subheader("🔍 对比文档（例如：待审核条款）")
        compare_files = st.file_uploader(
            "上传一个或多个对比PDF文件", 
            type="pdf", 
            accept_multiple_files=True,
            key="compare_files"
        )
    
    # 处理基准文件
    if base_file is not None and compare_files:
        with st.spinner("正在提取基准文档文本..."):
            progress_bar = st.progress(0)
            base_text = extract_text_from_pdf(base_file, progress_bar)
            progress_bar.empty()
            
            if base_text:
                st.success(f"基准文档 '{base_file.name}' 文本提取完成，共 {len(base_text)} 字符")
                
                # 分析文档结构
                with st.expander("查看文档结构分析", expanded=False):
                    structure_analysis = analyze_document_structure(base_text, base_file.name, api_key)
                    if structure_analysis:
                        st.markdown(structure_analysis)
                    else:
                        st.info("未进行文档结构分析（API密钥未设置或分析失败）")
                
                # 分割基准条款
                with st.spinner("正在分析基准文档条款结构..."):
                    base_clauses = split_into_clauses(base_text, base_file.name)
                    st.success(f"基准文档条款分析完成，识别出 {len(base_clauses)} 条条款")
                
                # 处理每个对比文件
                for i, compare_file in enumerate(compare_files):
                    st.divider()
                    st.header(f"📊 对比分析 {i+1}/{len(compare_files)}: {compare_file.name}")
                    
                    with st.spinner(f"正在提取 {compare_file.name} 文本..."):
                        progress_bar = st.progress(0)
                        compare_text = extract_text_from_pdf(compare_file, progress_bar)
                        progress_bar.empty()
                        
                        if compare_text:
                            st.success(f"{compare_file.name} 文本提取完成，共 {len(compare_text)} 字符")
                            
                            # 分析文档结构
                            with st.expander(f"查看 {compare_file.name} 结构分析", expanded=False):
                                structure_analysis = analyze_document_structure(compare_text, compare_file.name, api_key)
                                if structure_analysis:
                                    st.markdown(structure_analysis)
                                else:
                                    st.info("未进行文档结构分析（API密钥未设置或分析失败）")
                            
                            # 进行条款对比分析
                            analyze_single_comparison(
                                base_clauses,
                                compare_text,
                                base_file.name,
                                compare_file.name,
                                api_key,
                                i  # 传入文件索引作为唯一标识
                            )
                        else:
                            st.error(f"无法从 {compare_file.name} 中提取文本")
            else:
                st.error(f"无法从基准文档 '{base_file.name}' 中提取文本")

if __name__ == "__main__":
    main()
