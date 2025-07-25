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
                
                time.sleep(2 **attempt)  # 指数退避
                
            except requests.exceptions.Timeout:
                st.warning(f"API请求超时 (尝试 {attempt+1}/{retry})")
                time.sleep(2** attempt)
            except Exception as e:
                st.warning(f"API调用异常: {str(e)} (尝试 {attempt+1}/{retry})")
                time.sleep(2 **attempt)
                
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
            matched_pairs.append({
                "base_clause": clause1,
                "compare_clause": best_match,
                "similarity": best_ratio,
                "base_index": i,
                "compare_index": best_j
            })
            used_indices.add(best_j)
    
    # 处理未匹配的条款
    for j in range(len(clauses2)):
        if j not in used_indices:
            matched_pairs.append({
                "base_clause": None,
                "compare_clause": clauses2[j],
                "similarity": 0,
                "base_index": -1,
                "compare_index": j
            })
    
    return matched_pairs

def analyze_compliance(base_clause, compare_clause, api_key):
    """分析条款合规性"""
    if not base_clause:
        return "无对应基准条款可比对", "warning"
    
    prompt = f"""
    作为法律合规性分析专家，请对比以下两个条款的合规性：
    
    基准条款：
    {base_clause}
    
    待分析条款：
    {compare_clause}
    
    请分析待分析条款是否符合基准条款的要求，指出两者的主要差异和潜在冲突。
    分析应包括：
    1. 条款核心内容对比
    2. 主要差异点
    3. 合规性判断（符合/部分符合/不符合）
    4. 风险提示（如适用）
    
    请用中文简洁明了地回答，不要超过300字。
    """
    
    response = call_qwen_api(prompt, api_key)
    
    if not response:
        return "合规性分析失败，请检查API密钥或稍后重试", "error"
    
    # 简单判断合规性等级
    if "不符合" in response:
        return response, "conflict"
    elif "部分符合" in response:
        return response, "warning"
    else:
        return response, "ok"

def analyze_single_comparison(base_clauses, compare_clauses, base_name, compare_name, api_key, file_index):
    """分析单个文件对比"""
    st.subheader(f"📊 {base_name} 与 {compare_name} 条款对比分析")
    
    # 创建进度容器
    progress_col1, progress_col2 = st.columns(2)
    
    with progress_col1:
        match_progress = st.empty()
    
    # 匹配条款
    matched_pairs = match_clauses(base_clauses, compare_clauses, match_progress)
    
    # 清除进度显示
    match_progress.empty()
    
    # 按相似度排序（高到低）
    matched_pairs.sort(key=lambda x: x["similarity"], reverse=True)
    
    # 显示匹配结果
    for i, pair in enumerate(matched_pairs):
        # 生成唯一的expander key，确保在整个应用中唯一
        expander_key = f"qwen_analysis_{file_index}_{i}_{hashlib.md5(str(pair).encode()).hexdigest()[:8]}"
        
        base_clause = pair["base_clause"]
        compare_clause = pair["compare_clause"]
        similarity = pair["similarity"]
        
        # 显示条款对比
        if base_clause:
            with st.expander(f"条款对比 #{i+1} (相似度: {similarity:.2f})", expanded=False):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown(f"**{base_name} 条款**")
                    st.markdown(f'<div class="clause-box">{" ".join(base_clause[:500])}{"..." if len(base_clause) > 500 else ""}</div>', unsafe_allow_html=True)
                
                with col2:
                    st.markdown(f"**{compare_name} 条款**")
                    st.markdown(f'<div class="clause-box">{" ".join(compare_clause[:500])}{"..." if len(compare_clause) > 500 else ""}</div>', unsafe_allow_html=True)
                
                # 合规性分析
                analysis, status = analyze_compliance(base_clause, compare_clause, api_key)
                
                # 使用唯一key创建分析expander
                with st.expander("查看Qwen大模型合规性分析", expanded=False, key=expander_key):
                    status_class = f"compliance-{status}"
                    st.markdown(f'<div class="model-response {status_class}">{analysis}</div>', unsafe_allow_html=True)
        else:
            with st.expander(f"仅在 {compare_name} 中存在的条款 #{i+1}", expanded=False):
                st.markdown(f"**{compare_name} 条款**")
                st.markdown(f'<div class="clause-box compliance-warning">{" ".join(compare_clause[:500])}{"..." if len(compare_clause) > 500 else ""}</div>', unsafe_allow_html=True)

def main():
    """主函数"""
    st.title("📄 Qwen 中文PDF条款合规性分析工具")
    st.write("上传基准PDF文档和待比较PDF文档，系统将自动分析条款合规性并生成报告")
    
    # 侧边栏设置
    with st.sidebar:
        st.header("⚙️ 设置")
        qwen_api_key = st.text_input("Qwen API 密钥", type="password", help="请输入阿里云Qwen API密钥")
        st.markdown("---")
        st.header("📁 上传文档")
        base_file = st.file_uploader("上传基准PDF文档", type="pdf", key="base_file")
        compare_files = st.file_uploader("上传待比较PDF文档（可多个）", type="pdf", accept_multiple_files=True, key="compare_files")
        st.markdown("---")
        st.info("工具说明：\n1. 上传基准文档和待比较文档\n2. 系统会自动提取文本并分割条款\n3. 对比分析条款相似度和合规性\n4. 展示AI分析结果")
    
    # 主逻辑
    if base_file and compare_files:
        # 提取基准文档文本
        with st.spinner("正在提取基准文档文本..."):
            base_progress = st.empty()
            base_text = extract_text_from_pdf(base_file, base_progress)
            base_progress.empty()
            
            if not base_text:
                st.error("无法从基准文档中提取文本，请检查文件是否有效")
                return
            
            base_name = base_file.name.split(".")[0]
            base_clauses = split_into_clauses(base_text, base_name)
            st.success(f"基准文档 '{base_name}' 处理完成，提取到 {len(base_clauses)} 个条款")
        
        # 处理每个待比较文档
        for i, compare_file in enumerate(compare_files):
            with st.spinner(f"正在处理待比较文档: {compare_file.name}..."):
                compare_progress = st.empty()
                compare_text = extract_text_from_pdf(compare_file, compare_progress)
                compare_progress.empty()
                
                if not compare_text:
                    st.error(f"无法从文档 '{compare_file.name}' 中提取文本，请检查文件是否有效")
                    continue
                
                compare_name = compare_file.name.split(".")[0]
                compare_clauses = split_into_clauses(compare_text, compare_name)
                st.success(f"文档 '{compare_name}' 处理完成，提取到 {len(compare_clauses)} 个条款")
                
                # 分析对比
                analyze_single_comparison(
                    base_clauses,
                    compare_clauses,
                    base_name,
                    compare_name,
                    qwen_api_key,
                    file_index=i  # 传入文件索引作为唯一标识
                )
                st.markdown("---")
    
    elif base_file is None and compare_files:
        st.warning("请先上传基准PDF文档")
    elif base_file and not compare_files:
        st.warning("请上传至少一个待比较PDF文档")

if __name__ == "__main__":
    main()
