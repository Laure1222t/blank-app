import streamlit as st
from PyPDF2 import PdfReader
from difflib import SequenceMatcher
import base64
import re
import requests
import jieba
import hashlib
import time
import io
from functools import lru_cache
from collections import defaultdict
# 新增OCR相关库
from pdf2image import convert_from_path
import pytesseract
from PIL import Image

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
            "max_tokens": 800  # 减少最大 tokens，使回答更简洁
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

# 新增OCR相关函数
def ocr_image(image):
    """对单张图片进行OCR识别，提取中文文本"""
    try:
        # 配置Tesseract识别中文
        custom_config = r'--oem 3 --psm 6 -l chi_sim'
        text = pytesseract.image_to_string(image, config=custom_config)
        return text
    except Exception as e:
        st.warning(f"OCR识别出错: {str(e)}")
        return ""

def extract_text_from_image_pdf(file, progress_bar=None):
    """从图片PDF中提取文本（先转为图片再进行OCR）"""
    try:
        # 将PDF保存到临时文件
        temp_path = f"temp_{hashlib.md5(file.read()).hexdigest()}.pdf"
        file.seek(0)  # 重置文件指针
        with open(temp_path, "wb") as f:
            f.write(file.read())
        
        # 将PDF转换为图片
        pages = convert_from_path(temp_path, 300)  # 300 DPI提高识别精度
        total_pages = len(pages)
        text = ""
        
        for i, page in enumerate(pages):
            # 对每一页进行OCR
            page_text = ocr_image(page)
            # 处理识别结果
            page_text = page_text.replace("  ", "").replace("\n", "").replace("\r", "")
            text += page_text
            
            # 更新进度条
            if progress_bar is not None:
                progress = (i + 1) / total_pages
                progress_bar.progress(progress)
                progress_bar.text(f"OCR处理: 第 {i+1}/{total_pages} 页")
        
        return text
    except Exception as e:
        st.error(f"图片PDF处理失败: {str(e)}")
        return ""

def is_image_based_pdf(file):
    """判断PDF是否为图片型PDF（无文本层）"""
    try:
        # 尝试提取文本
        pdf_reader = PdfReader(file)
        file.seek(0)  # 重置文件指针
        
        # 检查前几页是否有文本
        sample_text = ""
        for i, page in enumerate(pdf_reader.pages):
            if i >= 3:  # 检查前3页
                break
            sample_text += page.extract_text() or ""
            
        # 如果提取的文本很少，视为图片型PDF
        return len(sample_text.strip()) < 50
    except Exception as e:
        st.warning(f"PDF类型检测出错: {str(e)}")
        return False

def extract_text_from_pdf(file, progress_bar=None):
    """从PDF提取文本，支持普通PDF和图片PDF（通过OCR）"""
    try:
        # 先判断PDF类型
        file.seek(0)  # 重置文件指针
        if is_image_based_pdf(file):
            st.info("检测到图片型PDF，将使用OCR进行文字识别（可能需要较长时间）")
            file.seek(0)  # 重置文件指针
            return extract_text_from_image_pdf(file, progress_bar)
        
        # 普通PDF文本提取
        file.seek(0)  # 重置文件指针
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
    # 简单实现：提取可能的条款号和关键名词
    terms = set()
    
    # 提取条款号
    clause_numbers = re.findall(r'第[一二三四五六七八九十百千]+条', text)
    terms.update(clause_numbers)
    
    # 提取可能的关键名词（简单处理）
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
    """使用Qwen大模型分析条款合规性，简化差异点分析"""
    prompt = f"""
    请简要分析以下两个中文条款的合规性，判断它们是否存在冲突：
    
    {filename1} 条款：{clause1}
    
    {filename2} 条款：{clause2}
    
    请按照以下结构用中文进行简洁分析（总字数控制在300字以内）：
    1. 相似度评估：简要说明相似程度（高/中/低）
    2. 主要差异：列出1-2个最核心的差异点
    3. 合规性判断：是否存在冲突（无冲突/轻微冲突/严重冲突）
    4. 简要建议：针对发现的问题，给出简短建议
    
    分析请简明扼要，避免冗长描述。
    """
    
    return call_qwen_api(prompt, api_key)

def analyze_standalone_clause_with_qwen(clause, doc_name, api_key):
    """使用Qwen大模型分析独立条款（未匹配的条款），结果更简洁"""
    prompt = f"""
    请简要分析以下中文条款的内容（总字数控制在200字以内）：
    
    {doc_name} 中的条款：{clause}
    
    请用中文简要说明该条款的核心内容和主要要求，无需展开详细分析。
    """
    
    return call_qwen_api(prompt, api_key)

def analyze_document_structure(text, doc_name, api_key):
    """分析文档结构，获取文档概述和主要章节，结果更简洁"""
    if not api_key:
        return None
        
    prompt = f"""
    请简要分析以下文档的结构并提供概述（总字数控制在200字以内）：
    
    文档名称：{doc_name}
    文档内容：{text[:3000]}  # 只取前3000字符进行分析
    
    请简明提供：
    1. 文档类型和主题概述
    2. 主要章节或条款分类（最多5项）
    3. 文档的核心目的
    
    分析应非常简洁，避免细节描述。
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

def analyze_single_comparison(base_clauses, compare_text, base_name, compare_name, api_key):
    """分析单个对比文件与基准文件的合规性，支持大文档处理"""
    # 检查文档大小，决定是否分块处理
    if len(compare_text) > 10000:  # 超过10000字符的文档视为大文档
        st.info(f"{compare_name} 是一个大文档（{len(compare_text)}字符），将进行分块处理")
        chunks = chunk_large_document(compare_text)
        st.info(f"文档已分为 {len(chunks)} 个处理块")
        
        all_compare_clauses = []
        for i, chunk in enumerate(chunks):
            with st.expander(f"处理块 {i+1}/{len(chunks)}", expanded=False):
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
    st.subheader(f"📊 {compare_name} 与 {base_name} 条款合规性分析（Qwen大模型）")
    
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
        
        # 添加筛选功能
        min_similarity = st.slider("最低相似度筛选", 0.0, 1.0, 0.0, 0.05)
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
            
            # 添加分析结果折叠框
            with st.expander("查看Qwen大模型分析", expanded=False):
                with st.spinner("正在调用Qwen大模型进行分析..."):
                    analysis = analyze_compliance_with_qwen(clause1, clause2, base_name, compare_name, api_key)
                
                if analysis:
                    st.markdown('<div class="model-response"><strong>Qwen分析结果:</strong><br>' + analysis + '</div>', unsafe_allow_html=True)
                else:
                    st.warning("未能获取分析结果")
            
            st.divider()
    
    # 未匹配的条款分析 - 基准文件独有
    if len(unmatched_base) > 0 and tab_idx < len(tabs):
        with tabs[tab_idx]:
            tab_idx += 1
            st.markdown(f"#### {base_name} 中独有的条款 ({len(unmatched_base)})")
            
            # 允许用户选择查看特定条款
            selected_clause = st.selectbox(
                "选择要查看的条款",
                range(len(unmatched_base)),
                format_func=lambda x: f"条款 {x+1}（{min(50, len(unmatched_base[x]))}字）"
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
            
            # 允许用户选择查看特定条款
            selected_clause = st.selectbox(
                "选择要查看的条款",
                range(len(unmatched_compare)),
                format_func=lambda x: f"条款 {x+1}（{min(50, len(unmatched_compare[x]))}字）"
            )
            
            clause = unmatched_compare[selected_clause]
            st.markdown(f'<div class="clause-box"><strong>条款 {selected_clause+1}:</strong><br>{clause}</div>', unsafe_allow_html=True)
            
            with st.spinner("Qwen大模型正在分析此条款..."):
                analysis = analyze_standalone_clause_with_qwen(clause, compare_name, api_key)
            
            if analysis:
                st.markdown('<div class="model-response"><strong>Qwen分析:</strong><br>' + analysis + '</div>', unsafe_allow_html=True)

# 应用主界面
st.title("📄 Qwen 中文PDF条款合规性分析工具")
st.markdown("专为中文文档优化的智能条款合规性分析系统 - 支持大文档、图片PDF和一对多分析")

# 新增OCR配置说明
with st.expander("📌 关于图片PDF处理", expanded=False):
    st.markdown("""
    本工具支持处理图片转PDF中的文字（通过OCR技术），但需要额外配置：
    
    1. 安装Tesseract OCR引擎：
       - Windows: 下载安装 [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)
       - macOS: `brew install tesseract tesseract-lang`
       - Linux: `sudo apt install tesseract-ocr tesseract-ocr-chi-sim`
    
    2. 确保中文语言包已安装（用于识别中文文本）
    """)

# Qwen API设置
with st.sidebar:
    st.subheader("Qwen API 设置")
    qwen_api_key = st.text_input("请输入Qwen API密钥", type="password")
    st.markdown(f"""
    提示：API密钥可以从阿里云DashScope控制台获取。
    当前使用的API端点：`{QWEN_API_URL}`
    """)
    
    # OCR设置
    st.subheader("OCR 设置")
    tesseract_path = st.text_input(
        "Tesseract OCR安装路径（可选）", 
        value=r"C:\Program Files\Tesseract-OCR\tesseract.exe" if st.runtime.platform == "windows" else "/usr/bin/tesseract"
    )
    # 配置Tesseract路径
    pytesseract.pytesseract.tesseract_cmd = tesseract_path
    
    # 高级设置
    with st.expander("高级设置", expanded=False):
        similarity_threshold = st.slider("条款匹配相似度阈值", 0.0, 1.0, 0.25, 0.05)
        max_api_retries = st.slider("API最大重试次数", 1, 5, 3)
        chunk_size = st.slider("大文档分块大小（字符）", 2000, 10000, 5000, 500)
        ocr_dpi = st.slider("OCR识别精度（DPI）", 150, 600, 300, 50)

with st.form("upload_form"):
    st.subheader("基准文件")
    base_file = st.file_uploader("选择基准PDF文件", type=["pdf"], key="base_file")
    
    st.subheader("对比文件（可上传多个）")
    compare_files = st.file_uploader(
        "选择需要对比的PDF文件", 
        type=["pdf"], 
        key="compare_files",
        accept_multiple_files=True
    )
    
    # 分析选项
    with st.expander("分析选项", expanded=False):
        analyze_structure = st.checkbox("分析文档结构并生成概述", value=True)
        show_all_matches = st.checkbox("显示所有匹配项（包括低相似度）", value=True)
        detailed_analysis = st.checkbox("生成详细分析报告", value=False)  # 默认不生成详细报告
        force_ocr = st.checkbox("对所有PDF强制使用OCR（即使有文本层）", value=False)
    
    submitted = st.form_submit_button("开始合规性分析")

if submitted and base_file and compare_files:
    if not qwen_api_key:
        st.warning("未检测到Qwen API密钥，部分功能可能受限")
    
    # 创建总体进度跟踪
    overall_progress = st.progress(0)
    total_steps = 1 + len(compare_files) * 3  # 基准文件处理 + 每个对比文件的3个步骤
    current_step = 0
    
    with st.spinner("正在解析基准PDF内容，请稍候..."):
        # 显示基准文件处理进度
        progress_bar = st.progress(0)
        
        # 检查是否强制OCR
        if force_ocr:
            base_text = extract_text_from_image_pdf(base_file, progress_bar)
        else:
            base_text = extract_text_from_pdf(base_file, progress_bar)
            
        progress_bar.empty()
        
        current_step += 1
        overall_progress.progress(current_step / total_steps)
        
        if not base_text:
            st.error("无法提取基准文件的文本内容，请确认PDF包含可提取的中文文本")
        else:
            st.success(f"基准文件 {base_file.name} 文本提取完成（{len(base_text)}字符）")
            
            # 分析基准文档结构
            if analyze_structure and qwen_api_key:
                with st.spinner("正在分析基准文档结构..."):
                    base_structure = analyze_document_structure(base_text, base_file.name, qwen_api_key)
                    if base_structure:
                        st.markdown('<div class="section-header"><strong>基准文档结构分析:</strong></div>', unsafe_allow_html=True)
                        st.markdown('<div class="model-response">' + base_structure + '</div>', unsafe_allow_html=True)
            
            # 处理大基准文档
            if len(base_text) > 10000:
                st.info(f"基准文件 {base_file.name} 是一个大文档（{len(base_text)}字符），将进行分块处理")
                chunks = chunk_large_document(base_text, chunk_size)
                st.info(f"基准文档已分为 {len(chunks)} 个处理块")
                
                base_clauses = []
                for i, chunk in enumerate(chunks):
                    with st.expander(f"基准文档处理块 {i+1}/{len(chunks)}", expanded=False):
                        chunk_clauses = split_into_clauses(chunk, f"{base_file.name} (块 {i+1})")
                        st.success(f"块 {i+1} 识别出 {len(chunk_clauses)} 条条款")
                        base_clauses.extend(chunk_clauses)
            else:
                # 预处理基准文件条款
                base_clauses = split_into_clauses(base_text, base_file.name)
            
            st.success(f"基准文件 {base_file.name} 条款解析完成，共识别出 {len(base_clauses)} 条条款")
            current_step += 1
            overall_progress.progress(current_step / total_steps)
            
            # 对每个对比文件进行分析
            for i, compare_file in enumerate(compare_files, 1):
                st.markdown(f"## 🔍 分析 {i}/{len(compare_files)}: {compare_file.name} 与 {base_file.name} 的对比")
                
                # 提取对比文件文本
                with st.spinner(f"正在提取 {compare_file.name} 的文本内容..."):
                    progress_bar = st.progress(0)
                    
                    if force_ocr:
                        compare_text = extract_text_from_image_pdf(compare_file, progress_bar)
                    else:
                        compare_text = extract_text_from_pdf(compare_file, progress_bar)
                        
                    progress_bar.empty()
                
                current_step += 1
                overall_progress.progress(current_step / total_steps)
                
                if not compare_text:
                    st.error(f"无法提取 {compare_file.name} 的文本内容，跳过该文件")
                    continue
                
                # 分析对比文档结构
                if analyze_structure and qwen_api_key:
                    with st.spinner(f"正在分析 {compare_file.name} 的文档结构..."):
                        compare_structure = analyze_document_structure(compare_text, compare_file.name, qwen_api_key)
                        if compare_structure:
                            st.markdown(f'<div class="section-header"><strong>{compare_file.name} 结构分析:</strong></div>', unsafe_allow_html=True)
                            st.markdown('<div class="model-response">' + compare_structure + '</div>', unsafe_allow_html=True)
                
                current_step += 1
                overall_progress.progress(current_step / total_steps)
                
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
                
                # 在文件分析之间添加分隔
                st.markdown("---")
        
        # 完成所有分析
        overall_progress.empty()
        st.success("所有文档分析已完成！")
        
        # 提供整体分析报告下载（如果启用）
        if detailed_analysis and qwen_api_key:
            with st.spinner("正在生成整体分析报告..."):
                report_prompt = f"""
                基于之前对基准文件 {base_file.name} 和对比文件 {[f.name for f in compare_files]} 的分析，
                请生成一份简洁的综合合规性分析报告（控制在500字以内），包括：
                1. 整体合规性评估
                2. 主要冲突点汇总（最多3项）
                3. 简要改进建议
                
                报告应非常简洁，重点突出。
                """
                report = call_qwen_api(report_prompt, qwen_api_key)
                
                if report:
                    st.markdown('<div class="section-header"><strong>整体合规性分析报告:</strong></div>', unsafe_allow_html=True)
                    st.markdown(report)
                    
                    # 创建下载链接
                    report_content = f"Qwen 中文PDF条款合规性分析报告\n\n基准文件: {base_file.name}\n对比文件: {', '.join([f.name for f in compare_files])}\n\n{report}"
                    download_link = create_download_link(report_content, "compliance_report.txt", "下载分析报告")
                    st.markdown(download_link, unsafe_allow_html=True)
elif submitted:
    if not base_file:
        st.error("请上传基准PDF文件")
    if not compare_files:
        st.error("请至少上传一个对比PDF文件")
else:
    st.info('请上传一个基准PDF文件和至少一个对比PDF文件，然后点击"开始合规性分析"按钮')

# 添加页脚
st.divider()
st.markdown("""
<style>
.footer {
    font-size: 0.8rem;
    color: #666;
    text-align: center;
    margin-top: 2rem;
}
</style>
<div class="footer">
    中文PDF条款合规性分析工具 | 基于Qwen大模型 | 支持图片PDF识别 | 优化中文文档处理
</div>
""", unsafe_allow_html=True)
