# ====================================================================
# WesmartAI 證據報告 Web App (final_definitive_flow)
# 作者: Gemini & User
# 核心架構 (最終定案):
# 1. 確立最終使用者流程：多次生成預覽 -> 一次性結束並下載所有原圖 -> 可選地生成PDF報告。
# 2. 前端恢復 Seed 與尺寸輸入，後端 /generate 同步接收。
# 3. /finalize_session 作為核心，處理整個任務的證據封裝，並回傳所有圖片連結。
# 4. JSON 證據檔案僅存於後端，不提供給使用者。
# ====================================================================

import requests, json, hashlib, uuid, datetime, random, time, os, io, base64
from flask import Flask, render_template, request, jsonify, send_from_directory, url_for
from PIL import Image
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import qrcode

# --- 讀取環境變數 ---
API_key = os.getenv("TOGETHER_API_KEY")

# --- Flask App 初始化 ---
app = Flask(__name__)
static_folder = 'static'
if not os.path.exists(static_folder): os.makedirs(static_folder)
app.config['UPLOAD_FOLDER'] = static_folder

# --- Helper Functions and PDF Class (與前版相同) ---
def sha256_bytes(b): return hashlib.sha256(b).hexdigest()

class WesmartPDFReport(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not os.path.exists("NotoSansTC.otf"):
            print("正在下載中文字型...")
            try:
                r = requests.get("https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Regular.otf")
                r.raise_for_status()
                with open("NotoSansTC.otf", "wb") as f: f.write(r.content)
                print("字型下載完成。")
            except Exception as e: print(f"字型下載失敗: {e}")
        self.add_font("NotoSansTC", "", "NotoSansTC.otf")
        self.set_auto_page_break(auto=True, margin=25); self.alias_nb_pages()
        self.logo_path = "LOGO.jpg" if os.path.exists("LOGO.jpg") else None
    def header(self):
        if self.logo_path:
            with self.local_context(fill_opacity=0.08, stroke_opacity=0.08):
                img_w=120; center_x=(self.w-img_w)/2; center_y=(self.h-img_w)/2; self.image(self.logo_path, x=center_x, y=center_y, w=img_w)
        if self.page_no() > 1: self.set_font("NotoSansTC", "", 9); self.set_text_color(128); self.cell(0, 10, "WesmartAI 生成式 AI 證據報告", new_x=XPos.LMARGIN, new_y=YPos.TOP, align='L'); self.cell(0, 10, "WesmartAI Inc.", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')
    def footer(self): self.set_y(-15); self.set_font("NotoSansTC", "", 8); self.set_text_color(128); self.cell(0, 10, f'第 {self.page_no()}/{{nb}} 頁', align='C')
    def chapter_title(self, title): self.set_font("NotoSansTC", "", 16); self.set_text_color(0); self.cell(0, 12, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L'); self.ln(6)
    def chapter_body(self, content): self.set_font("NotoSansTC", "", 10); self.set_text_color(50); self.multi_cell(0, 7, content, align='L'); self.ln()
    def create_cover(self, meta):
        self.add_page();
        if self.logo_path: self.image(self.logo_path, x=(self.w-60)/2, y=25, w=60)
        self.set_y(100); self.set_font("NotoSansTC", "", 28); self.cell(0, 20, "WesmartAI 證據報告", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C'); self.ln(20)
        self.set_font("NotoSansTC", "", 12)
        data = [("出證申請人:", meta.get('applicant', 'N/A')), ("申請事項:", "WesmartAI 生成式 AI 證據報告"), ("申請出證時間:", meta.get('issued_at', 'N/A')), ("出證編號 (報告ID):", meta.get('report_id', 'N/A')), ("出證單位:", meta.get('issuer', 'N/A'))]
        for row in data: self.cell(20); self.cell(45, 10, row[0], align='L'); self.multi_cell(0, 10, row[1], new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
    def create_generation_details_page(self, proof_data):
        self.add_page(); self.chapter_title("一、生成任務基本資訊"); self.set_font("NotoSansTC", "", 10); self.set_text_color(0)
        experiment_meta = {"Trace Token": proof_data['event_proof']['trace_token'], "總共版本數": len(proof_data['event_proof']['snapshots'])}
        for key, value in experiment_meta.items():
            self.cell(40, 8, f"  {key}:", align='L'); self.set_font("NotoSansTC", "", 9); self.set_text_color(80)
            self.multi_cell(0, 8, str(value), align='L', new_x=XPos.LMARGIN, new_y=YPos.NEXT); self.set_font("NotoSansTC", "", 10); self.set_text_color(0)
        self.ln(10)
        self.chapter_title("二、各版本生成快照")
        for snapshot in proof_data['event_proof']['snapshots']:
            self.set_font("NotoSansTC", "", 12); self.set_text_color(0); self.cell(0, 10, f"版本索引: {snapshot['version_index']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L'); self.ln(2)
            details = [("時間戳記 (UTC)", snapshot['timestamp_utc']), ("圖像雜湊 (SHA-256 over Base64)", snapshot['snapshot_hash']), ("輸入指令 (Prompt)", snapshot['prompt']), ("隨機種子 (Seed)", str(snapshot['seed']))]
            for key, value in details:
                self.set_font("NotoSansTC", "", 10); self.set_text_color(0); self.cell(60, 7, f"  - {key}:", align='L'); self.set_font("NotoSansTC", "", 9); self.set_text_color(80)
                self.multi_cell(0, 7, str(value), align='L', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(5)
            try:
                img_bytes = base64.b64decode(snapshot['content_base64'])
                img_file_obj = io.BytesIO(img_bytes)
                self.image(img_file_obj, x=(self.w-80)/2, w=80, type='PNG')
            except Exception as e: print(f"在PDF中顯示圖片失敗: {e}")
            self.ln(15)
    def create_conclusion_page(self, proof_data):
        self.add_page(); self.chapter_title("三、報告驗證")
        self.chapter_body("本報告的真實性與完整性，取決於其對應的 `proof_event.json` 證據檔案。此 JSON 檔案的雜湊值（Final Event Hash）被記錄於下，可用於比對與驗證。")
        self.ln(10); self.set_font("NotoSansTC", "", 12); self.set_text_color(0)
        self.cell(0, 10, "最終事件雜湊值 (Final Event Hash):", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Courier", "B", 11)
        self.multi_cell(0, 8, proof_data['event_proof']['final_event_hash'], border=1, align='C', padding=5)
        qr_data = proof_data['verification']['verify_url']
        qr = qrcode.make(qr_data); qr_path = os.path.join(app.config['UPLOAD_FOLDER'], f"qr_{proof_data['report_id'][:10]}.png"); qr.save(qr_path)
        self.ln(10); self.set_font("NotoSansTC", "", 10); self.cell(0, 10, "掃描 QR Code 前往驗證頁面", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.image(qr_path, w=50, x=(self.w-50)/2)
# --- 全域變數 ---
session_previews = []
latest_proof_data = None

@app.route('/')
def index():
    global session_previews, latest_proof_data
    session_previews = []
    latest_proof_data = None
    return render_template('index.html', api_key_set=bool(API_key))

# 步驟1: 生成預覽圖
@app.route('/generate', methods=['POST'])
def generate():
    if not API_key: return jsonify({"error": "後端尚未設定 TOGETHER_API_KEY 環境變數"}), 500
    
    data = request.json
    prompt = data.get('prompt')
    if not prompt: return jsonify({"error": "Prompt 為必填項"}), 400

    try:
        seed_input = data.get('seed')
        width = int(data.get('width', 512))
        height = int(data.get('height', 512))
        seed_value = int(seed_input) if seed_input and seed_input.isdigit() else random.randint(1, 10**9)
        payload = {"model": "black-forest-labs/FLUX.1-schnell", "prompt": prompt, "seed": seed_value, "steps": 8, "width": width, "height": height}
        
        res = requests.post("https://api.together.xyz/v1/images/generations", headers={"Authorization": f"Bearer {API_key}"}, json=payload, timeout=60)
        res.raise_for_status()
        img_bytes = requests.get(res.json()["data"][0]["url"], timeout=60).content
        
        filename = f"preview_v{len(session_previews) + 1}_{int(time.time())}.png"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        Image.open(io.BytesIO(img_bytes)).save(filepath)

        session_previews.append({
            "prompt": prompt, "seed": seed_value, "model": payload['model'],
            "width": width, "height": height, "filepath": filepath,
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()
        })
        
        return jsonify({
            "success": True, 
            "preview_url": url_for('static_preview', filename=filename),
            "version": len(session_previews)
        })

    except Exception as e:
        return jsonify({"error": f"生成失敗: {str(e)}"}), 500

# 步驟2: 結束任務，生成所有證據正本
@app.route('/finalize_session', methods=['POST'])
def finalize_session():
    global latest_proof_data, session_previews
    applicant_name = request.json.get('applicant_name')
    if not applicant_name: return jsonify({"error": "出證申請人名稱為必填項"}), 400
    if not session_previews: return jsonify({"error": "沒有任何預覽圖像可供結束任務"}), 400

    try:
        snapshots = []
        image_urls = []
        
        for i, preview in enumerate(session_previews):
            with open(preview['filepath'], "rb") as f: definitive_bytes = f.read()
            img_base64_str = base64.b64encode(definitive_bytes).decode('utf-8')
            snapshot_hash = sha256_bytes(img_base64_str.encode('utf-8'))
            
            snapshots.append({
                "version_index": i + 1, "timestamp_utc": preview['timestamp_utc'],
                "snapshot_hash": snapshot_hash, "prompt": preview['prompt'],
                "seed": preview['seed'], "model": preview['model'],
                "content_base64": img_base64_str
            })
            image_urls.append(url_for('static_download', filename=os.path.basename(preview['filepath'])))

        report_id = str(uuid.uuid4())
        trace_token = str(uuid.uuid4())
        issued_at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        temp_proof_for_hashing = {"report_id": report_id, "event_proof": {"trace_token": trace_token, "snapshots": snapshots}}
        proof_string_for_hashing = json.dumps(temp_proof_for_hashing, sort_keys=True, ensure_ascii=False).encode('utf-8')
        final_event_hash = sha256_bytes(proof_string_for_hashing)

        proof_data = {
            "report_id": report_id, "issuer": "WesmartAI Inc.", "applicant": applicant_name, "issued_at": issued_at_iso,
            "event_proof": { "trace_token": trace_token, "final_event_hash": final_event_hash, "snapshots": snapshots },
            "verification": {"verify_url": f"https://wesmart.ai/verify?hash={final_event_hash}"}
        }

        json_filename = f"proof_event_{report_id}.json"
        json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
        with open(json_filepath, 'w', encoding='utf-8') as f:
            json.dump(proof_data, f, ensure_ascii=False, indent=2)
        print(f"證據正本已儲存至: {json_filename}")

        latest_proof_data = proof_data

        return jsonify({"success": True, "image_urls": image_urls})

    except Exception as e:
        print(f"結束任務失敗: {e}")
        return jsonify({"error": f"結束任務失敗: {str(e)}"}), 500

# 步驟3: 產生 PDF 報告
@app.route('/create_report', methods=['POST'])
def create_report():
    if not latest_proof_data: return jsonify({"error": "請先結束任務並生成證據"}), 400
    
    try:
        report_id = latest_proof_data['report_id']
        pdf = WesmartPDFReport()
        pdf.create_cover(latest_proof_data)
        pdf.create_generation_details_page(latest_proof_data)
        pdf.create_conclusion_page(latest_proof_data)
        
        report_filename = f"WesmartAI_Report_{report_id}.pdf"
        report_filepath = os.path.join(app.config['UPLOAD_FOLDER'], report_filename)
        pdf.output(report_filepath)

        return jsonify({"success": True, "report_url": url_for('static_download', filename=report_filename)})
    except Exception as e:
        print(f"報告生成失敗: {e}")
        return jsonify({"error": f"報告生成失敗: {str(e)}"}), 500

# --- 靜態檔案路由 ---
@app.route('/static/preview/<path:filename>')
def static_preview(filename): return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/static/download/<path:filename>')
def static_download(filename): return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
