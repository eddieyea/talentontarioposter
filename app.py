import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from pipeline.parse_date import extract_issue_date
from pipeline.render_letter import render_and_mask
from pipeline.composite import build_poster, build_xhs_poster

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB

BASE_DIR = Path(__file__).parent
PROGRAMS = json.loads((BASE_DIR / "config" / "programs.json").read_text())


@app.route("/")
def index():
    return render_template("index.html", programs=list(PROGRAMS.keys()))


@app.route("/generate", methods=["POST"])
def generate():
    pdf_file = request.files.get("pdf")
    client_name = request.form.get("client_name", "").strip()
    program = request.form.get("program", "").strip()

    if not pdf_file or not client_name or not program:
        return jsonify({"error": "Missing required fields"}), 400
    if program not in PROGRAMS:
        return jsonify({"error": f"Unknown program: {program}"}), 400

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        approved_date = extract_issue_date(tmp_path) or "日期未识别"
        letter_img = render_and_mask(tmp_path)

        wechat = build_poster(
            psd_filename=PROGRAMS[program],
            client_name=client_name,
            program_name=program,
            approved_date=approved_date,
            letter_image=letter_img,
        )
        xhs = build_xhs_poster(program_name=program, letter_image=letter_img)

        # Pack both into a ZIP
        safe_name = client_name.replace(" ", "_")
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for img, label in ((wechat, "朋友圈"), (xhs, "小红书")):
                img_buf = io.BytesIO()
                img.save(img_buf, format="PNG", optimize=False)
                img_buf.seek(0)
                zf.writestr(f"移民捷报_{safe_name}_{program}_{label}.png", img_buf.read())

        zip_buf.seek(0)
        return send_file(
            zip_buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"移民捷报_{safe_name}_{program}.zip",
        )
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
