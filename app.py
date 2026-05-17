import os
import uuid
import requests
from flask import Flask, request, jsonify, render_template, session
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# ── Load .env before anything else ───────────────────────────────────────────
load_dotenv()

app = Flask(__name__)

# ── Config (all from environment) ────────────────────────────────────────────
app.secret_key              = os.environ["SECRET_KEY"]
GEMINI_API_KEY              = os.environ["GEMINI_API_KEY"]
UPLOAD_FOLDER               = "uploads"
ALLOWED_EXTENSIONS          = {"pdf", "txt"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024   # 5 MB

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta"
    "/models/gemini-1.5-flash-latest:generateContent"
)

SYSTEM_CONTEXT = """You are Dr. HealthNG AI, a medical assistant specialized in Nigerian healthcare.
You have deep knowledge of:
- Diseases endemic to Nigeria (malaria, typhoid, Lassa fever, cholera, yellow fever, TB, HIV, monkeypox, etc.)
- Nigerian drug market and NAFDAC-approved medications with common local brand names
- NHIS (National Health Insurance Scheme) and healthcare access in Nigeria
- NPHCDA vaccination schedules for Nigerian children
- Traditional medicine context in Nigeria and how it interacts with modern medicine
- Health challenges specific to Nigeria's 36 states and FCT
- Local food, nutrition, and lifestyle factors in Nigeria
- NCDC (Nigeria Centre for Disease Control) guidelines and outbreak alerts

Always be culturally sensitive, practical, and aware of healthcare infrastructure limitations in Nigeria.
Always recommend consulting a real doctor for serious conditions.
For emergencies, mention NCDC emergency hotline: 0800 970 0010.
Format responses with clear numbered sections. Be thorough but practical."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def call_gemini(prompt: str) -> tuple[str | None, str | None]:
    """Call Gemini 1.5 Flash with the server-side API key."""
    payload = {
        "contents": [{"parts": [{"text": f"{SYSTEM_CONTEXT}\n\n{prompt}"}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1500},
    }
    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=payload,
            timeout=30,
        )
        if not resp.ok:
            msg = resp.json().get("error", {}).get("message", "Unknown API error")
            return None, f"Gemini API error: {msg}"
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return text, None
    except requests.exceptions.Timeout:
        return None, "Request timed out — please try again."
    except Exception as exc:
        return None, f"Request failed: {exc}"


# ── Routes — Pages ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── Routes — API ──────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    """Health check — confirms server is running and key is configured."""
    key_ok = bool(GEMINI_API_KEY and GEMINI_API_KEY != "your-gemini-api-key-here")
    return jsonify({
        "status": "ok",
        "ai_ready": key_ok,
        "doc_count": len(session.get("docs", [])),
    })


@app.route("/api/symptom-check", methods=["POST"])
def symptom_check():
    data     = request.get_json() or {}
    symptoms = data.get("symptoms", [])
    if not symptoms:
        return jsonify({"error": "Please select at least one symptom."}), 400

    prompt = f"""Patient profile for medical analysis:
- Age group: {data.get('age', 'Adult (18-60)')}
- Gender: {data.get('gender', 'Not specified')}
- State / Region in Nigeria: {data.get('state', 'Nigeria')}
- Duration of symptoms: {data.get('duration', 'Unknown')}
- Symptoms reported: {', '.join(symptoms)}
{f"- Additional context: {data['notes']}" if data.get('notes') else ''}

Provide a structured analysis:
1. POSSIBLE CONDITIONS — top 3-5 ranked by likelihood given Nigeria disease patterns
2. RED FLAGS — symptoms that need immediate emergency care
3. IMMEDIATE STEPS — what the patient can do right now
4. RECOMMENDED SPECIALIST — which type of doctor or clinic to visit
5. AVAILABLE TREATMENTS IN NIGERIA — drug names, local brand names, and availability"""

    result, error = call_gemini(prompt)
    if error:
        return jsonify({"error": error}), 500
    return jsonify({"result": result})


@app.route("/api/chat", methods=["POST"])
def chat():
    data    = request.get_json() or {}
    message = data.get("message", "").strip()
    history = data.get("history", [])[-6:]
    if not message:
        return jsonify({"error": "Empty message."}), 400

    history_text = "\n".join(
        f"{'Patient' if m['role'] == 'user' else 'Doctor AI'}: {m['text']}"
        for m in history
    )
    prompt = f"{history_text}\nPatient: {message}\nDoctor AI:"

    result, error = call_gemini(prompt)
    if error:
        return jsonify({"error": error}), 500
    return jsonify({"result": result})


@app.route("/api/disease-info", methods=["POST"])
def disease_info():
    data    = request.get_json() or {}
    disease = data.get("disease", "").strip()
    if not disease:
        return jsonify({"error": "No disease specified."}), 400

    prompt = f"""Provide comprehensive information about {disease} in the Nigerian context:
1. Overview & prevalence in Nigeria (statistics where available)
2. Symptoms — early warning signs and advanced-stage presentation
3. High-risk states / regions in Nigeria
4. Diagnosis methods available in Nigerian hospitals and clinics
5. Treatment options & drugs available in Nigeria (NAFDAC-approved, with local brand names)
6. Prevention measures practical for Nigerians
7. When to seek emergency care — red flags
8. NCDC / FMOH resources, programs, and emergency hotlines"""

    result, error = call_gemini(prompt)
    if error:
        return jsonify({"error": error}), 500
    return jsonify({"result": result})


@app.route("/api/prevention", methods=["POST"])
def prevention():
    data  = request.get_json() or {}
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "No topic specified."}), 400

    prompt = f"""Provide a detailed, practical prevention and care guide for: {topic}
Be specific to the Nigerian context — reference available government programs, local facilities,
affordable local options, and practical constraints faced by ordinary Nigerians.
Include cost-effective solutions and reference any FMOH or NCDC programs."""

    result, error = call_gemini(prompt)
    if error:
        return jsonify({"error": error}), 500
    return jsonify({"result": result})


@app.route("/api/upload-doc", methods=["POST"])
def upload_doc():
    if "file" not in request.files:
        return jsonify({"error": "No file in request."}), 400
    file = request.files["file"]
    if not file.filename or not allowed_file(file.filename):
        return jsonify({"error": "Only PDF and TXT files are allowed."}), 400

    filename    = secure_filename(file.filename)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    save_path   = os.path.join(app.config["UPLOAD_FOLDER"], unique_name)
    file.save(save_path)

    # Extract text content
    content = ""
    if filename.lower().endswith(".txt"):
        with open(save_path, "r", errors="ignore") as f:
            content = f.read()[:6000]
    else:
        try:
            import pdfplumber
            with pdfplumber.open(save_path) as pdf:
                content = "\n".join(
                    page.extract_text() or "" for page in pdf.pages[:10]
                )[:6000]
        except Exception:
            content = f"[PDF: {filename} — text extraction unavailable]"

    docs = session.get("docs", [])
    docs.append({
        "name":    filename,
        "path":    unique_name,
        "content": content,
        "size":    os.path.getsize(save_path),
    })
    session["docs"]    = docs
    session.modified   = True
    return jsonify({"success": True, "name": filename, "size": os.path.getsize(save_path)})


@app.route("/api/query-docs", methods=["POST"])
def query_docs():
    data    = request.get_json() or {}
    query   = data.get("query", "").strip()
    general = data.get("general", False)
    if not query:
        return jsonify({"error": "No query provided."}), 400

    docs = session.get("docs", [])
    if not general and docs:
        doc_context = "\n\n".join(f"=== {d['name']} ===\n{d['content']}" for d in docs)
        prompt = f"""You are a medical document analyst for Nigerian healthcare.
Answer this question based on the uploaded documents:
Question: {query}

Documents:
{doc_context}

Cite relevant sections. Supplement with Nigerian medical knowledge where the documents are insufficient."""
    else:
        prompt = f"Answer this medical question with specific relevance to Nigerian healthcare:\n\nQuestion: {query}"

    result, error = call_gemini(prompt)
    if error:
        return jsonify({"error": error}), 500
    return jsonify({"result": result})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)
