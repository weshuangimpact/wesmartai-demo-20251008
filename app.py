# ==========================================================
# WesmartAI × Together AI (Flux Schnell)
# 新增功能：每張生成圖下方加入「以此為基底再生成」
# ==========================================================

from flask import Flask, render_template, request, jsonify
import requests, os, base64, hashlib, datetime, uuid
from fpdf import FPDF
from PIL import Image

app = Flask(__name__)

TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")  # 建議環境變數設定
MODEL_NAME = "black-forest-labs/FLUX.1-schnell"
GENERATED_DIR = "static/generated"
os.makedirs(GENERATED_DIR, exist_ok=True)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


# === Route: 首頁 ===
@app.route("/")
def index():
    return render_template("index.html")


# === Route: 生成圖像 ===
@app.route("/generate", methods=["POST"])
def generate():
    prompt = request.form.get("prompt", "")
    seed = request.form.get("seed", "1234")
    steps = int(request.form.get("steps", "8"))
    base_image_id = request.form.get("base_image_id")

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "steps": steps,
        "seed": int(seed),
    }

    # 若使用者選擇以舊圖為基底
    if base_image_id:
        base_path = os.path.join(GENERATED_DIR, f"{base_image_id}.png")
        if os.path.exists(base_path):
            with open(base_path, "rb") as f:
                base_b64 = base64.b64encode(f.read()).decode("utf-8")
            payload["image_prompt"] = base_b64
            payload["image_prompt_strength"] = 0.5

    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}"}
    res = requests.post("https://api.together.xyz/v1/images/generations",
                        headers=headers, json=payload)

    if res.status_code != 200:
        return jsonify({"error": res.text}), 500

    data = res.json()
    polling_url = data.get("polling_url")
    if not polling_url:
        return jsonify({"error": "No polling URL"}), 500

    # 輪詢直到完成
    import time
    while True:
        poll = requests.get(polling_url, headers=headers).json()
        if poll.get("status") == "Ready":
            img_url = poll["result"]["sample"]
            img_bytes = requests.get(img_url).content
            break
        elif poll.get("status") == "Failed":
            return jsonify({"error": "Generation failed"}), 500
        time.sleep(1)

    img_id = str(uuid.uuid4())
    img_path = os.path.join(GENERATED_DIR, f"{img_id}.png")
    with open(img_path, "wb") as f:
        f.write(img_bytes)

    hash_val = sha256_bytes(img_bytes)
    return jsonify({
        "image_id": img_id,
        "image_url": f"/{img_path}",
        "seed": seed,
        "hash": hash_val,
        "base_from": base_image_id or None
    })


# === Route: 生成報告 (簡化) ===
@app.route("/create_report", methods=["POST"])
def create_report():
    image_id = request.form.get("image_id")
    prompt = request.form.get("prompt")
    seed = request.form.get("seed")
    hash_val = request.form.get("hash")

    img_path = os.path.join(GENERATED_DIR, f"{image_id}.png")
    report_name = f"report_{image_id}.pdf"

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "WesmartAI Image Generation Report", ln=True)

    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 8, f"Prompt: {prompt}")
    pdf.multi_cell(0, 8, f"Seed: {seed}")
    pdf.multi_cell(0, 8, f"Hash: {hash_val}")
    pdf.image(img_path, x=30, y=70, w=150)
    pdf.output(os.path.join(GENERATED_DIR, report_name))

    return jsonify({"report_url": f"/{GENERATED_DIR}/{report_name}"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
