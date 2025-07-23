import streamlit as st
from PyPDF2 import PdfReader
import re
import jieba
import time
import matplotlib.pyplot as plt
import os
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
import torch
import tempfile

# 设置页面配置 - 优先保证加载速度
st.set_page_config(
    page_title="Qwen PDF合规分析工具",
    page_icon="📄",
    layout="wide"
)

# 确保中文显示正常
plt.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

# 自定义CSS - 简化样式提高渲染速度
st.markdown("""
<style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .clause-box { border-left: 4px solid #ccc; padding: 10px 15px; margin: 10px 0; }
    .clause-box.conflict { border-color: #dc3545; background-color: #fff5f5; }
    .clause-box.consistent { border-color: #28a745; background-color: #f8fff8; }
    .analysis-result { padding: 10px; border-radius: 5px; margin: 10px 0; }
</style>
""", unsafe_allow_html=True)

# 检查并显示依赖状态
def check_dependencies():
    """检查关键依赖是否安装正确"""
    try:
        import rich
        rich_version = rich.__version__
        if not (rich_version >= "10.14.0" and rich_version < "14.0.0"):
            st.warning(f"检测到不兼容的rich版本: {rich_version}，建议安装13.7.0版本")
    except ImportError:
        st.warning("未检测到rich库，请安装13.7.0版本")

# 缓存Qwen模型加载 - 提高重复使用速度
@st.cache_resource
def load_qwen_model(model_name="Qwen/Qwen-7B-Chat"):
    """加载Qwen模型和tokenizer，使用缓存提高效率"""
    try:
        # 检查是否有可用GPU
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # 加载tokenizer
        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            trust_remote_code=True
        )
        
        # 加载模型，使用半精度提高速度和减少内存占用
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            device_map="auto",
            trust_remote_code=True
        ).eval()
        
        # 创建文本生成管道
        generator = pipeline(
            "text-generation",
            model=model,
            tokenizer=tokenizer,
            device=0 if device == "cuda" else -1
        )
        
        return generator, tokenizer, device
    except Exception as e:
        st.error(f"模型加载失败: {str(e)}")
        st.info("请确保已安装正确的依赖，或尝试使用较小的模型版本")
        return None, None, None

# 快速PDF文本提取
def extract_text_from_pdf(file):
    """高效提取PDF文本内容"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(file.getvalue())
            tmp_file_path = tmp_file.name
        
        pdf_reader = PdfReader(tmp_file_path)
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text() or ""
            text += page_text + "\n"
        
        os.unlink(tmp_file_path)  # 清理临时文件
        return text
    except Exception as e:
        st.error(f"PDF提取失败: {str(e)}")
        return ""

# 条款提取优化版
def extract_clauses(text):
    """快速提取条款，减少不必要的正则匹配"""
    if not text:
        return []
    
    # 简化的条款模式匹配，提高速度
    clause_patterns = [
        r'(第[一二三四五六七八九十百千万]+条)',
        r'(第\d+条)',
        r'(\d+\.\s?[^。，,；;]+)',
        r'([一二三四五六七八九十]+、\s?[^。，,；;]+)'
    ]
    
    clauses = []
    current_title = ""
    current_content = ""
    
    # 按行处理，减少内存占用
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
            
        matched = False
        for pattern in clause_patterns:
            match = re.search(pattern, line)
            if match:
                if current_title:  # 保存上一个条款
                    clauses.append({
                        "title": current_title,
                        "content": current_content.strip()
                    })
                
                current_title = match.group(1)
                current_content = line.replace(current_title, "", 1).strip()
                matched = True
                break
        
        if not matched and current_title:
            current_content += "\n" + line
    
    # 添加最后一个条款
    if current_title and current_content:
        clauses.append({
            "title": current_title,
            "content": current_content.strip()
        })
    
    return clauses

# 缓存条款匹配 - 避免重复计算
@st.cache_data
def match_clauses(benchmark_clauses, compare_clauses):
    """快速匹配基准条款和对比条款"""
    benchmark_map = {clause["title"]: clause for clause in benchmark_clauses}
    compare_map = {clause["title"]: clause for clause in compare_clauses}
    
    # 只保留双方都有的条款
    common_titles = set(benchmark_map.keys()) & set(compare_map.keys())
    
    matched = []
    for title in common_titles:
        matched.append({
            "title": title,
            "benchmark": benchmark_map[title]["content"],
            "compare": compare_map[title]["content"]
        })
    
    return matched

# 使用Qwen进行合规性分析
def analyze_compliance_with_qwen(generator, tokenizer, benchmark_text, compare_text, title):
    """利用Qwen模型分析条款合规性"""
    if not generator or not tokenizer:
        return "模型未加载，无法进行分析", False
    
    # 构建简洁的提示词，减少模型计算量
    prompt = f"""
    任务：分析两个条款的合规性，判断是否存在冲突。
    基准条款：{benchmark_text[:500]}
    对比条款：{compare_text[:500]}
    
    请回答：
    1. 两条款的核心内容是否一致？
    2. 如果存在差异，是否构成合规性冲突？
    3. 简要说明理由（不超过200字）
    """
    
    try:
        # 优化生成参数，提高速度
        result = generator(
            prompt,
            max_length=500,
            temperature=0.3,  # 降低随机性，提高稳定性
            top_p=0.8,
            repetition_penalty=1.1,
            do_sample=True,
            num_return_sequences=1
        )
        
        analysis = result[0]['generated_text'].replace(prompt, '').strip()
        
        # 判断是否存在冲突
        has_conflict = any(keyword in analysis for keyword in 
                          ["冲突", "不一致", "不符合", "违背", "矛盾"])
        
        return analysis, has_conflict
    except Exception as e:
        st.warning(f"条款 '{title}' 分析失败: {str(e)}")
        return f"分析出错: {str(e)}", True

# 主应用
def main():
    # 检查依赖
    check_dependencies()
    
    st.title("📄 Qwen PDF合规性分析工具")
    st.markdown("基于Qwen大模型的条款合规性分析，快速稳定")
    
    # 侧边栏 - 模型设置
    with st.sidebar:
        st.subheader("模型设置")
        model_size = st.radio("选择模型大小", ["7B (较快)", "14B (较准)"], index=0)
        model_name = "Qwen/Qwen-7B-Chat" if model_size == "7B (较快)" else "Qwen/Qwen-14B-Chat"
        
        st.subheader("分析设置")
        batch_size = st.slider("批量分析条款数", 1, 5, 2)
        
        st.info("首次使用会下载模型，可能需要几分钟时间")
        
        # 预加载模型
        with st.spinner("加载Qwen模型..."):
            generator, tokenizer, device = load_qwen_model(model_name)
        
        st.success(f"模型加载完成，使用设备: {device}")
    
    # 主内容区
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("基准文件")
        benchmark_file = st.file_uploader("上传基准PDF", type="pdf", key="benchmark")
    
    with col2:
        st.subheader("对比文件")
        compare_file = st.file_uploader("上传对比PDF", type="pdf", key="compare")
    
    # 分析按钮
    if st.button("开始合规性分析", disabled=not (benchmark_file and compare_file and generator)):
        with st.spinner("正在处理文件..."):
            # 提取文本
            benchmark_text = extract_text_from_pdf(benchmark_file)
            compare_text = extract_text_from_pdf(compare_file)
            
            if not benchmark_text or not compare_text:
                st.error("无法提取PDF文本内容")
                return
            
            # 提取条款
            benchmark_clauses = extract_clauses(benchmark_text)
            compare_clauses = extract_clauses(compare_text)
            
            st.info(f"提取完成 - 基准文件: {len(benchmark_clauses)} 条条款，对比文件: {len(compare_clauses)} 条条款")
            
            # 匹配条款
            matched_clauses = match_clauses(benchmark_clauses, compare_clauses)
            
            if not matched_clauses:
                st.warning("未找到匹配的条款，无法进行合规性分析")
                return
            
            st.success(f"找到 {len(matched_clauses)} 条匹配条款，开始分析...")
        
        # 显示分析结果
        st.subheader("分析结果")
        
        # 统计信息
        total = len(matched_clauses)
        conflict_count = 0
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # 批量处理条款，提高效率
        results = []
        for i, clause in enumerate(matched_clauses):
            status_text.text(f"正在分析条款 {i+1}/{total}: {clause['title']}")
            
            # 使用Qwen分析
            analysis, has_conflict = analyze_compliance_with_qwen(
                generator, 
                tokenizer,
                clause["benchmark"], 
                clause["compare"],
                clause["title"]
            )
            
            if has_conflict:
                conflict_count += 1
            
            results.append({
                "title": clause["title"],
                "benchmark": clause["benchmark"],
                "compare": clause["compare"],
                "analysis": analysis,
                "has_conflict": has_conflict
            })
            
            # 更新进度
            progress_bar.progress((i + 1) / total)
        
        progress_bar.empty()
        status_text.empty()
        
        # 显示总体统计
        col1, col2 = st.columns(2)
        col1.metric("总匹配条款数", total)
        col2.metric("存在冲突的条款数", conflict_count)
        
        # 显示详细结果
        st.subheader("条款详细分析")
        
        # 先显示冲突条款
        st.markdown("### ⚠️ 存在冲突的条款")
        conflict_found = False
        for res in results:
            if res["has_conflict"]:
                conflict_found = True
                with st.expander(f"条款: {res['title']}", expanded=True):
                    st.markdown(f"<div class='clause-box'><strong>基准条款:</strong><br>{res['benchmark'][:300]}...</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='clause-box conflict'><strong>对比条款:</strong><br>{res['compare'][:300]}...</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='analysis-result'><strong>合规性分析:</strong><br>{res['analysis']}</div>", unsafe_allow_html=True)
        
        if not conflict_found:
            st.success("未发现存在冲突的条款")
        
        # 再显示合规条款
        st.markdown("### ✅ 合规的条款")
        for res in results:
            if not res["has_conflict"]:
                with st.expander(f"条款: {res['title']}", expanded=False):
                    st.markdown(f"<div class='clause-box'><strong>基准条款:</strong><br>{res['benchmark'][:300]}...</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='clause-box consistent'><strong>对比条款:</strong><br>{res['compare'][:300]}...</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='analysis-result'><strong>合规性分析:</strong><br>{res['analysis']}</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
