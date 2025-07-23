import streamlit as st
from PyPDF2 import PdfReader
from difflib import SequenceMatcher
import base64
import re
import requests
import jieba
from typing import List, Tuple, Dict

# 页面配置
st.set_page_config(
    page_title="Qwen 中文PDF条款合规性分析工具（1对多）",
    page_icon="📄",
    layout="wide"
)

# 自定义样式（增强视觉区分度）
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
</style>
""", unsafe_allow_html=True)

# API配置
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

def call_qwen_api(prompt: str, api_key: str) -> str:
    """调用Qwen大模型API"""
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
            "max_tokens": 1500
        }
        
        response = requests.post(
            QWEN_API_URL,
            headers=headers,
            json=data,
            timeout=60
        )
        
        if response.status_code != 200:
            st.error(f"API请求失败，状态码: {response.status_code}，响应: {response.text}")
            return None
            
        response_json = response.json()
        if "choices" not in response_json or len(response_json["choices"]) == 0:
            st.error("API返回格式不符合预期")
            return None
            
        return response_json["choices"][0]["message"]["content"]
        
    except requests.exceptions.Timeout:
        st.error("API请求超时，请重试")
        return None
    except Exception as e:
        st.error(f"调用Qwen API失败: {str(e)}")
        return None

def extract_text_from_pdf(file) -> str:
    """从PDF提取文本（优化中文处理）"""
    try:
        pdf_reader = PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text() or ""
            # 处理中文排版问题
            page_text = page_text.replace("  ", "").replace("\n", "").replace("\r", "")
            text += page_text
        return text
    except Exception as e:
        st.error(f"提取文本失败: {str(e)}")
        return ""

def split_into_clauses(text: str) -> List[str]:
    """将文本分割为条款（增强中文条款识别）"""
    patterns = [
        r'(第[一二三四五六七八九十百]+条\s+.*?)(?=第[一二三四五六七八九十百]+条\s+|$)',
        r'([一二三四五六七八九十]+、\s+.*?)(?=[一二三四五六七八九十]+、\s+|$)',
        r'(\d+\.\s+.*?)(?=\d+\.\s+|$)',
        r'(\([一二三四五六七八九十]+\)\s+.*?)(?=\([一二三四五六七八九十]+\)\s+|$)',
        r'(\([1-9]+\)\s+.*?)(?=\([1-9]+\)\s+|$)',
        r'(【[^\】]+】\s+.*?)(?=【[^\】]+】\s+|$)'
    ]
    
    for pattern in patterns:
        clauses = re.findall(pattern, text, re.DOTALL)
        if len(clauses) > 3:
            return [clause.strip() for clause in clauses if clause.strip()]
    
    # 兜底分割方案
    paragraphs = re.split(r'[。；！？]\s*', text)
    return [p.strip() for p in paragraphs if p.strip() and len(p) > 10]

def chinese_text_similarity(text1: str, text2: str) -> float:
    """计算中文文本相似度（分词优化）"""
    words1 = list(jieba.cut(text1))
    words2 = list(jieba.cut(text2))
    return SequenceMatcher(None, words1, words2).ratio()

def match_clauses(benchmark_clauses: List[str], target_clauses: List[str]) -> Tuple[List, List, List]:
    """匹配基准条款与目标条款"""
    matched_pairs = []
    used_indices = set()
    
    for i, bench_clause in enumerate(benchmark_clauses):
        best_match = None
        best_ratio = 0.25  # 中文匹配阈值
        best_j = -1
        
        for j, target_clause in enumerate(target_clauses):
            if j not in used_indices:
                ratio = chinese_text_similarity(bench_clause, target_clause)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = target_clause
                    best_j = j
        
        if best_match:
            matched_pairs.append((bench_clause, best_match, best_ratio))
            used_indices.add(best_j)
    
    unmatched_bench = [clause for i, clause in enumerate(benchmark_clauses) 
                     if i not in [idx for idx, _ in enumerate(matched_pairs)]]
    unmatched_target = [clause for j, clause in enumerate(target_clauses) if j not in used_indices]
    
    return matched_pairs, unmatched_bench, unmatched_target

def create_download_link(content: str, filename: str, text: str) -> str:
    """生成下载链接"""
    b64 = base64.b64encode(content.encode()).decode()
    return f'<a href="data:file/txt;base64,{b64}" download="{filename}">{text}</a>'

def analyze_compliance_with_qwen(bench_clause: str, target_clause: str, 
                                bench_name: str, target_name: str, api_key: str) -> str:
    """使用大模型分析条款合规性"""
    prompt = f"""
    请分析以下两个条款的合规性（以{bench_name}为基准）：
    
    {bench_name}条款：{bench_clause}
    {target_name}条款：{target_clause}
    
    按以下结构回答：
    1. 相似度评估：高/中/低及理由
    2. 差异点分析：表述、范围、要求的具体差异
    3. 合规性判断：无冲突/轻微冲突/严重冲突
    4. 冲突原因（如存在）：具体原因及潜在影响
    5. 建议：专业处理建议
    
    注意中文法律术语差异（如"应当"与"必须"、"不得"与"禁止"）
    """
    return call_qwen_api(prompt, api_key)

def analyze_standalone_clause_with_qwen(clause: str, doc_name: str, api_key: str) -> str:
    """分析独立条款"""
    prompt = f"""
    分析以下条款（来自{doc_name}）：{clause}
    请评估：主要内容、核心要求、潜在影响及可能存在的问题，给出建议。
    """
    return call_qwen_api(prompt, api_key)

def analyze_single_target(bench_text: str, target_text: str, 
                         bench_name: str, target_name: str, api_key: str) -> Dict:
    """分析单个目标文件与基准文件的对比结果"""
    # 条款分割
    bench_clauses = split_into_clauses(bench_text)
    target_clauses = split_into_clauses(target_text)
    
    # 条款匹配
    matched_pairs, unmatched_bench, unmatched_target = match_clauses(bench_clauses, target_clauses)
    
    # 生成分析结果
    analysis_results = {
        "bench_name": bench_name,
        "target_name": target_name,
        "bench_count": len(bench_clauses),
        "target_count": len(target_clauses),
        "matched_count": len(matched_pairs),
        "matched_pairs": matched_pairs,
        "unmatched_bench": unmatched_bench,
        "unmatched_target": unmatched_target,
        "compliance_analyses": []
    }
    
    # 合规性分析
    for bench_clause, target_clause, ratio in matched_pairs:
        analysis = analyze_compliance_with_qwen(
            bench_clause, target_clause, bench_name, target_name, api_key
        )
        analysis_results["compliance_analyses"].append(analysis)
    
    return analysis_results

def show_multi_target_analysis(bench_text: str, target_files: List, 
                              bench_name: str, api_key: str):
    """显示多目标文件分析结果"""
    # 基准条款预处理
    bench_clauses = split_into_clauses(bench_text)
    st.success(f"基准文件条款解析完成：{bench_name} 识别出 {len(bench_clauses)} 条条款")

    # 目标文件选择器
    st.subheader("🔍 选择目标文件进行对比")
    selected_targets = st.multiselect(
        "已上传目标文件",
        options=[f.name for f in target_files],
        default=[f.name for f in target_files[:2]]  # 默认选择前2个
    )

    if not selected_targets:
        st.info("请至少选择一个目标文件")
        return

    # 批量分析
    for target_name in selected_targets:
        # 找到对应的文件对象
        target_file = next(f for f in target_files if f.name == target_name)
        target_text = extract_text_from_pdf(target_file)
        
        if not target_text:
            st.error(f"无法提取 {target_name} 的文本内容")
            continue

        # 显示单个目标分析结果
        st.divider()
        st.header(f"📌 {target_name} 与 {bench_name} 对比分析")
        
        # 执行分析
        with st.spinner(f"正在分析 {target_name}..."):
            result = analyze_single_target(
                bench_text, target_text, bench_name, target_name, api_key
            )
        
        # 统计信息
        col1, col2, col3 = st.columns(3)
        col1.metric("基准条款数", result["bench_count"])
        col2.metric(f"{target_name} 条款数", result["target_count"])
        col3.metric("匹配条款数", result["matched_count"])

        # 详细分析
        st.subheader("条款匹配及合规性分析")
        for i in range(result["matched_count"]):
            st.markdown(f"### 匹配对 {i+1}（相似度: {result['matched_pairs'][i][2]:.2%}）")
            
            # 条款对比展示
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f'<div class="clause-box compliance-ok"><strong>{bench_name} 条款:</strong><br>{result["matched_pairs"][i][0]}</div>', unsafe_allow_html=True)
            with col_b:
                st.markdown(f'<div class="clause-box"><strong>{target_name} 条款:</strong><br>{result["matched_pairs"][i][1]}</div>', unsafe_allow_html=True)
            
            # 合规性分析结果
            if result["compliance_analyses"][i]:
                st.markdown(
                    f'<div class="model-response"><strong>合规性分析:</strong><br>{result["compliance_analyses"][i]}</div>',
                    unsafe_allow_html=True
                )
            st.divider()

        # 未匹配条款
        st.subheader("未匹配条款分析")
        col_un1, col_un2 = st.columns(2)
        with col_un1:
            st.markdown(f"#### {bench_name} 独有的条款（{len(result['unmatched_bench'])}）")
            for i, clause in enumerate(result["unmatched_bench"][:5]):  # 显示前5条
                st.markdown(f'<div class="clause-box"><strong>条款 {i+1}:</strong><br>{clause}</div>', unsafe_allow_html=True)
                if i >= 4:
                    st.text(f"... 共 {len(result['unmatched_bench'])} 条（仅显示前5条）")
                    break

        with col_un2:
            st.markdown(f"#### {target_name} 独有的条款（{len(result['unmatched_target'])}）")
            for i, clause in enumerate(result["unmatched_target"][:5]):
                st.markdown(f'<div class="clause-box"><strong>条款 {i+1}:</strong><br>{clause}</div>', unsafe_allow_html=True)
                if i >= 4:
                    st.text(f"... 共 {len(result['unmatched_target'])} 条（仅显示前5条）")
                    break

# 主界面
def main():
    st.title("📄 Qwen 中文PDF条款合规性分析工具（1对多）")
    st.markdown("支持1个基准文件与多个目标文件的条款合规性比对")

    # 侧边栏API设置
    with st.sidebar:
        st.subheader("Qwen API 设置")
        qwen_api_key = st.text_input("请输入Qwen API密钥", type="password")
        st.markdown(f"当前API端点：`{QWEN_API_URL}`")
        st.divider()
        st.info("使用说明：\n1. 上传1个基准文件\n2. 上传多个目标文件\n3. 选择目标文件进行对比")

    # 文件上传区（参考图片布局）
    st.subheader("📂 文件上传区")
    
    # 基准文件上传
    st.markdown('<div class="file-selector"><span class="benchmark-label">基准文件（必填）：</span>选择作为合规性判断依据的文件</div>', unsafe_allow_html=True)
    bench_file = st.file_uploader(
        "上传基准文件（仅支持PDF）",
        type=["pdf"],
        key="benchmark",
        accept_multiple_files=False
    )

    # 目标文件上传
    st.markdown('<div class="file-selector"><span class="target-label">目标文件（可多个）：</span>需要进行合规性检查的文件</div>', unsafe_allow_html=True)
    target_files = st.file_uploader(
        "上传目标文件（仅支持PDF）",
        type=["pdf"],
        key="targets",
        accept_multiple_files=True
    )

    # 分析按钮
    if st.button("开始1对多合规性分析", type="primary"):
        if not bench_file:
            st.error("请先上传基准文件")
            return
        if not target_files:
            st.error("请至少上传一个目标文件")
            return

        # 基准文件处理
        with st.spinner("正在解析基准文件..."):
            bench_text = extract_text_from_pdf(bench_file)
            if not bench_text:
                st.error("无法提取基准文件文本，请检查文件有效性")
                return

        # 显示分析结果
        show_multi_target_analysis(bench_text, target_files, bench_file.name, qwen_api_key)

    # 页脚
    st.divider()
    st.markdown("""
    <div style="text-align:center; color:#666; margin-top:20px;">
        中文PDF条款合规性分析工具（1对多版） | 基于Qwen大模型
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
