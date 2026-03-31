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

# ========================
# 0. 尝试加载 OCR 视觉引擎 (带路径自动寻址)
# ========================
try:
    import pytesseract
    from PIL import Image
    HAS_OCR = True
    # 针对 Windows 用户，自动寻找 Tesseract 常见安装路径
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

PT_DICT = {
    "solicitação": "申请", "compras": "采购", "urgente": "紧急", "normal": "正常", "unplanned": "未计划", "projeto": "项目", "localização": "位置", "potência": "功率", "funcionário": "员工", "cargo": "职位", "observações": "备注", "estoque": "库存", "sim": "是", "não": "否", "descrição": "描述", "quantidade": "数量", "valor": "金额", "data": "日期", "referência": "参考", "código": "代码", "unidade": "单位", "material": "材料", "equipamento": "设备", "serviço": "服务", "mão de obra": "人工", "instalação": "安装", "manutenção": "维护", "reparo": "维修", "substituição": "更换", "fornecimento": "供应", "entrega": "交付", "prazo": "期限", "garantia": "保修", "especificação": "规格", "modelo": "型号", "marca": "品牌", "fabricante": "制造商", "origem": "原产地", "destino": "目的地", "transporte": "运输", "frete": "运费", "seguro": "保险", "imposto": "税", "taxa": "费率", "desconto": "折扣", "total": "总计",
    "ferramenta": "工具", "parafuso": "螺栓", "porca": "螺母", "arruela": "垫圈", "prego": "钉子", "broca": "钻头", "serra": "锯", "disco": "圆盘", "lixa": "砂纸", "solda": "焊接", "eletrodo": "焊条", "maçarico": "焊炬", "cilindro": "气瓶", "gás": "气体", "oxigênio": "氧气", "acetileno": "乙炔", "nitrogênio": "氮气", "óleo": "油", "lubrificante": "润滑油", "graxa": "润滑脂", "desengripante": "除锈剂", "tinta": "油漆", "solvente": "溶剂", "pincel": "刷子", "rolo": "滚筒", "fita": "胶带", "adesivo": "粘合剂", "cola": "胶水", "silicone": "硅胶", "vedação": "密封件", "junta": "垫片", "o-ring": "O型圈", "retentor": "油封", "rolamento": "轴承", "mancal": "轴承座", "eixo": "轴", "engrenagem": "齿轮", "correia": "皮带", "polia": "皮带轮", "corrente": "链条", "pinhão": "链轮", "acoplamento": "联轴器", "mangueira": "软管", "tubo": "管道", "conexão": "接头", "válvula": "阀门", "registro": "闸阀", "bomba": "泵", "compressor": "压缩机", "ventilador": "风扇", "exaustor": "排风机", "motor": "电机", "redutor": "减速机", "gerador": "发电机", "alternador": "交流发电机", "bateria": "电池", "carregador": "充电器", "inversor": "逆变器", "conversor": "转换器", "transformador": "变压器", "disjuntor": "断路器", "contator": "接触器", "relé": "继电器", "fusível": "熔断器", "borne": "接线端子", "terminal": "端子", "cabo": "电缆", "fio": "电线", "isolador": "绝缘子", "eletroduto": "线管", "calha": "线槽", "painel": "控制面板", "quadro": "配电盘", "lâmpada": "灯泡", "reator": "镇流器", "luminária": "灯具", "refletor": "探照灯", "tomada": "插座", "plugue": "插头", "interruptor": "开关", "sensor": "传感器", "transmissor": "变送器", "medidor": "仪表", "manômetro": "压力表", "termômetro": "温度计", "fluxômetro": "流量计", "nível": "液位计", "pressostato": "压力开关", "termostato": "恒温器", "controlador": "控制器", "clp": "PLC", "ihm": "触摸屏",
    "maca": "担架", "extintor": "灭火器", "hidrante": "消防栓", "alarme": "警报", "detector": "探测器", "placa": "标牌", "sinalização": "标志", "epi": "劳保用品", "capacete": "安全帽", "óculos": "护目镜", "máscara": "口罩", "luva": "手套", "botina": "工作靴", "bota": "靴子", "uniforme": "制服",
    "diária": "日结费用", "hospedagem": "住宿", "passagem": "机票/车票", "aéreo": "航空", "terrestre": "陆路", "carreto": "短途运输", "locação": "租赁", "aluguel": "租金", "consultoria": "咨询", "passagem aérea": "机票", "ida e volta": "往返", "bilhete": "票", "combustível": "燃油", "lockers": "储物柜", "soft bare": "软裸", "cat6": "六类网线", "replacing": "更换", "civil": "土建", "labor": "劳务", "work": "工作", "professional": "专业", "tool box": "工具箱", "steel": "钢制", "wardrobe": "衣柜", "doors": "门", "lock": "锁", "hasp": "搭扣", "partition": "隔层", "police": "警察", "wood": "木片", "sheet": "片", "installation kit": "安装套件", "work service": "工作服务", "mounting": "安装", "accessories": "配件", "chimney": "烟囱", "top plate": "顶板", "replacement": "更换", "cost": "费用", "round-trip": "往返", "airfare": "机票", "ticket": "票", "from": "从", "to": "到", "date": "日期", "mr": "先生", "accompany": "陪同", "personnel": "人员", "往返": "往返", "机票": "机票", "陪同": "陪同", "人员": "人员",
    "garrafão de água": "桶装水", "água mineral": "矿泉水", "comestíveis": "食品", "copa": "茶水间", "açúcar": "糖", "café": "咖啡", "biscoito": "饼干", "leite em pó": "奶粉", "copo descartável": "一次性杯子", "gasolina": "汽油", "lavagem de carro": "洗车", "pneu furado": "补胎", "aluguel de carro": "租车费", "aluguel de apartamento": "租房费", "serviço de limpeza": "清洁服务", "taxa de internet": "网费", "recarga de celular": "话费充值", "papel a4": "A4打印纸", "caneta": "钢笔/圆珠笔", "envelope": "信封", "grampeador": "订书机", "tesoura": "剪刀", "fita adesiva": "胶带", "bateria": "电池", "pilha": "干电池", "cadeira": "椅子", "mesa": "桌子", "avental": "围裙", "manga": "袖套", "tinta esmalte": "瓷漆", "tinta acrílica": "丙烯酸涂料", "rolo de pintura": "油漆滚筒", "bandeja de pintura": "油漆托盘", "pedra brita": "碎石", "balsa": "渡轮/油船", "passagem de barco": "船票", "táxi": "出租车"
}

EN_DICT = {
    "shipping": "运输/海运", "freight": "运费", "assembly": "总成/组件", "compound": "复合物", "compiund": "复合物", "wooden box": "木箱", "wooden": "木制", "box": "箱", "sealing set": "密封套件", "sealing": "密封", "seal": "密封件", "injection": "喷射/喷油", "gudgeon pin": "活塞销", "bush": "衬套", "bushing": "衬套", "liner": "缸套", "ring": "活塞环", "rings": "活塞环", "penetrating oil": "渗透油", "penetrating": "渗透", "balance": "平衡", "drill": "钻头", "lubrification": "润滑", "lubrication": "润滑", "supplies": "耗材/用品", "water pump": "水泵", "diesel": "柴油", "water drum": "桶装水", "groceries": "食品/杂货", "sugar": "糖", "coffee": "咖啡", "powder milk": "奶粉", "biscuit": "饼干", "biscuits": "饼干", "disposable cup": "一次性杯子", "car wash": "洗车", "flat tire": "补胎", "apartment rental": "租房费", "cleaning service": "清洁服务", "internet fees": "网费", "phone recharge": "话费充值", "accommodation": "住宿", "skilled labor": "专业劳务", "dismantling": "拆卸", "testing": "测试", "emerald grass": "绿化草坪", "measuring tape": "测量尺", "rental period": "租期", "leather apron": "皮围裙", "leather glove": "皮手套", "sleeve": "袖套", "crushed stone": "碎石", "floodlight": "泛光灯", "utility knife": "美工刀", "electrical cable": "电缆", "male plug": "公插头", "female plug": "母插头", "pallet": "托盘", "plywood": "胶合板", "fire extinguisher": "灭火器", "refill": "充装", "hydrostatic test": "水压测试", "host": "主机", "wireless camera": "无线摄像头",
    "cable": "电缆", "cables": "电缆", "wire": "电线", "wires": "电线", "unipolar": "单极", "bipolar": "双极", "multipolar": "多极", "copper": "铜", "aluminum": "铝", "shielded": "屏蔽", "control": "控制", "instrumentation": "仪表", "power": "电力", "low voltage": "低压", "medium voltage": "中压", "high voltage": "高压", "flex": "柔性", "armored": "铠装", "mm2": "平方毫米", "awg": "美标线规", "kit": "套件", "labor": "人工", "service": "服务", "installation": "安装", "repair": "维修", "replacement": "更换", "camera": "摄像头", "cameras": "摄像头", "cctv": "监控", "system": "系统", "new": "新", "unit": "机组", "generator": "发电机", "turbine": "涡轮", "substation": "变电站", "project": "项目", "purchase": "采购", "material": "材料", "equipment": "设备", "spare parts": "备件", "tools": "工具", "safety": "安全", "protection": "保护", "grounding": "接地", "lightning": "防雷", "surge": "浪涌", "arrester": "避雷器", "transformer": "变压器", "switchgear": "开关柜", "panel": "配电盘", "breaker": "断路器", "fuse": "熔断器", "relay": "继电器", "sensor": "传感器", "meter": "电表", "battery": "电池", "charger": "充电器", "inverter": "逆变器", "rectifier": "整流器", "converter": "转换器", "motor": "电机", "pump": "泵", "valve": "阀门", "pipe": "管道", "fitting": "管件", "flange": "法兰", "gasket": "垫片", "bolt": "螺栓", "nut": "螺母", "washer": "垫圈", "screw": "螺丝", "rivet": "铆钉", "weld": "焊接", "glue": "胶水", "tape": "胶带", "paint": "油漆", "coating": "涂层", "insulation": "绝缘", "sealant": "密封剂", "lubricant": "润滑剂", "cleaner": "清洁剂", "solvent": "溶剂", "chemical": "化学品", "consumable": "耗材", "office": "办公", "supply": "用品", "furniture": "家具", "computer": "电脑", "printer": "打印机", "software": "软件", "license": "许可证", "maintenance": "维护", "inspection": "检查", "testing": "测试", "commissioning": "调试", "training": "培训", "consulting": "咨询", "engineering": "工程", "design": "设计", "construction": "施工", "civil works": "土建", "electrical works": "电气工程", "mechanical works": "机械工程", "instrumentation works": "仪表工程", "automation": "自动化", "scada": "数据采集与监控系统", "plc": "可编程逻辑控制器", "hmi": "人机界面", "rtu": "远程终端单元", "gps": "全球定位系统", "gis": "地理信息系统", "bms": "电池管理系统", "ems": "能量管理系统", "dcs": "分布式控制系统", "sis": "安全仪表系统", "fire alarm": "火灾报警", "gas detection": "气体检测", "access control": "门禁控制", "video surveillance": "视频监控", "public address": "广播系统", "intercom": "对讲系统", "telephone": "电话", "network": "网络", "fiber optic": "光纤", "ethernet": "以太网", "wifi": "无线网络", "bluetooth": "蓝牙", "bobbin": "卷筒", "coil": "线圈", "spool": "线轴", "reel": "卷轴", "drum": "鼓轮", "carton": "纸箱", "crate": "板条箱", "pallet": "托盘", "bag": "袋", "transport": "运输", "aerea": "航空", "hospedagem": "住宿", "alimentacao": "餐饮", "combustivel": "燃油", "pecas": "配件", "manutencao": "维护", "servico": "服务", "equipamento": "设备", "escritorio": "办公室", "limpeza": "清洁", "seguranca": "安全", "ferramentas": "工具", "estoque": "库存", "compra": "采购", "reparo": "维修", "instalacao": "安装", "lockers": "储物柜", "armario": "柜子", "soft bare": "软裸", "cat6": "六类网线", "replacing": "更换", "concrete": "混凝土", "foundation": "基础", "professional": "专业", "tool box": "工具箱", "steel": "钢制", "wardrobe": "衣柜", "doors": "门", "lock": "锁", "hasp": "搭扣", "partition": "隔层", "police": "警察", "wood": "木片", "sheet": "片", "installation kit": "安装套件", "work service": "工作服务", "mounting": "安装", "accessories": "配件", "chimney": "烟囱", "top plate": "顶板", "cost": "费用", "round-trip": "往返", "airfare": "机票", "ticket": "票", "from": "从", "to": "到", "date": "日期", "mr": "先生", "accompany": "陪同", "personnel": "人员",
    "tool": "工具", "nail": "钉子", "drill bit": "钻头", "saw": "锯", "blade": "刀片", "disc": "圆盘", "sandpaper": "砂纸", "electrode": "焊条", "torch": "焊炬", "cylinder": "气瓶", "gas": "气体", "oxygen": "氧气", "acetylene": "乙炔", "nitrogen": "氮气", "oil": "油", "grease": "润滑脂", "rust penetrant": "除锈剂", "brush": "刷子", "roller": "滚筒", "adhesive": "粘合剂", "o-ring": "O型圈", "bearing": "轴承", "housing": "外壳", "shaft": "轴", "gear": "齿轮", "belt": "皮带", "pulley": "皮带轮", "chain": "链条", "sprocket": "链轮", "coupling": "联轴器", "hose": "软管", "gate": "闸门", "exhaust": "排风", "reducer": "减速机", "contactor": "接触器", "board": "板", "lamp": "灯", "ballast": "镇流器", "fixture": "夹具", "spotlight": "探照灯", "socket": "插座", "plug": "插头", "switch": "开关", "transmitter": "变送器", "gauge": "量规", "thermometer": "温度计", "flowmeter": "流量计", "level": "液位", "pressure switch": "压力开关", "thermostat": "恒温器", "controller": "控制器", "cartridge": "墨盒", "toner": "碳粉", "paper": "纸张", "pen": "钢笔", "pencil": "铅笔", "folder": "文件夹", "envelope": "信封", "stapler": "订书机", "hole punch": "打孔机", "desk": "书桌", "chair": "椅子", "cabinet": "机柜", "drawer": "抽屉", "shelf": "架子", "rack": "机架", "stretcher": "担架", "extinguisher": "灭火器", "fire hose": "消防软管", "hydrant": "消防栓", "alarm": "警报器", "detector": "探测器", "sign": "标志", "signage": "标牌", "ppe": "个人防护装备", "helmet": "头盔", "glasses": "眼镜", "earplug": "耳塞", "mask": "面罩", "glove": "手套", "safety harness": "安全带", "boot": "靴子", "shoe": "鞋", "uniform": "制服", "shirt": "衬衫", "pants": "裤子", "jacket": "夹克", "raincoat": "雨衣", "soap": "肥皂", "detergent": "洗涤剂", "disinfectant": "消毒剂", "broom": "扫帚", "squeegee": "吸水扒", "cloth": "布", "bin": "垃圾桶", "trash bag": "垃圾袋", "cup": "杯子", "plate": "盘子", "cutlery": "餐具", "coffee": "咖啡", "sugar": "糖", "water": "水", "soda": "苏打水", "juice": "果汁", "cookie": "饼干", "meal": "膳食", "per diem": "每日津贴", "accommodation": "住宿", "air": "空气", "land": "陆地", "haulage": "拖运", "lease": "租赁", "advisory": "咨询", "report": "报告", "fee": "费用", "tax": "税", "insurance": "保险"
}

COMBINED_DICT = {**PT_DICT, **EN_DICT}
SORTED_DICT_KEYS = sorted(COMBINED_DICT.keys(), key=len, reverse=True)

# 增强正则：允许逗号/点号后带有空格（修复OCR断层），捕获独立金额
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
            # 防御机制：把专有名词套上保护壳，防止谷歌乱翻
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
    
    desc = re.sub(r'[|\[\]{}_]', ' ', desc) # 清理OCR杂乱符号
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
        if text_match:
            meta["pr_number"] = text_match.group(1).upper()
    
    if meta["pr_number"] == "未知":
        meta["pr_number"] = os.path.splitext(filename)[0][:30]
        
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
        row_lower = row_text.lower()
        
        if any(b in row_lower for b in BLACKLIST_PHRASES):
            continue
            
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
        
        if money_val == 0.0 and not has_chinese and letter_count < 4:
            continue
            
        desc_text = row_text
        desc_text = MONEY_PATTERN.sub('', desc_text)
        desc_text = re.sub(r'\d{1,2}[-/][A-Za-z]{3}[-/]\d{4}', '', desc_text)
        desc_text = re.sub(r'\b\d{1,2}\s+\d{1,2}\s+\d{2,4}\b', '', desc_text)
        desc_text = re.sub(r'^\s*\d{1,3}\s+', '', desc_text)
        desc_text = clean_description(desc_text)
        
        # 保留“裸金额”
        if money_val == 0.0 and len(desc_text) < 3 and not has_chinese: 
            continue
            
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
            row_lower = row_text.lower()
            
            if any(b in row_lower for b in BLACKLIST_PHRASES):
                continue
            
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
            
            if money_val == 0.0 and not has_chinese and letter_count < 4:
                continue
            
            desc_text = row_text
            desc_text = MONEY_PATTERN.sub('', desc_text)
            desc_text = re.sub(r'\d{1,2}[-/][A-Za-z]{3}[-/]\d{4}', '', desc_text)
            desc_text = re.sub(r'\b\d{1,2}\s+\d{1,2}\s+\d{2,4}\b', '', desc_text)
            desc_text = re.sub(r'^\s*\d{1,3}\s+', '', desc_text)
            desc_text = clean_description(desc_text)
            
            if money_val == 0.0 and len(desc_text) < 3 and not has_chinese: 
                continue
                
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
        
        # ==========================================
        # 🔥 散点雷达版 OCR (解决图文混排拦截)
        # ==========================================
        total_money_found = sum(it["amount_brl"] for it in raw_items)
        if total_money_found == 0 and HAS_OCR:
            try:
                ocr_text = ""
                for page in doc:
                    pix = page.get_pixmap(dpi=300) 
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    img = img.convert('L')
                    
                    # 优先尝试多语言（带中文），使用 psm 11 散点雷达模式
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
                print(f"OCR Failed for {file_name}: {e}")
                
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
            if empty_priced:
                best_match = empty_priced[0]
            elif len(priced_items) == 1:
                best_match = priced_items[0]
            else:
                for priced in priced_items:
                    p_chars = set(re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]', priced["translated_desc"]))
                    overlap = len(u_chars.intersection(p_chars))
                    if overlap > max_overlap:
                        max_overlap, best_match = overlap, priced
                if best_match is None: best_match = priced_items[0]
            
            if best_match and (not best_match["translated_desc"].strip() or has_chinese or len(u_text) < 60):
                if u_text not in best_match["translated_desc"]:
                    if best_match["translated_desc"].strip():
                        best_match["translated_desc"] += f" | {u_text}"
                    else:
                        best_match["translated_desc"] = u_text
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
        
        if not HAS_OCR:
            fallback_desc = f"{fallback_desc} (⚠️ 未安装OCR引擎，无法读取纯图片PDF)"
        elif ocr_error:
            fallback_desc = f"{fallback_desc} (⚠️ OCR引擎报错: {ocr_error[:30]}...)"
        else:
            fallback_desc = f"{fallback_desc} (⚠️ 图片排版异常，未能自动提价，请手动补充)"
            
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
    st.markdown("#### ⚙️ 引擎状态")
    if HAS_OCR:
        st.success("👁️ OCR 视觉引擎：散点雷达版已启动")
    else:
        st.warning("🙈 OCR 视觉引擎：未安装 (无法读取扫描件)")
        st.caption("请确认已安装 Tesseract-OCR 并 `pip install pytesseract Pillow`")
        
    st.divider()
    
    st.markdown("#### 1️⃣ 数据录入")
    use_api = st.checkbox("🌐 启用外部辅助翻译", value=False)
    uploaded_files = st.file_uploader("拖拽上传 PDF 文件", type=["pdf"], accept_multiple_files=True)
    
    st.divider()
    
    st.markdown("#### 2️⃣ 视图筛选")
    selected_station = st.selectbox("过滤电站", options=list(STATION_OPTIONS.keys()), index=0)
    search_query = st.text_input("精确搜索", placeholder="输入描述、编号...")

st.title("PR数据库")

if STATION_OPTIONS.get(selected_station):
    st.markdown(f"<div style='background-color: #e8f2fc; color: #0071e3; padding: 10px 16px; border-radius: 8px; font-weight: 500; font-size: 0.95rem; margin-bottom: 20px;'>🔍 当前筛选：{selected_station} {f' | 关键词：{search_query}' if search_query else ''}</div>", unsafe_allow_html=True)

DB_FILE = "pr_database_pro.csv"
cols = ["ID", "PR 编号", "电站编号", "申请日期", "描述", "总金额 (BRL)"]

if not os.path.exists(DB_FILE): 
    pd.DataFrame(columns=cols).to_csv(DB_FILE, index=False, encoding='utf-8-sig')

try: 
    df = pd.read_csv(DB_FILE, encoding='utf-8-sig')
    if "ID" not in df.columns:
        df.insert(0, "ID", [str(uuid.uuid4()) for _ in range(len(df))])
        df.to_csv(DB_FILE, index=False, encoding='utf-8-sig')
except: 
    df = pd.DataFrame(columns=cols)

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
        st.info(f"🛡️ 自动跳过了 {skipped_count} 份已存在于数据库中的 PR 记录。")

    if files_to_process:
        st.warning("⚠️ **系统正在处理中，请勿在此期间操作左侧边栏，否则会导致进程中断！**")
        bar = st.progress(0)
        st.toast("🚀 正在启用带视觉识别引擎的多线程极速解析...")
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
        
        try:
            with open(AUTO_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(AUTO_CACHE, f, ensure_ascii=False, indent=2)
        except Exception as e:
            pass
            
        if all_new:
            df_new = pd.DataFrame(all_new)
            df = pd.concat([df, df_new], ignore_index=True) if not df.empty else df_new
            df.to_csv(DB_FILE, index=False, encoding='utf-8-sig')
            
            st.session_state.processed_files.update(successful_filenames)
            st.success(f"✅ 极速处理完成！成功解析录入 {len(all_new)} 条全新记录。")
            time.sleep(1)
            st.rerun()
        else:
            st.session_state.processed_files.update(successful_filenames)
            st.info("⚠️ 无新数据写入。")
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

st.markdown("<h4 style='font-weight: 600; margin-top: 2rem; margin-bottom: 1rem;'>📝 数据明细 (双击任意单元格进行修改)</h4>", unsafe_allow_html=True)

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
        if st.button("💾 保存数据更改"):
            original_ids_in_view = set(f_df["ID"])
            edited_ids = set(edited_df["ID"].dropna())
            deleted_ids = original_ids_in_view - edited_ids
            df = df[~df["ID"].isin(deleted_ids)]
            df = df[~df["ID"].isin(edited_ids)]
            for idx, row in edited_df.iterrows():
                if pd.isna(row.get("ID")):
                    edited_df.at[idx, "ID"] = str(uuid.uuid4())
            df = pd.concat([df, edited_df], ignore_index=True)
            df.to_csv(DB_FILE, index=False, encoding='utf-8-sig')
            
            st.success("✅ 更改已安全同步至底层数据库！")
            st.rerun()
else: 
    st.info("当前视图暂无数据")

if not df.empty:
    export_df = df.drop(columns=["ID"], errors='ignore')
    csv = export_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
    st.download_button("下载完整 CSV", csv, "pr_details_pro.csv", "text/csv")