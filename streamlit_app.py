import streamlit as st
import PyPDF2
import os
import tempfile
import re
import string
from collections import Counter
import matplotlib.pyplot as plt
import numpy as np
from wordcloud import WordCloud
import nltk
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer

# 确保下载NLTK所需资源
nltk.download('stopwords', quiet=True)
nltk.download('wordnet', quiet=True)

# 设置页面配置
st.set_page_config(
    page_title="PDF解析与对比分析工具",
    page_icon="📄",
    layout="wide"
)

# 初始化NLP工具
stop_words = set(stopwords.words('english'))
lemmatizer = WordNetLemmatizer()

# 标题
st.title("📄 PDF解析与对比分析工具")

# 侧边栏导航
st.sidebar.title("功能导航")
option = st.sidebar.selectbox(
    "选择功能",
    ("PDF解析", "多文件对比分析")
)

# 文本预处理函数
def preprocess_text(text):
    """对文本进行预处理：小写化、去除标点、停用词和词形还原"""
    # 转换为小写
    text = text.lower()
    
    # 去除标点
    text = text.translate(str.maketrans('', '', string.punctuation))
    
    # 去除数字
    text = re.sub(r'\d+', '', text)
    
    # 分词
    words = text.split()
    
    # 去除停用词和词形还原
    words = [lemmatizer.lemmatize(word) for word in words if word not in stop_words and len(word) > 2]
    
    return words

# 提取PDF文本
def extract_text_from_pdf(pdf_file):
    """从PDF文件中提取文本内容"""
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text
    return text

# 分析文本函数
def analyze_text(text):
    """分析文本内容，返回统计信息"""
    # 预处理文本
    words = preprocess_text(text)
    
    # 计算基本统计信息
    total_words = len(words)
    unique_words = len(set(words))
    word_freq = Counter(words)
    top_words = word_freq.most_common(10)
    
    return {
        "total_words": total_words,
        "unique_words": unique_words,
        "top_words": top_words,
        "word_freq": word_freq,
        "words": words
    }

# 生成词云
def generate_wordcloud(word_freq):
    """根据词频生成词云"""
    wordcloud = WordCloud(width=800, height=400, background_color='white').generate_from_frequencies(word_freq)
    
    plt.figure(figsize=(10, 5))
    plt.imshow(wordcloud, interpolation='bilinear')
    plt.axis('off')
    return plt

# 比较多个文档
def compare_documents(doc_analyses):
    """比较多个文档的分析结果"""
    # 提取所有文档的词频
    all_words = set()
    for doc in doc_analyses.values():
        all_words.update(doc["word_freq"].keys())
    
    # 计算每个词在各文档中的频率
    word_comparison = {}
    for word in all_words:
        word_comparison[word] = {name: doc["word_freq"].get(word, 0) for name, doc in doc_analyses.items()}
    
    # 找出共同出现的词
    common_words = [word for word, counts in word_comparison.items() if all(c > 0 for c in counts.values())]
    common_words_sorted = sorted(common_words, key=lambda w: sum(word_comparison[w].values()), reverse=True)[:10]
    
    # 找出各文档特有的词
    unique_words = {}
    for name, doc in doc_analyses.items():
        other_docs = [d for n, d in doc_analyses.items() if n != name]
        other_words = set()
        for d in other_docs:
            other_words.update(d["word_freq"].keys())
        unique = [word for word in doc["word_freq"] if word not in other_words]
        # 按频率排序
        unique_sorted = sorted(unique, key=lambda w: doc["word_freq"][w], reverse=True)[:10]
        unique_words[name] = unique_sorted
    
    return {
        "common_words": common_words_sorted,
        "unique_words": unique_words,
        "word_comparison": word_comparison
    }

# PDF解析功能
if option == "PDF解析":
    st.header("PDF解析")
    st.write("上传PDF文件，系统将解析并分析其内容")
    
    pdf_file = st.file_uploader("选择PDF文件", type="pdf")
    
    if pdf_file is not None:
        # 显示文件名
        st.write(f"已上传文件: {pdf_file.name}")
        
        # 提取文本
        with st.spinner("正在解析PDF文件..."):
            text = extract_text_from_pdf(pdf_file)
        
        # 显示提取的文本（前500字符）
        st.subheader("文本预览")
        if len(text) > 0:
            st.text_area("PDF内容预览", text[:500] + ("..." if len(text) > 500 else ""), height=200)
            
            # 分析文本
            with st.spinner("正在分析文本内容..."):
                analysis = analyze_text(text)
            
            # 显示分析结果
            st.subheader("文本分析结果")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.metric("总词数", analysis["total_words"])
                st.metric("独特词数", analysis["unique_words"])
            
            with col2:
                st.write("高频词Top 10:")
                top_words_df = {
                    "词语": [word for word, _ in analysis["top_words"]],
                    "出现次数": [count for _, count in analysis["top_words"]]
                }
                st.dataframe(top_words_df)
            
            # 生成词云
            st.subheader("词云")
            wordcloud_fig = generate_wordcloud(analysis["word_freq"])
            st.pyplot(wordcloud_fig)
        else:
            st.warning("无法从PDF中提取文本内容，可能是图片型PDF或加密PDF。")

# 多文件对比分析功能
elif option == "多文件对比分析":
    st.header("多文件对比分析")
    st.write("上传多个PDF文件，系统将对比分析它们的内容差异与共性")
    
    pdf_files = st.file_uploader("选择多个PDF文件", type="pdf", accept_multiple_files=True)
    
    if len(pdf_files) >= 2:
        st.write(f"已上传 {len(pdf_files)} 个文件")
        
        # 解析所有文件
        doc_analyses = {}
        with st.spinner("正在解析所有PDF文件..."):
            for file in pdf_files:
                text = extract_text_from_pdf(file)
                if text:
                    analysis = analyze_text(text)
                    doc_analyses[file.name] = analysis
                else:
                    st.warning(f"无法解析文件: {file.name}，已跳过该文件")
        
        # 确保至少有两个可分析的文件
        if len(doc_analyses) >= 2:
            # 比较文档
            with st.spinner("正在对比分析文档..."):
                comparison = compare_documents(doc_analyses)
            
            # 显示比较结果
            st.subheader("文档比较结果")
            
            # 显示共同词
            st.write("### 共同高频词 (Top 10)")
            if comparison["common_words"]:
                common_words_data = {
                    "词语": comparison["common_words"],
                    **{name: [doc["word_freq"][word] for word in comparison["common_words"]] 
                       for name, doc in doc_analyses.items()}
                }
                st.dataframe(common_words_data)
                
                # 绘制共同词对比图
                fig, ax = plt.subplots(figsize=(10, 6))
                x = np.arange(len(comparison["common_words"]))
                width = 0.8 / len(doc_analyses)
                
                for i, (name, doc) in enumerate(doc_analyses.items()):
                    counts = [doc["word_freq"][word] for word in comparison["common_words"]]
                    ax.bar(x + i*width - 0.4 + width/2, counts, width, label=name)
                
                ax.set_xticks(x)
                ax.set_xticklabels(comparison["common_words"], rotation=45)
                ax.legend()
                ax.set_title("共同高频词在各文档中的出现次数")
                st.pyplot(fig)
            else:
                st.info("未发现所有文档共同出现的词语")
            
            # 显示各文档的独特词
            st.write("### 各文档的独特高频词 (Top 10)")
            for name, unique_words in comparison["unique_words"].items():
                with st.expander(f"{name} 的独特词"):
                    if unique_words:
                        unique_words_data = {
                            "词语": unique_words,
                            "出现次数": [doc_analyses[name]["word_freq"][word] for word in unique_words]
                        }
                        st.dataframe(unique_words_data)
                    else:
                        st.info(f"{name} 没有独特的词语")
            
            # 显示各文档的基本统计对比
            st.write("### 文档基本统计对比")
            stats_data = {
                "文档名称": list(doc_analyses.keys()),
                "总词数": [doc["total_words"] for doc in doc_analyses.values()],
                "独特词数": [doc["unique_words"] for doc in doc_analyses.values()]
            }
            st.dataframe(stats_data)
            
            # 绘制统计对比图
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
            
            # 总词数对比
            ax1.bar(stats_data["文档名称"], stats_data["总词数"], color='skyblue')
            ax1.set_title("总词数对比")
            ax1.tick_params(axis='x', rotation=45)
            
            # 独特词数对比
            ax2.bar(stats_data["文档名称"], stats_data["独特词数"], color='lightgreen')
            ax2.set_title("独特词数对比")
            ax2.tick_params(axis='x', rotation=45)
            
            plt.tight_layout()
            st.pyplot(fig)
            
            # 显示各文档的词云
            st.write("### 各文档词云对比")
            cols = st.columns(len(doc_analyses))
            for col, (name, doc) in zip(cols, doc_analyses.items()):
                with col:
                    st.write(f"**{name}**")
                    wordcloud_fig = generate_wordcloud(doc["word_freq"])
                    st.pyplot(wordcloud_fig)
        else:
            st.error("可分析的文件不足2个，请上传更多可解析的PDF文件")
    elif 0 < len(pdf_files) < 2:
        st.warning("请至少上传2个PDF文件进行对比分析")
