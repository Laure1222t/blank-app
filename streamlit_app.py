import streamlit as st
import PyPDF2
import re
import string
from collections import defaultdict
import jieba
import jieba.analyse
import matplotlib.pyplot as plt
import numpy as np
from wordcloud import WordCloud
import spacy
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# 设置页面配置
st.set_page_config(
    page_title="中文PDF条款解析与合规性分析工具",
    page_icon="📄",
    layout="wide"
)

# 设置中文字体
plt.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

# 加载中文停用词
def load_chinese_stopwords():
    """加载中文停用词"""
    stopwords_list = [
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也", 
        "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这", "与", "及", "等",
        "可以", "我们", "对于", "进行", "可能", "表示", "认为", "提出", "问题", "方法", "研究", "通过",
        "第", "条", "款", "项", "规定", "内容", "如下", "所示", "包括", "其中", "并且", "同时", "此外"
    ]
    return set(stopwords_list)

stop_words = load_chinese_stopwords()

# 提取PDF文本
def extract_text_from_pdf(pdf_file):
    """从PDF文件中提取文本内容"""
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page_num, page in enumerate(pdf_reader.pages, 1):
            page_text = page.extract_text()
            if page_text:
                text += f"\n--- 第 {page_num} 页 ---\n"
                text += page_text
        return text
    except Exception as e:
        st.error(f"提取PDF文本时出错: {str(e)}")
        return ""

# 文本预处理
def preprocess_text(text):
    """预处理中文文本"""
    # 去除特殊字符和多余空格
    text = re.sub(r'\s+', ' ', text).strip()
    # 去除标点
    text = text.translate(str.maketrans('', '', string.punctuation))
    # 分词
    words = jieba.cut(text)
    # 过滤停用词和短词
    filtered_words = [word for word in words if word not in stop_words and len(word) > 1]
    return " ".join(filtered_words)

# 条款提取
def extract_clauses(text):
    """从文本中提取条款"""
    # 匹配条款的正则表达式模式 (如"第一条"、"1."、"1.1"等)
    clause_patterns = [
        r'(第[一二三四五六七八九十百千万]+条)',  # 中文数字条款，如"第一条"
        r'(\d+\.)',  # 数字加点，如"1."
        r'(\d+\.\d+)',  # 数字加.加数字，如"1.1"
        r'(第\d+条)'  # 数字条款，如"第1条"
    ]
    
    clauses = []
    current_clause = {"title": "", "content": ""}
    current_title = ""
    
    # 按行处理文本
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 检查是否为条款标题
        matched = False
        for pattern in clause_patterns:
            matches = re.findall(pattern, line)
            if matches:
                # 如果有当前条款，先保存
                if current_clause["title"]:
                    clauses.append(current_clause)
                
                # 新条款
                current_title = matches[0]
                current_clause = {
                    "title": current_title,
                    "content": line.replace(current_title, "").strip()
                }
                matched = True
                break
        
        # 如果不是条款标题，添加到当前条款内容
        if not matched and current_title:
            current_clause["content"] += " " + line
    
    # 添加最后一个条款
    if current_clause["title"]:
        clauses.append(current_clause)
    
    return clauses

# 提取关键词
def extract_keywords(text, top_n=5):
    """提取文本关键词"""
    return jieba.analyse.extract_tags(text, topK=top_n, withWeight=False)

# 合规性分析
def analyze_compliance(clauses_a, clauses_b):
    """分析两个文件条款之间的合规性"""
    # 创建条款标题到内容的映射
    clauses_a_dict = {clause["title"]: clause for clause in clauses_a}
    clauses_b_dict = {clause["title"]: clause for clause in clauses_b}
    
    # 所有条款标题
    all_titles = set(clauses_a_dict.keys()).union(set(clauses_b_dict.keys()))
    
    # 结果分类
    results = {
        "consistent": [],  # 一致的条款
        "conflicting": [],  # 冲突的条款
        "only_a": [],       # 仅在A中存在的条款
        "only_b": [],       # 仅在B中存在的条款
        "similar": []       # 相似但标题不同的条款
    }
    
    # 分析相同标题的条款
    for title in all_titles:
        in_a = title in clauses_a_dict
        in_b = title in clauses_b_dict
        
        if in_a and in_b:
            # 两个文件都有此条款，比较内容
            content_a = clauses_a_dict[title]["content"]
            content_b = clauses_b_dict[title]["content"]
            
            # 预处理文本
            processed_a = preprocess_text(content_a)
            processed_b = preprocess_text(content_b)
            
            # 计算相似度
            if not processed_a or not processed_b:
                similarity = 0.0
            else:
                vectorizer = TfidfVectorizer()
                tfidf_matrix = vectorizer.fit_transform([processed_a, processed_b])
                similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            
            # 提取关键词
            keywords_a = extract_keywords(content_a)
            keywords_b = extract_keywords(content_b)
            
            # 判断是否冲突（基于相似度阈值）
            if similarity > 0.7:
                results["consistent"].append({
                    "title": title,
                    "content_a": content_a,
                    "content_b": content_b,
                    "similarity": similarity,
                    "keywords_a": keywords_a,
                    "keywords_b": keywords_b
                })
            else:
                results["conflicting"].append({
                    "title": title,
                    "content_a": content_a,
                    "content_b": content_b,
                    "similarity": similarity,
                    "keywords_a": keywords_a,
                    "keywords_b": keywords_b
                })
        
        elif in_a:
            # 仅在A中存在
            results["only_a"].append(clauses_a_dict[title])
        
        elif in_b:
            # 仅在B中存在
            results["only_b"].append(clauses_b_dict[title])
    
    # 查找相似但标题不同的条款
    a_titles = [t for t in clauses_a_dict.keys() if t not in clauses_b_dict.keys()]
    b_titles = [t for t in clauses_b_dict.keys() if t not in clauses_a_dict.keys()]
    
    for a_title in a_titles:
        content_a = clauses_a_dict[a_title]["content"]
        processed_a = preprocess_text(content_a)
        
        for b_title in b_titles:
            content_b = clauses_b_dict[b_title]["content"]
            processed_b = preprocess_text(content_b)
            
            if processed_a and processed_b:
                vectorizer = TfidfVectorizer()
                tfidf_matrix = vectorizer.fit_transform([processed_a, processed_b])
                similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
                
                if similarity > 0.6:  # 相似但标题不同的阈值
                    results["similar"].append({
                        "title_a": a_title,
                        "title_b": b_title,
                        "content_a": content_a,
                        "content_b": content_b,
                        "similarity": similarity
                    })
    
    return results

# 生成词云
def generate_wordcloud(text, title):
    """生成中文词云"""
    processed_text = preprocess_text(text)
    if not processed_text:
        return None
        
    wordcloud = WordCloud(
        width=800, 
        height=400, 
        background_color='white',
        font_path="simhei.ttf"
    ).generate(processed_text)
    
    plt.figure(figsize=(10, 5))
    plt.imshow(wordcloud, interpolation='bilinear')
    plt.title(title)
    plt.axis('off')
    return plt

# 主应用
def main():
    st.title("📄 中文PDF条款解析与合规性分析工具")
    st.write("上传两个PDF文件，系统将解析条款并进行合规性分析，重点识别条款冲突")
    
    # 上传文件
    col1, col2 = st.columns(2)
    with col1:
        pdf_file1 = st.file_uploader("上传第一个PDF文件", type="pdf", key="file1")
    with col2:
        pdf_file2 = st.file_uploader("上传第二个PDF文件", type="pdf", key="file2")
    
    if pdf_file1 and pdf_file2:
        # 提取文本
        with st.spinner("正在解析PDF文件..."):
            text1 = extract_text_from_pdf(pdf_file1)
            text2 = extract_text_from_pdf(pdf_file2)
        
        # 提取条款
        with st.spinner("正在提取条款..."):
            clauses1 = extract_clauses(text1)
            clauses2 = extract_clauses(text2)
        
        # 显示条款提取结果
        st.subheader("条款提取结果")
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"从 {pdf_file1.name} 中提取到 {len(clauses1)} 条条款")
            with st.expander(f"查看 {pdf_file1.name} 的所有条款"):
                for i, clause in enumerate(clauses1, 1):
                    st.write(f"**{clause['title']}**")
                    st.write(clause['content'])
                    st.write("---")
        
        with col2:
            st.info(f"从 {pdf_file2.name} 中提取到 {len(clauses2)} 条条款")
            with st.expander(f"查看 {pdf_file2.name} 的所有条款"):
                for i, clause in enumerate(clauses2, 1):
                    st.write(f"**{clause['title']}**")
                    st.write(clause['content'])
                    st.write("---")
        
        # 合规性分析
        with st.spinner("正在进行合规性分析..."):
            compliance_results = analyze_compliance(clauses1, clauses2)
        
        # 显示合规性分析结果
        st.subheader("📊 合规性分析结果")
        
        # 冲突条款
        st.write("### ⚠️ 存在冲突的条款")
        if compliance_results["conflicting"]:
            for item in compliance_results["conflicting"]:
                with st.expander(f"条款 {item['title']} (相似度: {item['similarity']:.2f})"):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.write(f"**{pdf_file1.name} 内容:**")
                        st.write(item["content_a"])
                        st.write(f"**关键词:** {', '.join(item['keywords_a'])}")
                    with col_b:
                        st.write(f"**{pdf_file2.name} 内容:**")
                        st.write(item["content_b"])
                        st.write(f"**关键词:** {', '.join(item['keywords_b'])}")
                    st.markdown("**分析:** 两条款内容存在显著差异，可能存在合规性冲突，建议重点审查。")
        else:
            st.success("未发现存在冲突的条款")
        
        # 一致的条款
        st.write("### ✅ 内容一致的条款")
        if compliance_results["consistent"]:
            for item in compliance_results["consistent"]:
                with st.expander(f"条款 {item['title']} (相似度: {item['similarity']:.2f})"):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.write(f"**{pdf_file1.name} 内容:**")
                        st.write(item["content_a"])
                    with col_b:
                        st.write(f"**{pdf_file2.name} 内容:**")
                        st.write(item["content_b"])
        else:
            st.info("未发现内容一致的条款")
        
        # 相似但标题不同的条款
        st.write("### 🔄 相似但标题不同的条款")
        if compliance_results["similar"]:
            for item in compliance_results["similar"]:
                with st.expander(f"条款 {item['title_a']} 与 {item['title_b']} (相似度: {item['similarity']:.2f})"):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.write(f"**{pdf_file1.name} {item['title_a']}:**")
                        st.write(item["content_a"])
                    with col_b:
                        st.write(f"**{pdf_file2.name} {item['title_b']}:**")
                        st.write(item["content_b"])
                    st.markdown("**分析:** 两条款内容相似但标题不同，可能是同一内容的不同表述，建议确认是否为同一条款。")
        else:
            st.info("未发现相似但标题不同的条款")
        
        # 仅在一个文件中存在的条款
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"### 📌 仅在 {pdf_file1.name} 中存在的条款")
            if compliance_results["only_a"]:
                for clause in compliance_results["only_a"]:
                    with st.expander(clause["title"]):
                        st.write(clause["content"])
            else:
                st.info(f"{pdf_file1.name} 中的所有条款在 {pdf_file2.name} 中都有对应条款")
        
        with col2:
            st.write(f"### 📌 仅在 {pdf_file2.name} 中存在的条款")
            if compliance_results["only_b"]:
                for clause in compliance_results["only_b"]:
                    with st.expander(clause["title"]):
                        st.write(clause["content"])
            else:
                st.info(f"{pdf_file2.name} 中的所有条款在 {pdf_file1.name} 中都有对应条款")
        
        # 条款覆盖度分析
        st.subheader("📈 条款覆盖度分析")
        total_clauses = len(compliance_results["consistent"]) + len(compliance_results["conflicting"]) + len(compliance_results["only_a"]) + len(compliance_results["only_b"])
        coverage = (len(compliance_results["consistent"]) + len(compliance_results["conflicting"])) / total_clauses * 100 if total_clauses > 0 else 0
        
        fig, ax = plt.subplots(figsize=(10, 6))
        labels = ['一致条款', '冲突条款', f'仅{pdf_file1.name}', f'仅{pdf_file2.name}']
        sizes = [
            len(compliance_results["consistent"]),
            len(compliance_results["conflicting"]),
            len(compliance_results["only_a"]),
            len(compliance_results["only_b"])
        ]
        colors = ['#4CAF50', '#F44336', '#2196F3', '#FFC107']
        explode = (0.1, 0.1, 0, 0)
        
        ax.pie(sizes, explode=explode, labels=labels, colors=colors, autopct='%1.1f%%',
                shadow=True, startangle=90)
        ax.axis('equal')
        plt.title(f'条款分布 (条款覆盖率: {coverage:.1f}%)')
        st.pyplot(fig)
        
        # 词云对比
        st.subheader("🔍 条款内容词云对比")
        col1, col2 = st.columns(2)
        with col1:
            all_text1 = " ".join([clause["content"] for clause in clauses1])
            wc1 = generate_wordcloud(all_text1, f"{pdf_file1.name} 条款词云")
            if wc1:
                st.pyplot(wc1)
        
        with col2:
            all_text2 = " ".join([clause["content"] for clause in clauses2])
            wc2 = generate_wordcloud(all_text2, f"{pdf_file2.name} 条款词云")
            if wc2:
                st.pyplot(wc2)
        
        # 合规性总结
        st.subheader("📝 合规性分析总结")
        st.info(f"""
        分析总结:
        1. 两个文件共比对出 {len(compliance_results["consistent"]) + len(compliance_results["conflicting"])} 条相同标题的条款
        2. 其中 {len(compliance_results["consistent"])} 条内容一致，{len(compliance_results["conflicting"])} 条存在冲突
        3. {pdf_file1.name} 有 {len(compliance_results["only_a"])} 条独有条款，{pdf_file2.name} 有 {len(compliance_results["only_b"])} 条独有条款
        4. 发现 {len(compliance_results["similar"])} 对标题不同但内容相似的条款
        
        合规性风险提示:
        - 存在 {len(compliance_results["conflicting"])} 条冲突条款，可能存在合规性问题，建议重点审查
        - 两个文件的条款覆盖率为 {coverage:.1f}%，{'' if coverage > 70 else '覆盖率较低，'} 建议确认是否涵盖所有必要内容
        """)

if __name__ == "__main__":
    main()
    
