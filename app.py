# ====================================================================
# WesmartAI 證據報告 Web App (final10.0-secure)
# 作者: Gemini
# 核心更新 (流程重構):
# 1. /generate 僅用於生成預覽圖，不再進行存證。
# 2. 新增 /seal 路由，使用者點擊下載時才觸發此路由進行雜湊與封存。
# 3. 此修改將存證的決定權交給使用者，流程更清晰、嚴謹。
# ====================================================================

import requests, json, hashlib, uuid, datetime, random, time, os, io, base64
from flask import Flask, render_template, request, jsonify, send_from_directory, url_for
from PIL import Image
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import qrcode

# --- 讀取環境變數 ---
API_KEY = os.getenv("TOGETHER_API_KEY")

# --- Flask App 初始化 ---
app = Flask(__name__)
static_folder = 'static'
if not os.path.exists(static_folder):
    os.makedirs(static_folder)
app.config['UPLOAD_FOLDER'] = static_folder

# --- Helper Functions and PDF Class (內容與前版相同，此處省略以節省篇幅) ---
def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()
# ... (WesmartPDFReport Class 的所有程式碼都和前一版相同) ...
class WesmartPDFReport(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not os.path.exists("NotoSansTC.otf"):
            print("正在下載中文字型...")
            try:
                font_url = "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Regular.otf"
                r = requests.get(font_url)
                r.raise_for_status()
                with open("NotoSansTC.otf", "wb") as f:
                    f.write(r.content)
                print("字型下載完成。")
            except Exception as e:
                print(f"字型下載失敗: {e}")
        self.add_font("NotoSansTC", "", "NotoSansTC.otf")
        self.set_auto_page_break(auto=True, margin=25)
        self.alias_nb_pages()
        self.logo_path = "LOGO.jpg" if os.path.exists("LOGO.jpg") else None

    def header(self):
        if self.logo_path:
            with self.local_context(fill_opacity=0.08, stroke_opacity=0.08):
                img_w = 120
                center_x = (self.w - img_w) / 2
                center_y = (self.h - img_w) / 2
                self.image(self.logo_path, x=center_x, y=center_y, w=img_w)
        if self.page_no() > 1:
            self.set_font("NotoSansTC", "", 9)
            self.set_text_color(128)
            self.cell(0, 10, "WesmartAI 生成式 AI 證據報告", new_x=XPos.LMARGIN, new_y=YPos.TOP, align='L')
            self.cell(0, 10, "WesmartAI Inc.", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')

    def footer(self):
        self.set_y(-15)
        self.set_font("NotoSansTC", "", 8)
        self.set_text_color(128)
        self.cell(0, 10, f'第 {self.page_no()}/{{nb}} 頁', align='C')

    def chapter_title(self, title):
        self.set_font("NotoSansTC", "", 16)
        self.set_text_color(0)
        self.cell(0, 12, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
        self.ln(6)

    def chapter_body(self, content):
        self.set_font("NotoSansTC", "", 10)
        self.set_text_color(50)
        self.multi_cell(0, 7, content, align='L')
        self.ln()

    def create_cover(self, meta):
        self.add_page()
        if self.logo_path:
            self.image(self.logo_path, x=(self.w-60)/2, y=25, w=60)
        self.set_y(100)
        self.set_font("NotoSansTC", "", 28)
        self.cell(0, 20, "WesmartAI 證據報告", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(20)
        self.set_font("NotoSansTC", "", 12)
        data = [
            ("出證申請人:", meta['applicant']), ("申請事項:", "WesmartAI 生成式 AI 證據報告"),
            ("申請出證時間:", meta['report_time']), ("出證編號:", meta['report_id']),
            ("出證單位:", "WesmartAI Inc.")
        ]
        for row in data:
            self.cell(20)
            self.cell(45, 10, row[0], align='L')
            self.multi_cell(0, 10, row[1], new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')

    def create_disclaimer_page(self):
        self.add_page()
        self.chapter_title("声 明")
        self.chapter_body(
            "本公司 WesmartAI Inc. (以下簡稱「本公司」) 受客戶委託，就本次生成式人工智慧 (Generative AI) 服務過程中的數位資料進行存證，並出具此報告。\n\n"
            "1. 本報告中所記錄的資料，均來自於使用者與本公司系統互動時所產生的真實數位紀錄。\n"
            "2. 本公司採用區塊鏈技術理念，對生成過程中的關鍵數據（包括但不限於：使用者輸入、模型參數、生成結果的雜湊值、時間戳記）進行了不可變的紀錄與固化。\n"
            "3. 本報告僅對存證的數據來源、紀錄過程及數據完整性負責。本報告不對生成內容的合法性、合規性、版權歸屬及商業用途提供任何形式的保證或背書。\n"
            "4. 任何協力廠商基於本報告所做的任何決策或行動，其後果由該協力廠商自行承擔，與本公司無關。\n"
            "5. 本報告的數位版本與紙質版本具有同等效力。報告的真實性可通過掃描報告中的 QR code 進行線上驗證。\n\n"
            "特此聲明。"
        )

    def create_overview_page(self):
        self.add_page()
        self.chapter_title("技術概述")
        self.chapter_body(
            "WesmartAI 的圖像生成存證服務，旨在為每一次 AI 生成操作提供透明、可追溯且難以篡改的技術證據。本服務的核心是「生成即存證」，確保從使用者提交指令到最終圖像產生的每一個環節都被記錄在案。\n\n"
            "我們的技術流程如下：\n"
            "1. **任務接收**: 使用者提交生成指令 (Prompt) 及相關參數。系統為此次會話分配一個唯一的追蹤權杖 (Trace Token)。\n"
            "2. **生成與存檔**: 系統生成圖像後，立即將其儲存為原始檔案。此檔案為證據的本體。\n"
            "3. **數據固化 (Base64)**: 系統重新讀取已儲存的原始檔案，將其內容轉為 Base64 字串。接著對此 Base64 字串進行 SHA-256 運算，產生唯一的數位指紋。\n"
            "4. **區塊封存**: 每一次的生成紀錄（包含輸入參數、時間戳記、Base64 內容及其雜湊值）被視為一個「區塊」，串聯形成不可變的證據鏈。\n"
            "5. **報告產出**: 當使用者結束任務時，系統會將整個證據鏈上的所有資訊，以及最終所有「區塊」的整合性雜湊值，一同寫入本份 PDF 報告中。"
        )

    def create_generation_details_page(self, experiment_meta, snapshots):
        self.add_page()
        self.chapter_title("一、生成任務基本資訊")
        self.set_font("NotoSansTC", "", 10)
        self.set_text_color(0)
        for key, value in experiment_meta.items():
            self.cell(40, 8, f"  {key}:", align='L')
            self.set_font("NotoSansTC", "", 9)
            self.set_text_color(80)
            self.multi_cell(0, 8, str(value), align='L', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_font("NotoSansTC", "", 10)
            self.set_text_color(0)
        self.ln(10)

        self.chapter_title("二、各版本生成快照")
        for snapshot in snapshots:
            self.set_font("NotoSansTC", "", 12)
            self.set_text_color(0)
            self.cell(0, 10, f"版本索引: {snapshot['version_index']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
            self.ln(2)
            details = [
                ("時間戳記 (UTC)", snapshot['sealed_at']),
                ("圖像雜湊 (SHA-256 over Base64)", snapshot['snapshot_hash']),
                ("輸入指令 (Prompt)", snapshot['input_data']['prompt']),
                ("隨機種子 (Seed)", str(snapshot['input_data']['seed']))
            ]
            for key, value in details:
                self.set_font("NotoSansTC", "", 10)
                self.set_text_color(0)
                self.cell(60, 7, f"  - {key}:", align='L')
                self.set_font("NotoSansTC", "", 9)
                self.set_text_color(80)
                self.multi_cell(0, 7, str(value), align='L', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            
            self.ln(5)
            if os.path.exists(snapshot['generated_image_path']):
                self.image(snapshot['generated_image_path'], x=(self.w-80)/2, w=80)
            self.ln(15)

    def create_conclusion_page(self, event_hash, num_snapshots):
        self.add_page()
        self.chapter_title("三、結論")
        self.chapter_body(
            f"本次出證任務包含 {num_snapshots} 個版本的生成快照。所有快照的元數據（包含 Base64 內容）已被整合並計算出最終的「事件雜湊值」。\n\n"
            "此雜湊值是對整個生成歷史的唯一數位簽章，可用於驗證本報告所含數據的完整性與真實性。"
        )
        self.ln(10)
        self.set_font("NotoSansTC", "", 12)
        self.set_text_color(0)
        self.cell(0, 10, "最終事件雜湊值 (Final Event Hash):", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Courier", "B", 11)
        self.multi_cell(0, 8, event_hash, border=1, align='C', padding=5)

        qr_data = f"https://wesmart.ai/verify?hash={event_hash}"
        qr = qrcode.make(qr_data)
        qr_path = os.path.join(app.config['UPLOAD_FOLDER'], f"qr_{event_hash[:10]}.png")
        qr.save(qr_path)
        self.ln(10)
        
        self.set_font("NotoSansTC", "", 10)
        
        self.cell(0, 10, "掃描 QR Code 以核對報告真偽。", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.image(qr_path, w=50, x=(self.w-50)/2)
# --- 全域會話變數 ---
trace_token = str(uuid.uuid4())
snapshots = []
version_counter = 1
# 用於暫存生成時的 input_data，以便存證時使用
temp_payloads = {}

@app.route('/')
def index():
    global snapshots, version_counter, trace_token, temp_payloads
    snapshots, version_counter, trace_token = [], 1, str(uuid.uuid4())
    temp_payloads = {}
    api_key_set = bool(API_KEY)
    return render_template('index.html', api_key_set=api_key_set)

@app.route('/generate', methods=['POST'])
def generate():
    global version_counter, temp_payloads
    if not API_KEY:
        return jsonify({"error": "後端尚未設定 TOGETHER_API_KEY 環境變數"}), 500
        
    data = request.json
    prompt, seed_input = data.get('prompt'), data.get('seed')
    width, height = int(data.get('width', 512)), int(data.get('height', 512))
    
    if not prompt: return jsonify({"error": "Prompt 為必填項"}), 400
    
    seed_value = int(seed_input) if seed_input and seed_input.isdigit() else random.randint(1, 10**9)
    url = "https://api.together.xyz/v1/images/generations"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    payload = {"model": "black-forest-labs/FLUX.1-schnell", "prompt": prompt, "seed": seed_value, "steps": 8, "width": width, "height": height}
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=60)
        res.raise_for_status()
        image_url = res.json()["data"][0]["url"]
        image_response = requests.get(image_url, timeout=60)
        image_response.raise_for_status()
        img_bytes_from_api = image_response.content
        
        # 步驟1: 僅儲存預覽圖，不進行存證
        filename = f"preview_v{version_counter}_{int(time.time())}.png"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        Image.open(io.BytesIO(img_bytes_from_api)).save(filepath)

        # 暫存這次請求的 payload，以便後續存證使用
        temp_payloads[filename] = payload

        response_data = {
            "success": True, 
            "filename": filename, # 回傳檔名給前端
            "image_url": url_for('static_preview', filename=filename),
            "download_url": url_for('static_download', filename=filename),
            "version": version_counter, 
            "seed": seed_value
        }
        version_counter += 1
        return jsonify(response_data)

    except Exception as e:
        return jsonify({"error": f"生成失敗: {str(e)}"}), 500

@app.route('/seal', methods=['POST'])
def seal():
    global snapshots, temp_payloads
    data = request.json
    filename = data.get('filename')

    if not filename:
        return jsonify({"error": "缺少檔名，無法存證"}), 400

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "檔案不存在，無法存證"}), 404
        
    try:
        # 步驟2: 讀取已儲存的檔案
        with open(filepath, "rb") as image_file:
            definitive_img_bytes = image_file.read()
        
        # 步驟3: Base64 編碼與雜湊
        img_base64_str = base64.b64encode(definitive_img_bytes).decode('utf-8')
        snapshot_hash = sha256_bytes(img_base64_str.encode('utf-8'))

        # 步驟4: 建立封存區塊
        sealed_block = {
            "version_index": len(snapshots) + 1, # 使用 snapshots 的長度來決定版本
            "trace_token": trace_token,
            "input_data": temp_payloads.get(filename, {}), # 從暫存區取得 payload
            "snapshot_hash": snapshot_hash,
            "sealed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "content_base64": img_base64_str,
            "generated_image_path": filepath
        }
        snapshots.append(sealed_block)
        
        return jsonify({"success": True, "message": f"檔案 {filename} 已成功存證"})
    
    except Exception as e:
        return jsonify({"error": f"存證失敗: {str(e)}"}), 500


@app.route('/finalize', methods=['POST'])
def finalize():
    global snapshots
    data = request.json
    applicant_name = data.get('applicant_name')

    if not applicant_name: return jsonify({"error": "出證申請人名稱為必填項"}), 400
    if not snapshots: return jsonify({"error": "沒有已存證的圖像可製作報告"}), 400

    try:
        report_id = str(uuid.uuid4())
        report_time_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')
        
        pdf = WesmartPDFReport()
        pdf.create_cover({'applicant': applicant_name, 'report_time': report_time_str, 'report_id': report_id})
        pdf.create_disclaimer_page()
        pdf.create_overview_page()

        # 根據 snapshots 內的資料來建立報告
        snapshots.sort(key=lambda x: x['version_index']) # 確保順序
        experiment_meta = {
            "Trace Token": trace_token, "出證申請人": applicant_name,
            "首次存證時間": snapshots[0]['sealed_at'], "最終存證時間": snapshots[-1]['sealed_at'],
            "總共存證版本數": len(snapshots), "使用模型": snapshots[0]['input_data'].get('model', 'N/A')
        }
        pdf.create_generation_details_page(experiment_meta, snapshots)

        final_event_data = json.dumps(snapshots, sort_keys=True, ensure_ascii=False).encode('utf-8')
        final_event_hash = sha256_bytes(final_event_data)
        pdf.create_conclusion_page(final_event_hash, len(snapshots))
        
        report_filename = f"WesmartAI_Report_{report_id}.pdf"
        report_filepath = os.path.join(app.config['UPLOAD_FOLDER'], report_filename)
        pdf.output(report_filepath)

        return jsonify({
            "success": True,
            "report_url": url_for('static_download', filename=report_filename),
        })

    except Exception as e:
        print(f"報告生成失敗: {e}")
        return jsonify({"error": f"報告生成失敗: {str(e)}"}), 500

@app.route('/static/preview/<path:filename>')
def static_preview(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/static/download/<path:filename>')
def static_download(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
