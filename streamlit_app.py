import streamlit as st
from PyPDF2 import PdfReader
from difflib import SequenceMatcher
import base64
import re
import requests
import jieba  # 用于中文分词，提高匹配精度

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
</style>
""", unsafe_allow_html=True)

# 配置Qwen API参数 - 使用指定的API链接
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

def call_qwen_api(prompt, api_key):
    """调用Qwen大模型API，使用指定的API链接"""
    if not api_key:
        st.error("Qwen API密钥未设置，请在左侧栏输入密钥")
        return None
        
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        # 构建符合API要求的请求数据
        data = {
            "model": "qwen-plus",  # 可根据需要更换为其他Qwen模型如qwen-max
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 5000
        }
        
        # 使用指定的API链接发送POST请求
        response = requests.post(
            QWEN_API_URL,
            headers=headers,
            json=data,
            timeout=60
        )
        
        # 检查HTTP响应状态
        if response.status_code != 200:
            st.error(f"API请求失败，状态码: {response.status_code}，响应: {response.text}")
            return None
            
        # 解析JSON响应
        response_json = response.json()
        
        # 检查响应结构
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

def extract_text_from_pdf(file):
    """从PDF提取文本，优化中文处理"""
    try:
        pdf_reader = PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text() or ""
            # 处理中文空格和换行问题
            page_text = page_text.replace("  ", "").replace("\n", "").replace("\r", "")
            text += page_text
        return text
    except Exception as e:
        st.error(f"提取文本失败: {str(e)}")
        return ""

def split_into_clauses(text):
    """将文本分割为条款，增强中文条款识别"""
    # 增强中文条款模式识别
    patterns = [
        # 中文条款常见格式
        r'(第[一二三四五六七八九十百]+条\s+.*?)(?=第[一二三四五六七八九十百]+条\s+|$)',  # 第一条、第二条格式
        r'([一二三四五六七八九十]+、\s+.*?)(?=[一二三四五六七八九十]+、\s+|$)',  # 一、二、三、格式
        r'(\d+\.\s+.*?)(?=\d+\.\s+|$)',  # 1. 2. 3. 格式
        r'(\([一二三四五六七八九十]+\)\s+.*?)(?=\([一二三四五六七八九十]+\)\s+|$)',  # (一) (二) 格式
        r'(\([1-9]+\)\s+.*?)(?=\([1-9]+\)\s+|$)',  # (1) (2) 格式
        r'(【[^\】]+】\s+.*?)(?=【[^\】]+】\s+|$)'  # 【标题】格式
    ]
    
    for pattern in patterns:
        clauses = re.findall(pattern, text, re.DOTALL)
        if len(clauses) > 3:  # 确保找到足够多的条款
            return [clause.strip() for clause in clauses if clause.strip()]
    
    # 按中文标点分割段落
    paragraphs = re.split(r'[。；！？]\s*', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip() and len(p) > 10]  # 过滤过短内容
    return paragraphs

def chinese_text_similarity(text1, text2):
    """计算中文文本相似度，使用分词后匹配"""
    # 使用jieba进行中文分词
    words1 = list(jieba.cut(text1))
    words2 = list(jieba.cut(text2))
    
    # 计算分词后的相似度
    return SequenceMatcher(None, words1, words2).ratio()

def match_clauses_with_multiple(reference_clauses, other_clauses_list, other_filenames):
    """将参考文档条款与多个其他文档条款进行匹配"""
    all_matched_pairs = []  # 存储格式: (参考条款, 其他文档条款, 相似度, 其他文档名称)
    all_used_indices = [set() for _ in other_clauses_list]  # 每个文档维护一个已使用条款索引集合
    
    for ref_clause in reference_clauses:
        best_matches = []  # 存储每个文档的最佳匹配
        
        # 为每个比较文档找到最佳匹配
        for doc_idx, (other_clauses, used_indices) in enumerate(zip(other_clauses_list, all_used_indices)):
            best_match = None
            best_ratio = 0.25  # 中文匹配阈值
            best_j = -1
            
            for j, other_clause in enumerate(other_clauses):
                if j not in used_indices:
                    ratio = chinese_text_similarity(ref_clause, other_clause)
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_match = other_clause
                        best_j = j
            
            if best_match:
                best_matches.append({
                    "clause": best_match,
                    "ratio": best_ratio,
                    "index": best_j,
                    "doc_name": other_filenames[doc_idx]
                })
                all_used_indices[doc_idx].add(best_j)
        
        if best_matches:
            all_matched_pairs.append({
                "reference_clause": ref_clause,
                "matches": best_matches
            })
    
    # 计算每个文档的未匹配条款
    unmatched = []
    for doc_idx, (other_clauses, used_indices) in enumerate(zip(other_clauses_list, all_used_indices)):
        unmatched_clauses = [
            clause for j, clause in enumerate(other_clauses) 
            if j not in used_indices
        ]
        unmatched.append({
            "doc_name": other_filenames[doc_idx],
            "clauses": unmatched_clauses
        })
    
    # 计算参考文档中未匹配的条款
    matched_ref_indices = set()
    for i, match_group in enumerate(all_matched_pairs):
        if match_group["matches"]:  # 如果有任何匹配
            matched_ref_indices.add(i)
    
    unmatched_reference = [
        clause for i, clause in enumerate(reference_clauses)
        if i not in matched_ref_indices
    ]
    
    return all_matched_pairs, unmatched_reference, unmatched

def create_download_link(content, filename, text):
    """生成下载链接"""
    b64 = base64.b64encode(content.encode()).decode()
    return f'<a href="data:file/txt;base64,{b64}" download="{filename}">{text}</a>'

def analyze_compliance_with_qwen_multiple(reference_clause, other_clauses_info, reference_filename, api_key):
    """使用Qwen大模型分析参考条款与多个其他条款的合规性"""
    # 构建比较条款部分
    other_clauses_text = ""
    for info in other_clauses_info:
        other_clauses_text += f"\n{info['doc_name']} 条款: {info['clause']} (相似度: {info['ratio']:.2%})"
    
    prompt = f"""
    请仔细分析以下参考条款与多个其他文档条款的合规性，判断它们之间是否存在冲突：
    
    参考文档 ({reference_filename}) 条款：{reference_clause}
    
    其他文档条款：{other_clauses_text}
    
    请按照以下结构用中文进行详细分析：
    1. 相似度评估：分别评估参考条款与每个其他条款的相似程度（高/中/低）
    2. 差异点分析：简要指出参考条款与每个其他条款在表述、范围、要求等方面的主要差异
    3. 合规性判断：判断参考条款与每个其他条款是否存在冲突（无冲突/轻微冲突/严重冲突）
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

def show_compliance_analysis(reference_text, reference_filename, other_texts, other_filenames, api_key):
    """显示1对多合规性分析结果"""
    # 分割条款
    with st.spinner("正在分析中文条款结构..."):
        reference_clauses = split_into_clauses(reference_text)
        other_clauses_list = [split_into_clauses(text) for text in other_texts]
        
        st.success(f"条款分析完成: {reference_filename} 识别出 {len(reference_clauses)} 条条款")
        for doc_name, clauses in zip(other_filenames, other_clauses_list):
            st.success(f"{doc_name} 识别出 {len(clauses)} 条条款")
    
    # 匹配条款
    with st.spinner("正在匹配相似条款..."):
        matched_pairs, unmatched_reference, unmatched_others = match_clauses_with_multiple(
            reference_clauses, other_clauses_list, other_filenames
        )
    
    # 显示总体统计
    st.divider()
    stats_cols = st.columns(len(other_filenames) + 1)
    stats_cols[0].metric(f"{reference_filename} 条款数", len(reference_clauses))
    for i, (doc_name, clauses) in enumerate(zip(other_filenames, other_clauses_list)):
        stats_cols[i+1].metric(f"{doc_name} 条款数", len(clauses))
    
    st.metric("匹配条款组数量", len(matched_pairs))
    
    # 显示条款对比和合规性分析
    st.divider()
    st.subheader("📊 条款合规性详细分析（Qwen大模型）")
    
    # 分析每个匹配组的合规性
    for i, match_group in enumerate(matched_pairs):
        reference_clause = match_group["reference_clause"]
        matches = match_group["matches"]
        
        st.markdown(f"### 匹配组 {i+1}")
        
        # 显示参考条款
        st.markdown(f'<div class="clause-box"><strong>{reference_filename} 参考条款:</strong><br>{reference_clause}</div>', unsafe_allow_html=True)
        
        # 显示所有匹配的其他条款
        for match in matches:
            st.markdown(f'<div class="clause-box"><strong>{match["doc_name"]} 匹配条款 (相似度: {match["ratio"]:.2%}):</strong><br>{match["clause"]}</div>', unsafe_allow_html=True)
        
        with st.spinner("正在调用Qwen大模型进行中文合规性分析..."):
            analysis = analyze_compliance_with_qwen_multiple(
                reference_clause, matches, reference_filename, api_key
            )
        
        if analysis:
            st.markdown('<div class="model-response"><strong>Qwen大模型分析结果:</strong><br>' + analysis + '</div>', unsafe_allow_html=True)
        
        st.divider()
    
    # 未匹配的条款分析
    st.subheader("未匹配条款分析")
    
    # 参考文档未匹配条款
    st.markdown(f"#### {reference_filename} 中未匹配的条款 ({len(unmatched_reference)})")
    for i, clause in enumerate(unmatched_reference):
        st.markdown(f'<div class="clause-box"><strong>条款 {i+1}:</strong><br>{clause}</div>', unsafe_allow_html=True)
        with st.spinner(f"正在分析 {reference_filename} 未匹配条款 {i+1}..."):
            analysis = analyze_standalone_clause_with_qwen(clause, reference_filename, api_key)
        if analysis:
            st.markdown('<div class="model-response">' + analysis + '</div>', unsafe_allow_html=True)
        st.divider()
    
    # 其他文档未匹配条款
    for doc_unmatched in unmatched_others:
        doc_name = doc_unmatched["doc_name"]
        clauses = doc_unmatched["clauses"]
        st.markdown(f"#### {doc_name} 中未匹配的条款 ({len(clauses)})")
        for i, clause in enumerate(clauses):
            st.markdown(f'<div class="clause-box"><strong>条款 {i+1}:</strong><br>{clause}</div>', unsafe_allow_html=True)
            with st.spinner(f"正在分析 {doc_name} 未匹配条款 {i+1}..."):
                analysis = analyze_standalone_clause_with_qwen(clause, doc_name, api_key)
            if analysis:
                st.markdown('<div class="model-response">' + analysis + '</div>', unsafe_allow_html=True)
            st.divider()

# 主程序
def main():
    st.title("📄 Qwen 中文PDF条款合规性分析工具")
    st.write("上传一个参考PDF文档和多个待比较的PDF文档，系统将自动分析条款合规性")
    
    # 侧边栏设置
    with st.sidebar:
        st.header("🔧 设置")
        api_key = st.text_input("请输入Qwen API密钥", type="password")
        st.markdown("""
        提示: 分析结果基于Qwen大模型，仅供参考。
        """)
    
    # 文件上传
    col1, col2 = st.columns(2)
    with col1:
        reference_file = st.file_uploader("上传参考PDF文档", type="pdf", key="reference")
    
    with col2:
        other_files = st.file_uploader(
            "上传多个待比较的PDF文档", 
            type="pdf", 
            key="others",
            accept_multiple_files=True
        )
    
    # 当文件上传后进行处理
    if reference_file and other_files:
        # 提取参考文档文本
        reference_text = extract_text_from_pdf(reference_file)
        reference_filename = reference_file.name
        
        # 提取其他文档文本
        other_texts = []
        other_filenames = []
        for file in other_files:
            other_texts.append(extract_text_from_pdf(file))
            other_filenames.append(file.name)
        
        # 显示分析结果
        show_compliance_analysis(
            reference_text, 
            reference_filename, 
            other_texts, 
            other_filenames, 
            api_key
        )

if __name__ == "__main__":
    main()
