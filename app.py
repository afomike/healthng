import os
import uuid
import requests
import logging
from flask import Flask, request, jsonify, render_template, session
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# ── Load .env ─────────────────────────────────────────────────────────────────
load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("healthng")

app = Flask(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
app.secret_key = os.environ["SECRET_KEY"]

UPLOAD_FOLDER      = "uploads"
ALLOWED_EXTENSIONS = {"pdf", "txt"}
app.config["UPLOAD_FOLDER"]       = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"]  = 5 * 1024 * 1024   # 5 MB

# ── Read all provider keys from environment ───────────────────────────────────
# Any key left as the placeholder string is treated as "not configured"
def _key(name):
    val = os.environ.get(name, "")
    return val if val and not val.startswith("your-") else ""

GROQ_API_KEY       = _key("GROQ_API_KEY")
TOGETHER_API_KEY   = _key("TOGETHER_API_KEY")
OPENROUTER_API_KEY = _key("OPENROUTER_API_KEY")
# CF_ACCOUNT_ID      = _key("CF_ACCOUNT_ID")  # DISABLED: Cloudflare API no longer used
# CF_API_TOKEN       = _key("CF_API_TOKEN")    # DISABLED: Cloudflare API no longer used
HF_API_KEY         = _key("HF_API_KEY")
GEMINI_API_KEY     = _key("GEMINI_API_KEY")

# ── System prompt ─────────────────────────────────────────────────────────────
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


# ══════════════════════════════════════════════════════════════════════════════
#  PROVIDER FUNCTIONS
#  Each returns (text, None) on success or (None, error_string) on failure.
#  They raise ProviderQuotaError when quota is hit so the router skips ahead.
# ══════════════════════════════════════════════════════════════════════════════

class ProviderQuotaError(Exception):
    """Raised when a provider hits quota / rate limit / model-not-found."""
    pass


def _is_quota_error(code, msg):
    """Return True if this error means 'try the next provider'."""
    skippable_codes = {429, 404, 503, 529}
    skippable_keywords = (
        "quota", "not found", "deprecated", "unavailable",
        "exhausted", "limit", "exceeded", "rate", "capacity",
        "overloaded", "too many"
    )
    return (
        code in skippable_codes
        or any(k in msg.lower() for k in skippable_keywords)
    )


# ── 1. Groq ───────────────────────────────────────────────────────────────────
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]

def call_groq(prompt):
    if not GROQ_API_KEY:
        raise ProviderQuotaError("Groq key not configured")
    for model in GROQ_MODELS:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                         "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_CONTEXT},
                        {"role": "user",   "content": prompt},
                    ],
                    "max_tokens": 1500,
                    "temperature": 0.4,
                },
                timeout=30,
            )
            if resp.ok:
                log.info(f"Groq success ({model})")
                return resp.json()["choices"][0]["message"]["content"], None
            err  = resp.json().get("error", {})
            code = resp.status_code
            msg  = err.get("message", str(err))
            log.warning(f"Groq {model} -> {code}: {msg[:100]}")
            if _is_quota_error(code, msg):
                continue
            return None, f"Groq error: {msg}"
        except requests.exceptions.Timeout:
            log.warning(f"Groq {model} timed out")
            continue
        except Exception as e:
            log.warning(f"Groq {model} exception: {e}")
            continue
    raise ProviderQuotaError("All Groq models quota/unavailable")


# ── 2. Together AI ────────────────────────────────────────────────────────────
TOGETHER_MODELS = [
    "meta-llama/Llama-3-70b-chat-hf",
    "meta-llama/Llama-3-8b-chat-hf",
    "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "Qwen/Qwen2.5-72B-Instruct-Turbo",
]

def call_together(prompt):
    if not TOGETHER_API_KEY:
        raise ProviderQuotaError("Together AI key not configured")
    for model in TOGETHER_MODELS:
        try:
            resp = requests.post(
                "https://api.together.xyz/v1/chat/completions",
                headers={"Authorization": f"Bearer {TOGETHER_API_KEY}",
                         "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_CONTEXT},
                        {"role": "user",   "content": prompt},
                    ],
                    "max_tokens": 1500,
                    "temperature": 0.4,
                },
                timeout=30,
            )
            if resp.ok:
                log.info(f"Together AI success ({model})")
                return resp.json()["choices"][0]["message"]["content"], None
            err  = resp.json().get("error", {})
            code = resp.status_code
            msg  = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            log.warning(f"Together {model} -> {code}: {msg[:100]}")
            if _is_quota_error(code, msg):
                continue
            return None, f"Together AI error: {msg}"
        except requests.exceptions.Timeout:
            log.warning(f"Together {model} timed out")
            continue
        except Exception as e:
            log.warning(f"Together {model} exception: {e}")
            continue
    raise ProviderQuotaError("All Together AI models quota/unavailable")


# ── 3. OpenRouter ─────────────────────────────────────────────────────────────
OPENROUTER_MODELS = [
    "meta-llama/llama-3.1-8b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "google/gemma-2-9b-it:free",
    "qwen/qwen-2-7b-instruct:free",
    "microsoft/phi-3-mini-128k-instruct:free",
]

def call_openrouter(prompt):
    if not OPENROUTER_API_KEY:
        raise ProviderQuotaError("OpenRouter key not configured")
    for model in OPENROUTER_MODELS:
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://healthng-ai.onrender.com",
                    "X-Title": "HealthNG AI",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_CONTEXT},
                        {"role": "user",   "content": prompt},
                    ],
                    "max_tokens": 1500,
                    "temperature": 0.4,
                },
                timeout=30,
            )
            if resp.ok:
                content = resp.json()["choices"][0]["message"]["content"]
                if content and content.strip():
                    log.info(f"OpenRouter success ({model})")
                    return content, None
            err  = resp.json().get("error", {})
            code = resp.status_code
            msg  = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            log.warning(f"OpenRouter {model} -> {code}: {msg[:100]}")
            if _is_quota_error(code, msg):
                continue
            return None, f"OpenRouter error: {msg}"
        except requests.exceptions.Timeout:
            log.warning(f"OpenRouter {model} timed out")
            continue
        except Exception as e:
            log.warning(f"OpenRouter {model} exception: {e}")
            continue
    raise ProviderQuotaError("All OpenRouter models quota/unavailable")


# ── 4. Cloudflare Workers AI ── DISABLED ──────────────────────────────────────
# CLOUDFLARE API IMPLEMENTATION HAS BEEN DISABLED
# To re-enable, uncomment the CF_ACCOUNT_ID and CF_API_TOKEN variables above,
# and uncomment the call_cloudflare function, then add it back to PROVIDERS list
# 
# CF_MODELS = [
#     "@cf/meta/llama-3.1-8b-instruct",
#     "@cf/mistral/mistral-7b-instruct-v0.1",
#     "@cf/google/gemma-7b-it",
#     "@cf/microsoft/phi-2",
# ]
# 
# def call_cloudflare(prompt):
#     if not CF_ACCOUNT_ID or not CF_API_TOKEN:
#         raise ProviderQuotaError("Cloudflare credentials not configured")
#     for model in CF_MODELS:
#         try:
#             resp = requests.post(
#                 f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model}",
#                 headers={"Authorization": f"Bearer {CF_API_TOKEN}",
#                          "Content-Type": "application/json"},
#                 json={
#                     "messages": [
#                         {"role": "system", "content": SYSTEM_CONTEXT},
#                         {"role": "user",   "content": prompt},
#                     ],
#                     "max_tokens": 1500,
#                 },
#                 timeout=30,
#             )
#             if resp.ok:
#                 data = resp.json()
#                 text = (
#                     data.get("result", {}).get("response")
#                     or (data.get("result", {}).get("choices") or [{}])[0]
#                        .get("message", {}).get("content", "")
#                 )
#                 if text and text.strip():
#                     log.info(f"Cloudflare success ({model})")
#                     return text, None
#             code = resp.status_code
#             msg  = resp.json().get("errors", [{}])[0].get("message", "unknown")
#             log.warning(f"Cloudflare {model} -> {code}: {msg[:100]}")
#             if _is_quota_error(code, msg):
#                 continue
#             return None, f"Cloudflare error: {msg}"
#         except requests.exceptions.Timeout:
#             log.warning(f"Cloudflare {model} timed out")
#             continue
#         except Exception as e:
#             log.warning(f"Cloudflare {model} exception: {e}")
#             continue
#     raise ProviderQuotaError("All Cloudflare models quota/unavailable")


# ── 5. Hugging Face Inference API ─────────────────────────────────────────────
HF_MODELS = [
    "mistralai/Mistral-7B-Instruct-v0.3",
    "HuggingFaceH4/zephyr-7b-beta",
    "microsoft/Phi-3-mini-4k-instruct",
    "Qwen/Qwen2.5-7B-Instruct",
]

def call_huggingface(prompt):
    if not HF_API_KEY:
        raise ProviderQuotaError("HuggingFace key not configured")
    full_prompt = f"{SYSTEM_CONTEXT}\n\nUser: {prompt}\nAssistant:"
    for model in HF_MODELS:
        try:
            resp = requests.post(
                f"https://api-inference.huggingface.co/models/{model}",
                headers={"Authorization": f"Bearer {HF_API_KEY}",
                         "Content-Type": "application/json"},
                json={
                    "inputs": full_prompt,
                    "parameters": {
                        "max_new_tokens": 1000,
                        "temperature": 0.4,
                        "return_full_text": False,
                    },
                },
                timeout=45,
            )
            if resp.ok:
                data = resp.json()
                # HF returns list of dicts or a dict
                if isinstance(data, list) and data:
                    text = data[0].get("generated_text", "").strip()
                elif isinstance(data, dict):
                    text = data.get("generated_text", "").strip()
                else:
                    text = ""
                if text:
                    log.info(f"HuggingFace success ({model})")
                    return text, None
            code = resp.status_code
            msg  = str(resp.json())[:100]
            log.warning(f"HuggingFace {model} -> {code}: {msg}")
            if _is_quota_error(code, msg):
                continue
            return None, f"HuggingFace error: {msg}"
        except requests.exceptions.Timeout:
            log.warning(f"HuggingFace {model} timed out")
            continue
        except Exception as e:
            log.warning(f"HuggingFace {model} exception: {e}")
            continue
    raise ProviderQuotaError("All HuggingFace models quota/unavailable")


# ── 6. Gemini (self-healing model discovery) ──────────────────────────────────
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_PREFERRED = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.0-pro",
]
_gemini_models_cache: list = []

def _discover_gemini_models():
    global _gemini_models_cache
    if _gemini_models_cache:
        return _gemini_models_cache
    try:
        resp = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}",
            timeout=10,
        )
        if resp.ok:
            all_m = resp.json().get("models", [])
            supported = [
                m["name"].replace("models/", "")
                for m in all_m
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
            ordered = [p for p in GEMINI_PREFERRED if p in supported]
            ordered += [m for m in supported if m not in ordered and "flash" in m.lower()]
            ordered += [m for m in supported if m not in ordered]
            _gemini_models_cache = ordered or GEMINI_PREFERRED
            log.info(f"Gemini live models: {_gemini_models_cache}")
            return _gemini_models_cache
    except Exception as e:
        log.warning(f"Gemini discovery failed: {e}")
    _gemini_models_cache = GEMINI_PREFERRED
    return _gemini_models_cache

def call_gemini(prompt):
    if not GEMINI_API_KEY:
        raise ProviderQuotaError("Gemini key not configured")
    models = _discover_gemini_models()
    payload = {
        "contents": [{"parts": [{"text": f"{SYSTEM_CONTEXT}\n\n{prompt}"}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1500},
    }
    for model in models:
        try:
            resp = requests.post(
                f"{GEMINI_BASE}/{model}:generateContent?key={GEMINI_API_KEY}",
                json=payload, timeout=30,
            )
            if resp.ok:
                log.info(f"Gemini success ({model})")
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"], None
            err  = resp.json().get("error", {})
            code = err.get("code", resp.status_code)
            msg  = err.get("message", "Unknown error")
            log.warning(f"Gemini {model} -> {code}: {msg[:100]}")
            if _is_quota_error(code, msg):
                continue
            return None, f"Gemini error: {msg}"
        except requests.exceptions.Timeout:
            log.warning(f"Gemini {model} timed out")
            continue
        except Exception as e:
            log.warning(f"Gemini {model} exception: {e}")
            continue
    raise ProviderQuotaError("All Gemini models quota/unavailable")


# ══════════════════════════════════════════════════════════════════════════════
#  MASTER ROUTER — tries all 6 providers in order
# ══════════════════════════════════════════════════════════════════════════════

PROVIDERS = [
    ("Groq",          call_groq),
    ("Together AI",   call_together),
    ("OpenRouter",    call_openrouter),
    # ("Cloudflare",    call_cloudflare),  # DISABLED: Cloudflare API no longer used
    ("HuggingFace",   call_huggingface),
    ("Gemini",        call_gemini),
]

def call_llm(prompt: str) -> tuple:
    """
    Try every configured provider in order.
    Returns (text, None) on first success.
    Returns (None, error) only if every single provider fails.
    """
    errors = []
    for name, fn in PROVIDERS:
        try:
            text, err = fn(prompt)
            if text:
                return text, None
            if err:
                log.warning(f"{name} returned error (non-quota): {err}")
                errors.append(f"{name}: {err}")
        except ProviderQuotaError as e:
            log.info(f"{name} quota/skip: {e}")
            errors.append(f"{name}: quota/unavailable")
            continue
        except Exception as e:
            log.warning(f"{name} unexpected exception: {e}")
            errors.append(f"{name}: {e}")
            continue

    summary = " | ".join(errors)
    log.error(f"All providers failed: {summary}")
    return None, (
        "All AI providers are currently unavailable. Please try again in a few minutes. "
        f"Details: {summary}"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def configured_providers() -> list:
    """Return names of providers that have keys set."""
    active = []
    if GROQ_API_KEY:       active.append("Groq")
    if TOGETHER_API_KEY:   active.append("Together AI")
    if OPENROUTER_API_KEY: active.append("OpenRouter")
    # if CF_ACCOUNT_ID and CF_API_TOKEN: active.append("Cloudflare")  # DISABLED
    if HF_API_KEY:         active.append("HuggingFace")
    if GEMINI_API_KEY:     active.append("Gemini")
    return active


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    # Serve the public landing page (marketing/hero) at root
    return render_template("landing.html")


@app.route("/app")
def app_page():
    # Serve the live platform UI (app shell) here
    return render_template("app.html")


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    active = configured_providers()
    return jsonify({
        "status":     "ok",
        "ai_ready":   len(active) > 0,
        "providers":  active,
        "doc_count":  len(session.get("docs", [])),
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

    result, error = call_llm(prompt)
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

    result, error = call_llm(prompt)
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

    result, error = call_llm(prompt)
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

    result, error = call_llm(prompt)
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
    session["docs"]  = docs
    session.modified = True
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

Cite relevant sections. Supplement with Nigerian medical knowledge where needed."""
    else:
        prompt = f"Answer this medical question with specific relevance to Nigerian healthcare:\n\nQuestion: {query}"

    result, error = call_llm(prompt)
    if error:
        return jsonify({"error": error}), 500
    return jsonify({"result": result})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    log.info(f"Configured providers: {configured_providers()}")
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)
