import streamlit as st
from PyPDF2 import PdfReader
from difflib import HtmlDiff, SequenceMatcher
import base64
import re
from collections import defaultdict

# 设置页面标题和图标
st.set_page_config(
    page_title="PDF条款合规性分析工具",
    page_icon="📄",
    layout="wide"
)

# 自定义CSS样式
st.markdown("""
<style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stFileUploader { width: 100%; }
    .highlight-add { background-color: #d4edda; }
    .highlight-remove { background-color: #f8d7da; }
    .highlight-conflict { background-color: #ffeeba; padding: 2px 4px; border-radius: 3px; }
    .diff-container { border: 1px solid #ddd; border-radius: 5px; padding: 15px; }
    .clause-box { border-left: 4px solid #007bff; padding: 10px; margin: 10px 0; background-color: #f8f9fa; }
    .compliance-ok { border-left: 4px solid #28a745; }
    .compliance-warning { border-left: 4px solid #ffc107; }
    .compliance-conflict { border-left: 4px solid #dc3545; }
</style>
""", unsafe_allow_html=True)

def extract_text_from_pdf(file):
    """从PDF提取文本"""
    try:
        pdf_reader = PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""  # 处理可能为None的情况
        return text
    except Exception as e:
        st.error(f"提取文本失败: {str(e)}")
        return ""

def split_into_clauses(text):
    """将文本分割为条款，尝试识别标准条款格式"""
    # 尝试识别多种条款格式：1. 2. 3. 或 (1) (2) (3) 或 第一条 第二条 等
    patterns = [
        r'(\d+\.\s+.*?)(?=\d+\.\s+|$)',  # 1. 2. 3. 格式
        r'([一二三四五六七八九十]+、\s+.*?)(?=[一二三四五六七八九十]+、\s+|$)',  # 一、二、三、格式
        r'((?:第)?[一二三四五六七八九十]+条\s+.*?)(?=(?:第)?[一二三四五六七八九十]+条\s+|$)',  # 第一条 第二条 格式
        r'(\([1-9]+\)\s+.*?)(?=\([1-9]+\)\s+|$)'  # (1) (2) (3) 格式
    ]
    
    for pattern in patterns:
        clauses = re.findall(pattern, text, re.DOTALL)
        if len(clauses) > 3:  # 如果找到足够多的条款，使用这种分割方式
            return [clause.strip() for clause in clauses if clause.strip()]
    
    # 如果没有识别到条款格式，按段落分割
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    return paragraphs

def match_clauses(clauses1, clauses2):
    """匹配两个文档中的相似条款"""
    matched_pairs = []
    used_indices = set()
    
    # 为文档1中的每个条款找到文档2中最相似的未匹配条款
    for i, clause1 in enumerate(clauses1):
        best_match = None
        best_ratio = 0.3  # 设置最低匹配阈值
        best_j = -1
        
        for j, clause2 in enumerate(clauses2):
            if j not in used_indices:
                ratio = SequenceMatcher(None, clause1, clause2).ratio()
                if ratio > best_ratio and ratio > best_ratio:
                    best_ratio = ratio
                    best_match = clause2
                    best_j = j
        
        if best_match:
            matched_pairs.append((clause1, best_match, best_ratio))
            used_indices.add(best_j)
    
    # 收集未匹配的条款
    unmatched1 = [clause for i, clause in enumerate(clauses1) 
                 if i not in [p[0] for p in [(idx, pair) for idx, pair in enumerate(matched_pairs)]]]
    unmatched2 = [clause for j, clause in enumerate(clauses2) if j not in used_indices]
    
    return matched_pairs, unmatched1, unmatched2

def analyze_compliance(clause1, clause2):
    """分析两个条款之间的合规性，判断是否存在冲突"""
    # 简单的冲突检测逻辑，可以根据实际需求扩展
    conflict_indicators = [
        (r'不得|禁止|严禁', r'可以|允许|有权'),
        (r'必须|应当', r'无需|不必|不应当'),
        (r'小于|低于|不超过', r'大于|高于|不少于'),
        (r'全部|所有', r'部分|个别'),
        (r'有效|生效', r'无效|失效')
    ]
    
    conflicts = []
    
    for pattern1, pattern2 in conflict_indicators:
        if re.search(pattern1, clause1, re.IGNORECASE) and re.search(pattern2, clause2, re.IGNORECASE):
            conflicts.append(f"检测到潜在冲突: 文档1包含'{pattern1}'相关表述，文档2包含'{pattern2}'相关表述")
        if re.search(pattern2, clause1, re.IGNORECASE) and re.search(pattern1, clause2, re.IGNORECASE):
            conflicts.append(f"检测到潜在冲突: 文档1包含'{pattern2}'相关表述，文档2包含'{pattern1}'相关表述")
    
    # 计算相似度
    similarity = SequenceMatcher(None, clause1, clause2).ratio()
    
    # 根据冲突和相似度判断合规性等级
    if conflicts:
        return "冲突", conflicts, similarity
    elif similarity > 0.8:
        return "一致", [], similarity
    elif similarity > 0.5:
        return "基本一致", [], similarity
    else:
        return "差异较大", [], similarity

def create_download_link(content, filename, text):
    """生成下载链接"""
    b64 = base64.b64encode(content.encode()).decode()
    return f'<a href="data:file/txt;base64,{b64}" download="{filename}">{text}</a>'

def show_compliance_analysis(text1, text2, filename1, filename2):
    """显示合规性分析结果"""
    # 分割条款
    with st.spinner("正在分析条款结构..."):
        clauses1 = split_into_clauses(text1)
        clauses2 = split_into_clauses(text2)
        
        st.success(f"条款分析完成: {filename1} 识别出 {len(clauses1)} 条条款，{filename2} 识别出 {len(clauses2)} 条条款")
    
    # 匹配条款并分析合规性
    with st.spinner("正在匹配条款并进行合规性分析..."):
        matched_pairs, unmatched1, unmatched2 = match_clauses(clauses1, clauses2)
        
        # 分析每个匹配对的合规性
        analyzed_pairs = []
        for clause1, clause2, ratio in matched_pairs:
            compliance, conflicts, similarity = analyze_compliance(clause1, clause2)
            analyzed_pairs.append({
                "clause1": clause1,
                "clause2": clause2,
                "similarity": similarity,
                "compliance": compliance,
                "conflicts": conflicts
            })
        
        # 按合规性排序，冲突的条款优先显示
        analyzed_pairs.sort(key=lambda x: ["冲突", "差异较大", "基本一致", "一致"].index(x["compliance"]))
    
    # 显示总体统计
    st.divider()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("文档1条款数", len(clauses1))
    col2.metric("文档2条款数", len(clauses2))
    col3.metric("匹配条款数", len(matched_pairs))
    conflict_count = sum(1 for p in analyzed_pairs if p["compliance"] == "冲突")
    col4.metric("潜在冲突数", conflict_count)
    
    # 显示条款对比和合规性分析
    st.divider()
    st.subheader("📊 条款合规性详细分析")
    
    # 显示有冲突的条款
    if any(p["compliance"] == "冲突" for p in analyzed_pairs):
        st.warning(f"发现 {conflict_count} 处潜在冲突条款，请重点关注")
        with st.expander("查看冲突条款", expanded=True):
            for i, pair in enumerate([p for p in analyzed_pairs if p["compliance"] == "冲突"]):
                st.markdown(f"### 冲突条款 {i+1}")
                st.markdown(f'<div class="clause-box compliance-conflict"><strong>{filename1} 条款:</strong><br>{pair["clause1"]}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="clause-box compliance-conflict"><strong>{filename2} 条款:</strong><br>{pair["clause2"]}</div>', unsafe_allow_html=True)
                
                st.markdown("**冲突分析:**")
                for conflict in pair["conflicts"]:
                    st.markdown(f'- <span class="highlight-conflict">{conflict}</span>', unsafe_allow_html=True)
                
                st.markdown(f"**相似度:** {pair['similarity']:.2%}")
                st.divider()
    
    # 显示其他合规性类别的条款
    st.subheader("其他条款对比")
    
    # 差异较大的条款
    with st.expander(f"差异较大的条款 ({sum(1 for p in analyzed_pairs if p['compliance'] == '差异较大')})"):
        for i, pair in enumerate([p for p in analyzed_pairs if p["compliance"] == "差异较大"]):
            st.markdown(f"### 差异条款 {i+1}")
            st.markdown(f'<div class="clause-box"><strong>{filename1} 条款:</strong><br>{pair["clause1"]}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="clause-box"><strong>{filename2} 条款:</strong><br>{pair["clause2"]}</div>', unsafe_allow_html=True)
            st.markdown(f"**相似度:** {pair['similarity']:.2%}")
            
            # 显示文本差异
            html_diff = HtmlDiff().make_file(
                pair["clause1"].splitlines(), 
                pair["clause2"].splitlines(),
                fromdesc=filename1,
                todesc=filename2
            )
            st.components.v1.html(html_diff, height=200, scrolling=True)
            st.divider()
    
    # 基本一致的条款
    with st.expander(f"基本一致的条款 ({sum(1 for p in analyzed_pairs if p['compliance'] == '基本一致')})"):
        for i, pair in enumerate([p for p in analyzed_pairs if p["compliance"] == "基本一致"]):
            st.markdown(f"### 条款 {i+1}")
            st.markdown(f'<div class="clause-box compliance-warning"><strong>{filename1} 条款:</strong><br>{pair["clause1"]}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="clause-box compliance-warning"><strong>{filename2} 条款:</strong><br>{pair["clause2"]}</div>', unsafe_allow_html=True)
            st.markdown(f"**相似度:** {pair['similarity']:.2%}")
            st.divider()
    
    # 完全一致的条款
    with st.expander(f"一致的条款 ({sum(1 for p in analyzed_pairs if p['compliance'] == '一致')})"):
        for i, pair in enumerate([p for p in analyzed_pairs if p["compliance"] == "一致"]):
            st.markdown(f"### 条款 {i+1}")
            st.markdown(f'<div class="clause-box compliance-ok"><strong>条款内容:</strong><br>{pair["clause1"]}</div>', unsafe_allow_html=True)
            st.markdown(f"**相似度:** {pair['similarity']:.2%}")
            st.divider()
    
    # 未匹配的条款
    st.subheader("未匹配条款")
    col1, col2 = st.columns(2)
    with col1:
        with st.expander(f"{filename1} 中独有的条款 ({len(unmatched1)})"):
            for i, clause in enumerate(unmatched1):
                st.markdown(f"**条款 {i+1}:**")
                st.text_area("", clause, height=100, label_visibility="collapsed")
                st.divider()
    
    with col2:
        with st.expander(f"{filename2} 中独有的条款 ({len(unmatched2)})"):
            for i, clause in enumerate(unmatched2):
                st.markdown(f"**条款 {i+1}:**")
                st.text_area("", clause, height=100, label_visibility="collapsed")
                st.divider()
    
    # 生成完整的HTML报告
    full_report = generate_full_report(analyzed_pairs, unmatched1, unmatched2, filename1, filename2)
    st.markdown(create_download_link(full_report, "compliance_report.html", "⬇️ 下载完整合规性分析报告(HTML)"), unsafe_allow_html=True)

def generate_full_report(analyzed_pairs, unmatched1, unmatched2, filename1, filename2):
    """生成完整的HTML报告"""
    html = f"""
    <html>
    <head>
        <title>PDF条款合规性分析报告</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; line-height: 1.6; }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            .stats {{ display: flex; justify-content: space-around; margin: 20px 0; padding: 15px; background-color: #f5f5f5; border-radius: 5px; }}
            .stat-box {{ text-align: center; }}
            .clause-box {{ margin: 15px 0; padding: 10px; border-radius: 5px; }}
            .compliance-ok {{ border-left: 4px solid #28a745; background-color: #f8f9fa; }}
            .compliance-warning {{ border-left: 4px solid #ffc107; background-color: #f8f9fa; }}
            .compliance-conflict {{ border-left: 4px solid #dc3545; background-color: #f8f9fa; }}
            .highlight-conflict {{ background-color: #ffeeba; padding: 2px 4px; border-radius: 3px; }}
            .section {{ margin: 30px 0; }}
            .divider {{ border: 0; border-top: 1px solid #ddd; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>PDF条款合规性分析报告</h1>
            <p>对比文档: {filename1} 与 {filename2}</p>
        </div>
        
        <div class="stats">
            <div class="stat-box">
                <h3>{filename1} 条款数</h3>
                <p>{len([p for p in analyzed_pairs] + unmatched1)}</p>
            </div>
            <div class="stat-box">
                <h3>{filename2} 条款数</h3>
                <p>{len([p for p in analyzed_pairs] + unmatched2)}</p>
            </div>
            <div class="stat-box">
                <h3>匹配条款数</h3>
                <p>{len(analyzed_pairs)}</p>
            </div>
            <div class="stat-box">
                <h3>潜在冲突数</h3>
                <p>{sum(1 for p in analyzed_pairs if p["compliance"] == "冲突")}</p>
            </div>
        </div>
        
        <div class="section">
            <h2>冲突条款</h2>
    """
    
    # 添加冲突条款
    for i, pair in enumerate([p for p in analyzed_pairs if p["compliance"] == "冲突"]):
        html += f"""
        <h3>冲突条款 {i+1}</h3>
        <div class="clause-box compliance-conflict">
            <strong>{filename1} 条款:</strong><br>
            {pair["clause1"].replace('\n', '<br>')}
        </div>
        <div class="clause-box compliance-conflict">
            <strong>{filename2} 条款:</strong><br>
            {pair["clause2"].replace('\n', '<br>')}
        </div>
        <div>
            <strong>冲突分析:</strong>
            <ul>
        """
        for conflict in pair["conflicts"]:
            html += f'<li><span class="highlight-conflict">{conflict}</span></li>'
        html += f"""
            </ul>
            <strong>相似度:</strong> {pair['similarity']:.2%}
        </div>
        <hr class="divider">
        """
    
    # 添加其他部分...
    html += """
        </div>
        <div class="section">
            <h2>完整分析请查看工具内详细内容</h2>
        </div>
    </body>
    </html>
    """
    return html

# 应用主界面
st.title("📄 PDF条款合规性分析工具")
st.markdown("上传两个PDF文件，系统将自动解析条款并分析合规性冲突")

with st.form("upload_form"):
    col1, col2 = st.columns(2)
    with col1:
        file1 = st.file_uploader("选择第一个PDF文件（基准文档）", type=["pdf"])
    with col2:
        file2 = st.file_uploader("选择第二个PDF文件（对比文档）", type=["pdf"])
    
    submitted = st.form_submit_button("开始合规性分析")

if submitted and file1 and file2:
    with st.spinner("正在解析PDF内容，请稍候..."):
        text1 = extract_text_from_pdf(file1)
        text2 = extract_text_from_pdf(file2)
        
        if not text1 or not text2:
            st.error("无法提取文本内容，请确认PDF包含可提取的文本")
        else:
            show_compliance_analysis(text1, text2, file1.name, file2.name)
else:
    st.info('请上传两个PDF文件后点击"开始合规性分析"按钮')

# 添加使用说明
with st.expander("使用说明"):
    st.markdown("""
    1. 上传两个需要对比的PDF文件（建议先上传基准文档）
    2. 点击"开始合规性分析"按钮
    3. 系统会自动识别文档中的条款并进行匹配
    4. 查看条款间的合规性分析结果，重点关注标记为"冲突"的条款
    5. 可以下载完整的HTML格式分析报告
    
    **分析逻辑:**
    - 系统会尝试识别文档中的条款结构（如1. 2. 3. 或第一条 第二条等格式）
    - 对条款进行匹配并计算相似度
    - 分析条款间是否存在语义冲突（如"必须"与"不必"、"允许"与"禁止"等）
    - 按合规性程度分类展示：冲突、差异较大、基本一致、一致
    
    **注意:**
    - 仅支持文本型PDF，扫描件需要OCR处理
    - 条款识别精度取决于文档格式的规范性
    - 合规性分析结果仅供参考，重要决策请结合人工审核
    """)

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
    PDF条款合规性分析工具 | 使用Streamlit构建 | 数据不会保留在服务器
</div>
""", unsafe_allow_html=True)
