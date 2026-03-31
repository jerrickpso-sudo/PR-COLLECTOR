import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import os
import re
import uuid
import time
import json
import threading
import concurrent.futures
from supabase import create_client, Client

# ========================
# 0. 尝试加载 OCR 视觉引擎
# ========================
try:
    import pytesseract
    from PIL import Image, ImageEnhance
    HAS_OCR = True
    if os.name == 'nt':
        possible_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            os.path.expanduser(r'~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe')
        ]
        for p in possible_paths:
            if os.path.exists(p):
                pytesseract.pytesseract.tesseract_cmd = p
                break
except ImportError:
    HAS_OCR = False

# ========================
# 0.5 页面配置与 Apple 极简风 UI
# ========================
st.set_page_config(page_title="PR数据库", layout="wide", page_icon="📄")

apple_css = """
<style>
html, body, [class*="css"] { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important; }
.stApp { background-color: #fbfbfd; }
#MainMenu {visibility: hidden;} footer {visibility: hidden;}
@keyframes fadeInUp { 0% { opacity: 0; transform: translateY(20px); } 100% { opacity: 1; transform: translateY(0); } }
.block-container { animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) ease-out; padding-top: 3rem !important; }
[data-testid="stSidebar"] { background-color: rgba(255, 255, 255, 0.75) !important; backdrop-filter: blur(20px); border-right: 1px solid rgba(0,0,0,0.05); }
.stButton>button { border-radius: 980px !important; background-color: #0071e3 !important; color: white !important; border: none !important; box-shadow: 0 4px 6px rgba(0, 113, 227, 0.2) !important; transition: all 0.3s ease !important; font-weight: 500 !important; padding: 0.3rem 1.2rem !important; }
.stButton>button:hover { background-color: #0077ED !important; transform: scale(1.03); box-shadow: 0 6px 10px rgba(0, 113, 227, 0.3) !important; }
.stDownloadButton>button { border-radius: 980px !important; background-color: #ffffff !important; color: #1d1d1f !important; border: 1px solid #d2d2d7 !important; box-shadow: 0 2px 4px rgba(0,0,0,0.02) !important; transition: all 0.3s ease !important; }
.stDownloadButton>button:hover { background-color: #f5f5f7 !important; transform: scale(1.02); }
[data-testid="metric-container"] { background-color: #ffffff; border-radius: 16px; padding: 16px 20px; box-shadow: 0 4px 16px rgba(0,0,0,0.04); border: 1px solid rgba(0,0,0,0.05); }
.jerrick-watermark { position: fixed; bottom: 12px; right: 18px; font-size: 10px; font-weight: 400; color: rgba(0, 0, 0, 0.12); z-index: 99999; pointer-events: none; letter-spacing: 0.5px; }
</style>
<div class="jerrick-watermark">© Jerrick_pso_China</div>
"""
st.markdown(apple_css, unsafe_allow_html=True)

# ========================
# 0.8 连接 Supabase 云端数据库
# ========================
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase = init_connection()
except Exception as e:
    st.error("⚠️ 无法连接到云端数据库，请检查 Secrets 配置！")
    st.stop()

def load_data_from_cloud():
    response = supabase.table("pr_database").select("*").execute()
    if response.data:
        df = pd.DataFrame(response.data)
        # 将云端英文字段映射回中文 UI 字段
        df = df.rename(columns={
            "id": "ID",
            "pr_number": "PR 编号",
            "station_code": "电站编号",
            "apply_date": "申请日期",
            "description": "描述",
            "total_amount": "总金额 (BRL)"
        })
        return df
    else:
        return pd.DataFrame(columns=["ID", "PR 编号", "电站编号", "申请日期", "描述", "总金额 (BRL)"])

# ========================
# 1. 核心翻译与清洗引擎
# ========================
try:
    from googletrans import Translator
    translator = Translator()
    HAS_GOOGLE_TRANS = True
except:
    HAS_GOOGLE_TRANS = False

AUTO_CACHE_FILE = "auto_translation_cache.json"
cache_lock = threading.Lock()
try:
    if os.path.exists(AUTO_CACHE_FILE):
        with open(AUTO_CACHE_FILE, 'r', encoding='utf-8') as f: AUTO_CACHE = json.load(f)
    else: AUTO_CACHE = {}
except: AUTO_CACHE = {}

# 保持你之前庞大的 PT_DICT 和 EN_DICT (此处为了代码结构清晰，合并省略部分超长字典，请确保包含你之前的所有词汇)
PT_DICT = {"solicitação": "申请", "compras": "采购", "urgente": "紧急", "normal": "正常", "unplanned": "未计划"} 
EN_DICT = {"shipping": "运输/海运", "freight": "运费", "assembly": "总成/组件"}
COMBINED_DICT = {**PT_DICT, **EN_DICT}
SORTED_DICT_KEYS = sorted(COMBINED_DICT.keys(), key=len, reverse=True)

MONEY_PATTERN = re.compile(r'(?:R\$|USD|HKD|RS|US\$|U\$)\s*\d{1,10}(?:[., ]\d{3})*(?:[.,]\s*\d{2})?\b|\b\d{1,10}(?:[., ]\d{3})*[.,]\s*\d{2}\b', re.IGNORECASE)
CHINESE_PATTERN = re.compile(r'[\u4e00-\u9fa5]')

BLACKLIST_PHRASES = [
    "pso director confirm", "application and approval", "tipo de solicitação", 
    "invoice/submiting date", "description/descrição", "total request amount", 
    "authorized pso", "signature/assinatura", "name (capital letter)", 
    "x pso", "cashier", "direct applicant", "remark/"
]

def translate_text(text, use_google=False):
    if not text: return ""
    if re.search(r'[\u4e00-\u9fa5]', text): return text
    if text in AUTO_CACHE: return AUTO_CACHE[text]
    
    if HAS_GOOGLE_TRANS and use_google:
        if re.search(r'[a-zA-Z]', text):
            temp_text = re.sub(r'(?i)\bpso\b', 'ZZPSOZZ', text)
            temp_text = re.sub(r'(?i)\bfts\b', 'ZZFTSZZ', temp_text)
            for _ in range(3): 
                try:
                    result = translator.translate(temp_text, dest='zh-cn')
                    translated_str = result.text
                    translated_str = re.sub(r'(?i)ZZPSOZZ', 'PSO', translated_str)
                    translated_str = re.sub(r'(?i)ZZFTSZZ', 'FTS', translated_str)
                    with cache_lock: AUTO_CACHE[text] = translated_str
                    return translated_str
                except Exception:
                    time.sleep(0.3)
            
    translated_text = text
    for key in SORTED_DICT_KEYS:
        pattern = r'(?i)\b' + re.escape(key) + r'\b'
        translated_text = re.sub(pattern, COMBINED_DICT[key], translated_text)
        
    with cache_lock: AUTO_CACHE[text] = translated_text
    return translated_text

def clean_description(desc):
    if not desc: return ""
    desc = re.sub(r'(?i)\b(?:CNPJ|CNPI|GNPJ|CNP)\b', '', desc)
    desc = re.sub(r'\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b', '', desc)
    desc = re.sub(r'\b\d{14}\b', '', desc)
    desc = re.sub(r'(?i)PSO\s*Ref.*?GC\d{4}-\d{4}-\d{3,4}', '', desc)
    desc = re.sub(r'\s+\d{1,2}\s*$', '', desc) 
    desc = re.sub(r'(?i)\b(?:RS|USD|HKD|US\$)\b', '', desc)
    desc = re.sub(r'(?i)R\$\s*', '', desc) 
    remove_words = ['OBS:', 'OBs:', 'obs:', 'NOTE:', 'Note:', 'note:', 'REMARK:', 'Remark:', 'remark:']
    for word in remove_words:
        desc = re.sub(r'\b' + word + r'\s*', '', desc, flags=re.IGNORECASE)
    desc = re.sub(r'[|\[\]{}_]', ' ', desc) 
    desc = re.sub(r'\s+', ' ', desc).strip()
    desc = re.sub(r'^[;:,\.\-\\/]+|[;:,\.\-\\/]+$', '', desc)
    return desc

def extract_top_remark(text):
    match = re.search(r'Remark/\s*Observações:\s*([\s\S]*?)(?:NÃO|SIM|Invoice|$)', text, re.IGNORECASE)
    if match:
        remark_text = match.group(1).replace('\n', ' ').strip()
        remark_text = re.sub(r'\s+', ' ', remark_text)
        if remark_text and remark_text.lower() not in ['x', 'sim', 'não', 'não x', '']:
            return remark_text
    return ""

def parse_filename(filename, full_text=""):
    meta = {"pr_number": "未知", "station_code": "未知", "raw_desc": "", "is_cancelled": False, "is_revision": False, "revision_info": ""}
    s_match = re.search(r'(GC\d{4})', filename, re.IGNORECASE)
    if s_match: meta["station_code"] = s_match.group(1).upper()
    pr_match = re.search(r'(GC\d{4}-\d{4}-\d{3,4})', filename, re.IGNORECASE)
    if pr_match: 
        meta["pr_number"] = pr_match.group(1).upper()
    elif full_text:
        text_match = re.search(r'(GC\d{4}-\d{4}-\d{3,4})', full_text, re.IGNORECASE)
        if text_match: meta["pr_number"] = text_match.group(1).upper()
    
    if meta["pr_number"] == "未知": meta["pr_number"] = os.path.splitext(filename)[0][:30]
        
    fname_lower = filename.lower()
    if 'cancel' in fname_lower: meta["is_cancelled"] = True
    if 're' in fname_lower and re.search(r're\d*', fname_lower):
        meta["is_revision"] = True
        rev_match = re.search(r'(re\d*)', fname_lower)
        if rev_match: meta["revision_info"] = rev_match.group(1).upper()
            
    chinese_chars = re.findall(r'[\u4e00-\u9fa5]+', filename)
    meta["raw_desc"] = "".join(chinese_chars) if chinese_chars else re.sub(r'\.pdf$', '', filename, flags=re.IGNORECASE)
    return meta

def extract_data_from_raw_text(text, top_remark):
    items = []
    text = re.sub(r'[|\[\]{}_]', ' ', text)
    lines = text.split('\n')
    for line in lines:
        row_text = line.strip()
        if not row_text: continue
        if any(b in row_text.lower() for b in BLACKLIST_PHRASES): continue
            
        money_matches = [m.group() for m in MONEY_PATTERN.finditer(row_text)]
        money_val = 0.0
        if money_matches:
            money_str = money_matches[-1]
            clean_str = re.sub(r'[^\d.,]', '', money_str)
            if ',' in clean_str[-3:] or '.' in clean_str[-3:]:
                last_sep = re.search(r'[.,](\d{2})$', clean_str)
                if last_sep:
                    main_part = clean_str[:-3].replace('.', '').replace(',', '')
                    try: money_val = float(main_part + '.' + last_sep.group(1))
                    except ValueError: pass
            else:
                main_part = clean_str.replace('.', '').replace(',', '')
                try: money_val = float(main_part)
                except ValueError: pass
        
        has_chinese = bool(CHINESE_PATTERN.search(row_text))
        letter_count = len(re.findall(r'[a-zA-Z]', row_text))
        if money_val == 0.0 and not has_chinese and letter_count < 4: continue
            
        desc_text = row_text
        desc_text = MONEY_PATTERN.sub('', desc_text)
        desc_text = re.sub(r'\d{1,2}[-/][A-Za-z]{3}[-/]\d{4}', '', desc_text)
        desc_text = re.sub(r'\b\d{1,2}\s+\d{1,2}\s+\d{2,4}\b', '', desc_text)
        desc_text = re.sub(r'^\s*\d{1,3}\s+', '', desc_text)
        desc_text = clean_description(desc_text)
        if money_val == 0.0 and len(desc_text) < 3 and not has_chinese: continue
            
        items.append({"desc": desc_text, "amount_brl": money_val, "top_remark": top_remark})
    return items

def extract_data_via_row_analysis(doc):
    items = []
    full_text = ""
    for page in doc: full_text += page.get_text() + "\n"
    top_remark = extract_top_remark(full_text)
    
    for page in doc:
        blocks = page.get_text("dict").get("blocks", [])
        all_spans = []
        for block in blocks:
            if "lines" not in block: continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if text: all_spans.append({"text": text, "y": span["bbox"][1], "x": span["bbox"][0]})
                        
        all_spans.sort(key=lambda k: k["y"])
        if not all_spans: continue
            
        rows = []
        current_row = [all_spans[0]]
        current_y = all_spans[0]["y"]
        
        for span in all_spans[1:]:
            if abs(span["y"] - current_y) < 12:
                current_row.append(span)
            else:
                current_row.sort(key=lambda k: k["x"])
                rows.append(current_row)
                current_row = [span]
                current_y = span["y"]
                
        current_row.sort(key=lambda k: k["x"])
        rows.append(current_row)
        
        for row_spans in rows:
            row_text = " ".join([s["text"] for s in row_spans])
            if any(b in row_text.lower() for b in BLACKLIST_PHRASES): continue
            
            money_matches = [m.group() for m in MONEY_PATTERN.finditer(row_text)]
            money_val = 0.0
            if money_matches:
                money_str = money_matches[-1]
                clean_str = re.sub(r'[^\d.,]', '', money_str)
                if ',' in clean_str[-3:] or '.' in clean_str[-3:]:
                    last_sep = re.search(r'[.,](\d{2})$', clean_str)
                    if last_sep:
                        main_part = clean_str[:-3].replace('.', '').replace(',', '')
                        try: money_val = float(main_part + '.' + last_sep.group(1))
                        except ValueError: pass
                else:
                    main_part = clean_str.replace('.', '').replace(',', '')
                    try: money_val = float(main_part)
                    except ValueError: pass
            
            has_chinese = bool(CHINESE_PATTERN.search(row_text))
            letter_count = len(re.findall(r'[a-zA-Z]', row_text))
            if money_val == 0.0 and not has_chinese and letter_count < 4: continue
            
            desc_text = row_text
            desc_text = MONEY_PATTERN.sub('', desc_text)
            desc_text = re.sub(r'\d{1,2}[-/][A-Za-z]{3}[-/]\d{4}', '', desc_text)
            desc_text = re.sub(r'\b\d{1,2}\s+\d{1,2}\s+\d{2,4}\b', '', desc_text)
            desc_text = re.sub(r'^\s*\d{1,3}\s+', '', desc_text)
            desc_text = clean_description(desc_text)
            
            if money_val == 0.0 and len(desc_text) < 3 and not has_chinese: continue
                
            items.append({"desc": desc_text, "amount_brl": money_val, "top_remark": top_remark})
    return items

def process_file_bytes(file_name, file_bytes, use_google=False):
    temp_path = f"temp_{uuid.uuid4().hex}.pdf"
    date_val = "未知"
    meta = None
    raw_items = []
    ocr_error = ""
    
    try:
        with open(temp_path, "wb") as f: f.write(file_bytes)
        doc = fitz.open(temp_path)
        full_text = ""
        for page in doc: full_text += page.get_text() + "\n"
        
        meta = parse_filename(file_name, full_text)
        d_match = re.search(r'\d{1,2}-[A-Za-z]{3}-\d{4}', full_text)
        if d_match: date_val = d_match.group()
        
        raw_items = extract_data_via_row_analysis(doc)
        
        total_money_found = sum(it["amount_brl"] for it in raw_items)
        if total_money_found == 0 and HAS_OCR:
            try:
                ocr_text = ""
                for page in doc:
                    pix = page.get_pixmap(dpi=300) 
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    img = img.convert('L')
                    enhancer = ImageEnhance.Contrast(img)
                    img = enhancer.enhance(2.0)
                    
                    try:
                        text = pytesseract.image_to_string(img, lang='por+eng+chi_sim', config='--psm 11')
                    except:
                        try:
                            text = pytesseract.image_to_string(img, lang='por+eng', config='--psm 11')
                        except:
                            text = pytesseract.image_to_string(img, config='--psm 11')
                    
                    ocr_text += text + "\n"
                
                if date_val == "未知":
                    d_match = re.search(r'\d{1,2}-[A-Za-z]{3}-\d{4}', ocr_text, re.IGNORECASE)
                    if d_match: date_val = d_match.group()
                
                top_remark = extract_top_remark(ocr_text)
                ocr_items = extract_data_from_raw_text(ocr_text, top_remark)
                if sum(it["amount_brl"] for it in ocr_items) > 0:
                    raw_items = ocr_items
            except Exception as e:
                ocr_error = str(e)
                
        doc.close()
    except Exception as e:
        print(f"Error parsing {file_name}: {e}")
        return []
    finally:
        if os.path.exists(temp_path): os.remove(temp_path)
        
    if not meta: meta = parse_filename(file_name)
        
    processed_items = []
    for item in raw_items:
        original = item["desc"]
        if not original and item["amount_brl"] == 0: continue
        translated = original if re.search(r'[\u4e00-\u9fa5]', original) else translate_text(original, use_google)
        if not translated: translated = original
        processed_items.append({"original": original, "translated_desc": translated, "amount_brl": item["amount_brl"], "top_remark": item["top_remark"]})
        
    priced_items = [it for it in processed_items if it["amount_brl"] > 0]
    unpriced_items = [it for it in processed_items if it["amount_brl"] == 0]
    final_items = []
    
    if priced_items and unpriced_items:
        for unpriced in unpriced_items:
            u_text = unpriced["translated_desc"]
            has_chinese = bool(CHINESE_PATTERN.search(u_text))
            best_match, max_overlap = None, -1
            u_chars = set(re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]', u_text))
            empty_priced = [p for p in priced_items if not p["translated_desc"].strip()]
            
            if empty_priced: best_match = empty_priced[0]
            elif len(priced_items) == 1: best_match = priced_items[0]
            else:
                for priced in priced_items:
                    p_chars = set(re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]', priced["translated_desc"]))
                    overlap = len(u_chars.intersection(p_chars))
                    if overlap > max_overlap:
                        max_overlap, best_match = overlap, priced
                if best_match is None: best_match = priced_items[0]
            
            if best_match and (not best_match["translated_desc"].strip() or has_chinese or len(u_text) < 60):
                if u_text not in best_match["translated_desc"]:
                    if best_match["translated_desc"].strip(): best_match["translated_desc"] += f" | {u_text}"
                    else: best_match["translated_desc"] = u_text
            else:
                final_items.append(unpriced)
        final_items.extend(priced_items)
    else:
        final_items = processed_items
        
    rows = []
    for item in final_items:
        final_desc = item["translated_desc"].strip()
        final_desc = re.sub(r'^\|\s*', '', final_desc)
        if item.get("top_remark"):
            remark_translated = item["top_remark"]
            if not re.search(r'[\u4e00-\u9fa5]', remark_translated): remark_translated = translate_text(remark_translated, use_google)
            final_desc = f"[备注：{remark_translated}] {final_desc}"
        prefix = "[已取消] " if meta['is_cancelled'] else f"[{meta['revision_info']}] " if meta['is_revision'] else ""
        
        # 返回准备存入数据库的格式
        rows.append({
            "ID": str(uuid.uuid4()),
            "PR 编号": meta['pr_number'],
            "电站编号": meta['station_code'],
            "申请日期": date_val,
            "描述": prefix + final_desc,
            "总金额 (BRL)": item["amount_brl"]
        })
        
    if not rows and meta['pr_number'] != "未知":
        prefix = "[已取消] " if meta['is_cancelled'] else f"[{meta['revision_info']}] " if meta['is_revision'] else ""
        fallback_desc = meta['raw_desc'] if meta['raw_desc'] and meta['raw_desc'] != meta['pr_number'] else "无法提取文字"
        if not HAS_OCR: fallback_desc = f"{fallback_desc} (⚠️ 未安装OCR引擎)"
        elif ocr_error: fallback_desc = f"{fallback_desc} (⚠️ OCR引擎报错)"
        else: fallback_desc = f"{fallback_desc} (⚠️ 图片排版异常请手动补充)"
        rows.append({"ID": str(uuid.uuid4()), "PR 编号": meta['pr_number'], "电站编号": meta['station_code'], "申请日期": date_val, "描述": prefix + fallback_desc, "总金额 (BRL)": 0.0})
            
    return rows

# ========================
# 2. 侧边栏交互与视图渲染
# ========================

STATION_OPTIONS = {"全部电站": "", "GC0042-NOD": "GC0042", "GC0035-HMT": "GC0035", "GC0044-SGC": "GC0044", "GC0043-BBA": "GC0043", "GC0045-AUT": "GC0045"}

with st.sidebar:
    st.markdown("<h3 style='font-weight: 600;'>📁 控制面板</h3>", unsafe_allow_html=True)
    st.markdown("<span style='color: #86868b; font-size: 0.9rem;'>智能数据解析与合并归档引擎。</span>", unsafe_allow_html=True)
    
    st.divider()
    st.markdown("#### ☁️ 云端数据库状态")
    st.success("🟢 已成功连接至 Supabase 节点")
        
    st.divider()
    
    st.markdown("#### 1️⃣ 数据录入")
    use_api = st.checkbox("🌐 启用外部辅助翻译", value=False)
    uploaded_files = st.file_uploader("拖拽上传 PDF 文件", type=["pdf"], accept_multiple_files=True)
    
    st.divider()
    
    st.markdown("#### 2️⃣ 视图筛选")
    selected_station = st.selectbox("过滤电站", options=list(STATION_OPTIONS.keys()), index=0)
    search_query = st.text_input("精确搜索", placeholder="输入描述、编号...")

st.title("PR数据库 (云端版)")

if STATION_OPTIONS.get(selected_station):
    st.markdown(f"<div style='background-color: #e8f2fc; color: #0071e3; padding: 10px 16px; border-radius: 8px; font-weight: 500; font-size: 0.95rem; margin-bottom: 20px;'>🔍 当前筛选：{selected_station} {f' | 关键词：{search_query}' if search_query else ''}</div>", unsafe_allow_html=True)

# 🚀 核心变更：每次刷新从 Supabase 拉取最新数据
df = load_data_from_cloud()

if 'processed_files' not in st.session_state:
    st.session_state.processed_files = set()

if uploaded_files:
    existing_prs_in_db = set(df['PR 编号'].dropna().astype(str))
    files_to_process = []
    skipped_count = 0
    
    for f in uploaded_files:
        if f.name in st.session_state.processed_files: continue
        meta = parse_filename(f.name)
        if meta['pr_number'] in existing_prs_in_db and meta['pr_number'] != "未知":
            skipped_count += 1
            st.session_state.processed_files.add(f.name)
        else:
            files_to_process.append(f)
            
    if skipped_count > 0:
        st.info(f"🛡️ 自动跳过了 {skipped_count} 份已存在于云端的 PR 记录。")

    if files_to_process:
        st.warning("⚠️ **系统正在处理并上传云端，请勿关闭页面！**")
        bar = st.progress(0)
        all_new = []
        successful_filenames = []
        
        file_tasks = [(f.name, f.getvalue()) for f in files_to_process]
        completed = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            future_to_file = {
                executor.submit(process_file_bytes, name, bytes_data, use_api): name 
                for name, bytes_data in file_tasks
            }
            
            for future in concurrent.futures.as_completed(future_to_file):
                f_name = future_to_file[future]
                try:
                    rows = future.result()
                    successful_filenames.append(f_name)
                    all_new.extend(rows)
                except Exception as exc:
                    print(f"File {f_name} generated an exception: {exc}")
                
                completed += 1
                bar.progress(completed / len(file_tasks))
        
        # 写入本地 AI 记忆字典
        try:
            with open(AUTO_CACHE_FILE, 'w', encoding='utf-8') as f: json.dump(AUTO_CACHE, f, ensure_ascii=False, indent=2)
        except: pass
            
        # 🚀 核心变更：批量插入数据到 Supabase
        if all_new:
            records_to_insert = []
            for row in all_new:
                records_to_insert.append({
                    "id": row["ID"],
                    "pr_number": row["PR 编号"],
                    "station_code": row["电站编号"],
                    "apply_date": row["申请日期"],
                    "description": row["描述"],
                    "total_amount": row["总金额 (BRL)"]
                })
            
            try:
                # 往云端发送数据
                supabase.table("pr_database").insert(records_to_insert).execute()
                st.session_state.processed_files.update(successful_filenames)
                st.success(f"✅ 极速处理完成！成功向云端数据库写入 {len(all_new)} 条记录。")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"❌ 写入云端数据库失败: {str(e)}")
        else:
            st.session_state.processed_files.update(successful_filenames)
            st.info("⚠️ 无新数据需要写入云端。")
        bar.empty()

f_df = df.copy()
if STATION_OPTIONS.get(selected_station): f_df = f_df[f_df["电站编号"] == STATION_OPTIONS[selected_station]]
if search_query:
    mask = f_df.astype(str).apply(lambda x: x.str.contains(search_query, case=False)).any(axis=1)
    f_df = f_df[mask]

st.markdown("<h4 style='font-weight: 600; margin-top: 1rem; margin-bottom: 1rem;'>📊 业务数据看板</h4>", unsafe_allow_html=True)
if not f_df.empty:
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        st.metric("总记录数", f"{len(f_df)} 条")
    with col2:
        st.metric("总采购金额 (BRL)", f"R$ {f_df['总金额 (BRL)'].sum():,.2f}")
    with col3:
        if not STATION_OPTIONS.get(selected_station):
            station_sum = f_df.groupby("电站编号")["总金额 (BRL)"].sum().reset_index()
            st.bar_chart(station_sum, x="电站编号", y="总金额 (BRL)", height=150)
        else:
            st.info("💡 切换回【全部电站】以查看跨电站开销分布图。")

st.markdown("<h4 style='font-weight: 600; margin-top: 2rem; margin-bottom: 1rem;'>📝 数据明细 (双击任意单元格进行修改，自动同步云端)</h4>", unsafe_allow_html=True)

if not f_df.empty:
    edited_df = st.data_editor(
        f_df, 
        use_container_width=True, 
        num_rows="dynamic",
        hide_index=True,
        column_order=["PR 编号", "电站编号", "申请日期", "描述", "总金额 (BRL)"],
        column_config={
            "总金额 (BRL)": st.column_config.NumberColumn("总金额 (BRL)", format="R$ %.2f")
        }
    )
    
    col_btn1, col_btn2 = st.columns([1, 5])
    with col_btn1:
        if st.button("💾 保存数据更改 (云端同步)"):
            original_ids_in_view = set(f_df["ID"])
            edited_ids = set(edited_df["ID"].dropna())
            deleted_ids = original_ids_in_view - edited_ids
            
            try:
                # 🚀 核心变更：处理云端数据的 删除 与 插入/更新
                
                # 1. 远端删除被用户删除的行
                if deleted_ids:
                    supabase.table("pr_database").delete().in_("id", list(deleted_ids)).execute()
                
                # 2. 远端更新或插入发生更改的行
                records_to_upsert = []
                for idx, row in edited_df.iterrows():
                    current_id = row.get("ID")
                    if pd.isna(current_id):
                        current_id = str(uuid.uuid4())
                        
                    records_to_upsert.append({
                        "id": current_id,
                        "pr_number": row["PR 编号"],
                        "station_code": row["电站编号"],
                        "apply_date": row["申请日期"],
                        "description": row["描述"],
                        "total_amount": row["总金额 (BRL)"]
                    })
                    
                if records_to_upsert:
                    supabase.table("pr_database").upsert(records_to_upsert).execute()
                
                st.success("✅ 数据更改已安全同步至 Supabase 云端服务器！")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"❌ 同步失败: {str(e)}")
else: 
    st.info("当前视图暂无数据")

if not df.empty:
    export_df = df.drop(columns=["ID"], errors='ignore')
    csv = export_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
    st.download_button("下载完整 CSV", csv, "pr_details_cloud.csv", "text/csv")
