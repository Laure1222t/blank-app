import streamlit as st
from PyPDF2 import PdfReader
from difflib import SequenceMatcher
import base64
import re
import requests
import jieba
from io import StringIO
import time
from typing import List, Tuple, Optional

# 页面设置
st.set_page_config(
    page_title="多文件基准合规性分析工具",
    page_icon="📊",
    layout="wide"
)

# 自定义样式
st.markdown("""
<style>
    .stApp { max-width: 1400px; margin: 0 auto; }
    .analysis-card { border: 1px solid #e0e0e0; border-radius: 8px; padding: 15px; margin: 10px 0; }
    .conflict-highlight { background-color: #fff3cd; padding: 2px 4px; border-radius: 2px; }
    .progress-container { margin: 20px 0; }
</style>
""", unsafe_allow_html=True)

# API配置
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# 会话状态初始化
if 'analysis_progress' not in st.session_state:
    st.session_state.analysis_progress = 0
if 'partial_reports' not in st.session_state:
    st.session_state.partial_reports = {}
if 'current_analysis' not in st.session_state:
    st.session_state.current_analysis = None

def call_qwen_api(prompt: str, api_key: str) -> Optional[str]:
    """调用API并实现重试机制"""
    retries = 2
    delay = 3
    
    for attempt in range(retries):
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            
            data = {
                "model": "qwen-plus",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 1500
            }
            
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
                
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay)
                continue
                
    return None

def extract_text_from_pdf(file) -> str:
    """从PDF提取文本"""
    try:
        pdf_reader = PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text() or ""
            page_text = page_text.replace("  ", "").replace("\n", "").replace("\r", "")
            text += page_text
        return text
    except Exception as e:
        st.error(f"提取文本失败: {str(e)}")
        return ""

def split_into_clauses(text: str, max_clauses: int = 30) -> List[str]:
    """分割文本为条款"""
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
            return [clause.strip() for clause in clauses if clause.strip()][:max_clauses]
    
    paragraphs = re.split(r'[。；！？]\s*', text)
    return [p.strip() for p in paragraphs if p.strip() and len(p) > 10][:max_clauses]

def chinese_text_similarity(text1: str, text2: str) -> float:
    """计算中文文本相似度"""
    words1 = list(jieba.cut(text1))
    words2 = list(jieba.cut(text2))
    return SequenceMatcher(None, words1, words2).ratio()

def match_clauses_with_base(base_clauses: List[str], target_clauses: List[str]) -> List[Tuple[str, str, float]]:
    """将目标文件条款与基准文件条款匹配"""
    matched_pairs = []
    used_indices = set()
    
    for base_clause in base_clauses:
        best_match = None
        best_ratio = 0.3  # 匹配阈值
        best_idx = -1
        
        for idx, target_clause in enumerate(target_clauses):
            if idx not in used_indices:
                ratio = chinese_text_similarity(base_clause, target_clause)
                if ratio > best_ratio and ratio > best_ratio:
                    best_ratio = ratio
                    best_match = target_clause
                    best_idx = idx
        
        if best_match:
            matched_pairs.append((base_clause, best_match, best_ratio))
            used_indices.add(best_idx)
    
    return matched_pairs

def analyze_compliance_with_base(base_clause: str, target_clause: str, 
                               base_name: str, target_name: str, 
                               api_key: str) -> Optional[str]:
    """分析目标条款与基准条款的合规性"""
    prompt = f"""
    请以{base_name}为基准，分析以下条款的合规性：
    
    基准条款（{base_name}）：{base_clause}
    
    目标条款（{target_name}）：{target_clause}
    
    请重点分析：
    1. 目标条款是否符合基准条款的要求
    2. 存在哪些偏离或冲突之处（需具体指出）
    3. 偏离程度评估（完全符合/轻微偏离/严重偏离）
    4. 导致偏离的关键原因
    5. 如何修改目标条款以符合基准要求
    
    请用专业、简洁的中文回答，聚焦合规性问题。
    """
    
    return call_qwen_api(prompt, api_key)

def generate_target_report(matched_pairs: List[Tuple[str, str, float]],
                          base_name: str, target_name: str,
                          api_key: str, target_index: int, total_targets: int) -> str:
    """为单个目标文件生成与基准文件的对比报告"""
    report = []
    report.append("="*60)
    report.append(f"条款合规性分析报告: {target_name} 与 {base_name} 对比")
    report.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("="*60 + "\n")
    
    # 总体统计
    report.append(f"分析概要: 共匹配 {len(matched_pairs)} 条条款\n")
    report.append("-"*60 + "\n")
    
    # 进度跟踪
    progress_container = st.empty()
    total_pairs = len(matched_pairs)
    
    # 分析每对条款
    for i, (base_clause, target_clause, ratio) in enumerate(matched_pairs):
        # 更新全局进度 (考虑多个目标文件的总进度)
        global_progress = (target_index * total_pairs + i) / (total_targets * total_pairs) if total_targets > 0 else 0
        st.session_state.analysis_progress = global_progress
        progress_container.progress(global_progress)
        
        report.append(f"条款对 {i+1} (相似度: {ratio:.2%})")
        report.append(f"基准条款: {base_clause[:200]}...")
        report.append(f"目标条款: {target_clause[:200]}...\n")
        
        # 合规性分析
        with st.spinner(f"正在分析 {target_name} 的条款 {i+1}/{total_pairs}..."):
            analysis = analyze_compliance_with_base(
                base_clause, target_clause, 
                base_name, target_name, 
                api_key
            )
        
        if analysis:
            report.append("合规性分析结果:")
            report.append(analysis)
        else:
            report.append("合规性分析结果: 无法获取有效的分析结果")
        
        report.append("\n" + "-"*60 + "\n")
        
        # 保存部分结果
        st.session_state.partial_reports[target_name] = report.copy()
        time.sleep(1)  # 控制API调用频率
    
    # 目标文件总体评估
    if matched_pairs:
        with st.spinner(f"生成 {target_name} 的总体评估..."):
            summary_prompt = f"""
            基于对{target_name}与基准文件{base_name}的{len(matched_pairs)}对条款的对比分析，
            请评估{target_name}整体符合基准的程度，包括：
            1. 总体合规性评分（1-10分）及理由
            2. 最主要的不合规点
            3. 整体修改建议
            """
            summary = call_qwen_api(summary_prompt, api_key)
            
            if summary:
                report.append("="*60)
                report.append(f"{target_name} 与 {base_name} 总体合规性评估")
                report.append("="*60)
                report.append(summary)
    
    return "\n".join(report)

def generate_combined_summary(reports: dict, base_name: str, api_key: str) -> Optional[str]:
    """生成所有文件与基准对比的综合摘要"""
    if not reports:
        return None
        
    target_names = list(reports.keys())
    summary_prompt = f"""
    以下是{len(target_names)}个文件与基准文件{base_name}的合规性分析结果摘要。
    请综合这些结果，生成一份总体摘要报告：
    
    """
    
    # 为每个目标文件添加关键信息
    for name, report in reports.items():
        summary_prompt += f"文件 {name} 的分析要点：\n"
        summary_prompt += f"{report[:1000]}...\n\n"  # 取报告开头部分作为摘要依据
    
    summary_prompt += """
    请基于以上信息，生成综合评估：
    1. 所有文件的整体合规性对比
    2. 各文件共同存在的合规性问题
    3. 各文件特有的合规性问题
    4. 针对所有文件的优先级修改建议
    """
    
    return call_qwen_api(summary_prompt, api_key)

def get_download_link(text: str, filename: str) -> str:
    """生成报告下载链接"""
    b64 = base64.b64encode(text.encode()).decode()
    return f'<a href="data:text/plain;base64,{b64}" download="{filename}" style="display:inline-block;padding:8px 16px;background-color:#007bff;color:white;text-decoration:none;border-radius:4px;margin:5px 0;">下载 {filename}</a>'

def main():
    st.title("多文件基准合规性分析工具")
    st.write("上传一个基准文件和多个目标文件，系统将分析所有目标文件与基准文件的条款合规性")
    
    # 侧边栏设置
    with st.sidebar:
        st.subheader("分析设置")
        api_key = st.text_input("Qwen API密钥", type="password")
        max_clauses = st.slider("每个文件最大分析条款数", 5, 50, 20)
        st.info("条款数量越少，分析速度越快，成功率越高")
    
    # 文件上传区域
    st.subheader("1. 上传基准文件")
    base_file = st.file_uploader("上传基准PDF文件（作为合规性标准）", type="pdf", key="base_file")
    
    st.subheader("2. 上传目标文件")
    target_files = st.file_uploader(
        "上传一个或多个需要检查的PDF文件", 
        type="pdf", 
        key="target_files",
        accept_multiple_files=True
    )
    
    # 分析控制
    if st.button("开始合规性分析", disabled=not (base_file and target_files and api_key)):
        try:
            # 处理基准文件
            with st.spinner("正在处理基准文件..."):
                base_text = extract_text_from_pdf(base_file)
                if not base_text:
                    st.error("无法从基准文件中提取文本")
                    return
                
                base_clauses = split_into_clauses(base_text, max_clauses)
                st.success(f"基准文件处理完成: {base_file.name} 提取到 {len(base_clauses)} 条条款")
            
            # 准备存储所有报告
            all_reports = {}
            total_targets = len(target_files)
            
            # 显示总体进度
            global_progress_bar = st.progress(0)
            
            # 处理每个目标文件
            for target_idx, target_file in enumerate(target_files, 1):
                st.subheader(f"正在分析目标文件 {target_idx}/{total_targets}: {target_file.name}")
                
                # 提取目标文件文本和条款
                with st.spinner(f"提取 {target_file.name} 的条款..."):
                    target_text = extract_text_from_pdf(target_file)
                    if not target_text:
                        st.warning(f"无法从 {target_file.name} 中提取文本，跳过该文件")
                        continue
                    
                    target_clauses = split_into_clauses(target_text, max_clauses)
                    st.info(f"{target_file.name} 提取到 {len(target_clauses)} 条条款")
                
                # 匹配条款
                with st.spinner(f"匹配 {target_file.name} 与基准文件的条款..."):
                    matched_pairs = match_clauses_with_base(base_clauses, target_clauses)
                    
                    if not matched_pairs:
                        st.warning(f"{target_file.name} 未找到与基准文件匹配的条款，无法分析")
                        continue
                    
                    st.info(f"找到 {len(matched_pairs)} 对可对比的条款")
                
                # 生成分析报告
                report = generate_target_report(
                    matched_pairs,
                    base_file.name,
                    target_file.name,
                    api_key,
                    target_idx - 1,  # 0-based index
                    total_targets
                )
                
                all_reports[target_file.name] = report
                
                # 显示单个文件分析结果
                st.success(f"{target_file.name} 分析完成！")
                st.markdown(get_download_link(report, f"{target_file.name}_vs_{base_file.name}_合规性报告.txt"), unsafe_allow_html=True)
                
                with st.expander(f"查看 {target_file.name} 的分析报告预览"):
                    st.text_area("报告内容", report, height=300)
                
                # 更新总体进度
                global_progress = target_idx / total_targets
                global_progress_bar.progress(global_progress)
            
            # 生成综合摘要（如果有多个目标文件）
            if len(all_reports) > 1:
                with st.spinner("生成所有文件的综合合规性摘要..."):
                    combined_summary = generate_combined_summary(all_reports, base_file.name, api_key)
                    
                    if combined_summary:
                        st.subheader("📋 所有文件综合合规性评估")
                        st.text_area("综合评估内容", combined_summary, height=400)
                        summary_filename = f"所有文件与{base_file.name}_综合评估.txt"
                        st.markdown(get_download_link(combined_summary, summary_filename), unsafe_allow_html=True)
            
            # 最终提示
            st.balloons()
            st.success("所有文件分析完成！")
                
        except Exception as e:
            st.error(f"分析过程出错: {str(e)}")
            
            # 显示已完成的部分结果
            if st.session_state.partial_reports:
                st.warning("已完成部分分析结果：")
                for name, partial_report in st.session_state.partial_reports.items():
                    report_text = "\n".join(partial_report)
                    st.markdown(get_download_link(report_text, f"部分_{name}_vs_{base_file.name}_合规性报告.txt"), unsafe_allow_html=True)

if __name__ == "__main__":
    main()
    
