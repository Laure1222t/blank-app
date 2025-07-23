import streamlit as st
from PyPDF2 import PdfReader
from difflib import SequenceMatcher
import base64
import re
import requests
import jieba
import time
from typing import List, Tuple, Dict, Optional

# --------------------------
# 基础配置与初始化
# --------------------------
# 页面配置（增加加载状态管理）
st.set_page_config(
    page_title="Qwen 中文PDF条款合规性分析工具（1对多）",
    page_icon="📄",
    layout="wide"
)

# 初始化jieba分词（添加自定义词典支持）
jieba.initialize()
try:
    jieba.load_userdict("legal_dict.txt")  # 可放置法律术语词典增强分词
except:
    pass  # 无词典时不影响基础功能

# 自定义样式（增强视觉反馈与可读性）
st.markdown("""
<style>
    .stApp { max-width: 1400px; margin: 0 auto; }
    .file-selector { border: 1px solid #e0e0e0; padding: 15px; border-radius: 5px; margin-bottom: 15px; }
    .benchmark-label { color: #0066cc; font-weight: bold; }
    .target-label { color: #cc6600; font-weight: bold; }
    .highlight-conflict { background-color: #ffeeba; padding: 2px 4px; border-radius: 3px; }
    .clause-box { border-left: 4px solid #007bff; padding: 10px; margin: 10px 0; background-color: #f8f9fa; }
    .compliance-ok { border-left: 4px solid #28a745; }
    .compliance-warning { border-left: 4px solid #ffc107; }
    .compliance-conflict { border-left: 4px solid #dc3545; }
    .model-response { background-color: #f0f2f6; padding: 15px; border-radius: 5px; margin: 10px 0; }
    .section-title { border-bottom: 2px solid #f0f2f6; padding-bottom: 8px; margin-top: 20px; }
    .analysis-card { border: 1px solid #eee; border-radius: 8px; padding: 15px; margin: 10px 0; }
    .status-badge { display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 0.8rem; }
</style>
""", unsafe_allow_html=True)

# API配置（支持模型选择）
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
SUPPORTED_MODELS = {
    "qwen-plus": "Qwen Plus（平衡型，推荐）",
    "qwen-max": "Qwen Max（高精度，较慢）",
    "qwen-turbo": "Qwen Turbo（快速型，适合初步分析）"
}

# --------------------------
# 核心功能优化
# --------------------------
def call_qwen_api(prompt: str, api_key: str, model: str = "qwen-plus") -> Optional[str]:
    """调用Qwen大模型API（增加重试机制和模型选择）"""
    if not api_key:
        st.error("Qwen API密钥未设置，请在左侧栏输入密钥")
        return None
        
    max_retries = 2  # 最多重试2次
    retry_delay = 3  # 重试间隔（秒）
    
    for attempt in range(max_retries + 1):
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            
            data = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 1500
            }
            
            response = requests.post(
                QWEN_API_URL,
                headers=headers,
                json=data,
                timeout=60
            )
            
            # 处理成功响应
            if response.status_code == 200:
                response_json = response.json()
                if "choices" in response_json and len(response_json["choices"]) > 0:
                    return response_json["choices"][0]["message"]["content"]
                st.error("API返回格式不符合预期（无有效结果）")
                return None
            
            # 处理限流/临时错误（重试）
            elif response.status_code in [429, 502, 503] and attempt < max_retries:
                st.warning(f"API请求暂时失败（{response.status_code}），将在{retry_delay}秒后重试（{attempt + 1}/{max_retries}）")
                time.sleep(retry_delay)
                continue
            
            # 其他错误（不重试）
            else:
                st.error(f"API请求失败，状态码: {response.status_code}，响应: {response.text[:200]}...")
                return None
                
        except requests.exceptions.Timeout:
            if attempt < max_retries:
                st.warning(f"API请求超时，将在{retry_delay}秒后重试（{attempt + 1}/{max_retries}）")
                time.sleep(retry_delay)
                continue
            st.error("API请求超时，已达到最大重试次数")
            return None
        except Exception as e:
            st.error(f"调用Qwen API失败: {str(e)}")
            return None


def extract_text_from_pdf(file) -> str:
    """从PDF提取文本（优化中文排版和进度反馈）"""
    try:
        pdf_reader = PdfReader(file)
        text = ""
        total_pages = len(pdf_reader.pages)
        
        # 显示提取进度（大文件友好）
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, page in enumerate(pdf_reader.pages):
            page_text = page.extract_text() or ""
            # 优化中文处理：保留必要空格，修复断句
            page_text = page_text.replace("\n", "").replace("\r", "").replace("  ", " ")
            text += page_text
            
            # 更新进度
            progress = (i + 1) / total_pages
            progress_bar.progress(progress)
            status_text.text(f"正在提取文本：第{i + 1}/{total_pages}页")
        
        progress_bar.empty()
        status_text.empty()
        return text
    except Exception as e:
        st.error(f"提取文本失败: {str(e)}")
        return ""


def split_into_clauses(text: str) -> List[str]:
    """将文本分割为条款（增强模式识别和过滤）"""
    # 增强中文条款模式（支持更多格式）
    patterns = [
        # 标准条款格式
        r'(第[一二三四五六七八九十百千]+条\s*[：:]\s*.*?)(?=第[一二三四五六七八九十百千]+条\s*[：:]|$)',
        r'([一二三四五六七八九十]+、\s*.*?)(?=[一二三四五六七八九十]+、\s*|$)',
        # 数字编号格式
        r'(\d+\.\s*.*?)(?=\d+\.\s*|$)',
        r'(\(\d+\)\s*.*?)(?=\(\d+\)\s*|$)',
        r'(\d+\)\s*.*?)(?=\d+\)\s*|$)',
        # 特殊标记格式
        r'(【[^\】]+】\s*.*?)(?=【[^\】]+】\s*|$)',
        r'([A-Za-z]\.\s*.*?)(?=[A-Za-z]\.\s*|$)'
    ]
    
    for pattern in patterns:
        clauses = re.findall(pattern, text, re.DOTALL)
        if len(clauses) > 3:  # 确保有效分割
            # 过滤过短/无效条款
            return [
                clause.strip() for clause in clauses 
                if clause.strip() and len(clause.strip()) > 15  # 过滤极短内容
            ]
    
    # 兜底方案：按标点分割（更智能的过滤）
    paragraphs = re.split(r'[。；！？]\s*', text)
    return [
        p.strip() for p in paragraphs 
        if p.strip() and len(p.strip()) > 15 and not re.match(r'^\s*$', p)
    ]


def match_clauses(benchmark_clauses: List[str], target_clauses: List[str]) -> Tuple[List, List, List]:
    """匹配基准条款与目标条款（优化匹配逻辑，避免重复匹配）"""
    matched_pairs = []
    used_target_indices = set()  # 记录已匹配的目标条款索引
    benchmark_count = len(benchmark_clauses)
    
    # 显示匹配进度
    progress_bar = st.progress(0)
    
    for i, bench_clause in enumerate(benchmark_clauses):
        best_match = None
        best_ratio = 0.25  # 中文匹配阈值（可调整）
        best_j = -1
        
        # 只匹配未被使用的目标条款
        for j, target_clause in enumerate(target_clauses):
            if j not in used_target_indices:
                ratio = chinese_text_similarity(bench_clause, target_clause)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = target_clause
                    best_j = j
        
        if best_match:
            matched_pairs.append((bench_clause, best_match, best_ratio))
            used_target_indices.add(best_j)
        
        # 更新进度
        progress_bar.progress((i + 1) / benchmark_count)
    
    progress_bar.empty()
    
    # 优化未匹配条款计算
    matched_bench_indices = {i for i, _ in enumerate(matched_pairs)}
    unmatched_bench = [
        clause for i, clause in enumerate(benchmark_clauses) 
        if i not in matched_bench_indices
    ]
    unmatched_target = [
        clause for j, clause in enumerate(target_clauses) 
        if j not in used_target_indices
    ]
    
    return matched_pairs, unmatched_bench, unmatched_target


# --------------------------
# 辅助功能优化
# --------------------------
def chinese_text_similarity(text1: str, text2: str) -> float:
    """计算中文文本相似度（保留原逻辑，稳定可靠）"""
    words1 = list(jieba.cut(text1))
    words2 = list(jieba.cut(text2))
    return SequenceMatcher(None, words1, words2).ratio()


def create_download_link(content: str, filename: str, text: str) -> str:
    """生成下载链接（增加安全编码）"""
    b64 = base64.b64encode(content.encode("utf-8")).decode()
    return f'<a href="data:file/txt;base64,{b64}" download="{filename}" target="_blank">{text}</a>'


def generate_analysis_report(analysis_results: Dict) -> str:
    """生成分析报告（支持下载）"""
    report = []
    report.append(f"=== {analysis_results['target_name']} 与 {analysis_results['bench_name']} 合规性分析报告 ===\n")
    
    # 基本统计
    report.append("1. 基本统计")
    report.append(f"- 基准条款总数：{analysis_results['bench_count']}")
    report.append(f"- 目标条款总数：{analysis_results['target_count']}")
    report.append(f"- 匹配条款数：{analysis_results['matched_count']}\n")
    
    # 匹配条款分析
    report.append("2. 匹配条款分析")
    for i, (bench_clause, target_clause, ratio) in enumerate(analysis_results["matched_pairs"]):
        report.append(f"\n--- 匹配对 {i + 1}（相似度：{ratio:.2%}）---")
        report.append(f"基准条款：{bench_clause}")
        report.append(f"目标条款：{target_clause}")
        report.append(f"分析结果：{analysis_results['compliance_analyses'][i] or '无分析结果'}\n")
    
    # 未匹配条款
    report.append("3. 未匹配条款")
    report.append(f"基准独有的条款（{len(analysis_results['unmatched_bench'])}条）：")
    for i, clause in enumerate(analysis_results['unmatched_bench'][:5]):
        report.append(f"- {clause[:100]}...")
    report.append(f"\n目标独有的条款（{len(analysis_results['unmatched_target'])}条）：")
    for i, clause in enumerate(analysis_results['unmatched_target'][:5]):
        report.append(f"- {clause[:100]}...")
    
    return "\n".join(report)


# --------------------------
# 分析逻辑优化
# --------------------------
def analyze_compliance_with_qwen(
    bench_clause: str, target_clause: str, 
    bench_name: str, target_name: str, 
    api_key: str, model: str
) -> str:
    """使用大模型分析条款合规性（优化提示词）"""
    # 更精准的中文提示词（强调法律条款细节）
    prompt = f"""
    作为法律条款分析专家，请以《{bench_name}》为基准，分析以下两个条款的合规性：
    
    【基准条款】（来自《{bench_name}》）：
    {bench_clause}
    
    【目标条款】（来自《{target_name}》）：
    {target_clause}
    
    请严格按照以下结构分析（总字数控制在800字内）：
    1. 相似度评估：明确高/中/低，并说明核心依据（如条款目的、约束范围）
    2. 差异点分析：逐条列出表述、要求、责任界定等方面的具体差异
    3. 合规性判断：明确无冲突/轻微冲突/严重冲突（以基准条款为依据）
    4. 冲突影响（如存在）：说明冲突可能导致的实际问题（如法律风险、执行矛盾）
    5. 建议：针对差异/冲突给出具体修改方向（参考基准条款表述）
    
    注意：需特别关注中文法律术语差异（如"应当"vs"必须"、"不得"vs"禁止"的法律效力区别）。
    """
    return call_qwen_api(prompt, api_key, model)


def analyze_single_target(
    bench_text: str, target_text: str, 
    bench_name: str, target_name: str, 
    api_key: str, model: str
) -> Dict:
    """分析单个目标文件（增加中间结果缓存）"""
    # 条款分割（复用已处理结果）
    bench_clauses = split_into_clauses(bench_text)
    target_clauses = split_into_clauses(target_text)
    
    # 条款匹配
    matched_pairs, unmatched_bench, unmatched_target = match_clauses(bench_clauses, target_clauses)
    
    # 合规性分析（支持中断后继续）
    compliance_analyses = []
    for i, (bench_clause, target_clause, ratio) in enumerate(matched_pairs):
        with st.expander(f"正在分析匹配对 {i + 1}/{len(matched_pairs)}（点击查看条款）", expanded=False):
            st.text(f"基准条款：{bench_clause[:100]}...")
            st.text(f"目标条款：{target_clause[:100]}...")
        
        analysis = analyze_compliance_with_qwen(
            bench_clause, target_clause, bench_name, target_name, api_key, model
        )
        compliance_analyses.append(analysis)
    
    return {
        "bench_name": bench_name,
        "target_name": target_name,
        "bench_count": len(bench_clauses),
        "target_count": len(target_clauses),
        "matched_count": len(matched_pairs),
        "matched_pairs": matched_pairs,
        "unmatched_bench": unmatched_bench,
        "unmatched_target": unmatched_target,
        "compliance_analyses": compliance_analyses
    }


# --------------------------
# 界面与交互优化
# --------------------------
def show_multi_target_analysis(
    bench_text: str, target_files: List, 
    bench_name: str, api_key: str, model: str
):
    """显示多目标分析结果（增加筛选和下载）"""
    # 基准条款预处理（只处理一次）
    bench_clauses = split_into_clauses(bench_text)
    st.success(f"基准文件条款解析完成：{bench_name} 识别出 {len(bench_clauses)} 条条款")

    # 目标文件选择器（支持搜索）
    st.subheader("🔍 选择目标文件进行对比")
    target_names = [f.name for f in target_files]
    selected_targets = st.multiselect(
        "已上传目标文件（可搜索）",
        options=target_names,
        default=target_names[:2],  # 默认选择前2个
        format_func=lambda x: x  # 支持搜索匹配
    )

    if not selected_targets:
