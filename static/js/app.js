'use strict';

// ── Data ─────────────────────────────────────────────────────────────────────

const SYMPTOMS = [
  'Fever','Headache','Body aches','Chills','Sweating','Fatigue',
  'Nausea','Vomiting','Diarrhoea','Stomach pain','Yellow eyes (jaundice)',
  'Rash','Cough','Difficulty breathing','Sore throat','Runny nose',
  'Joint pain','Loss of appetite','Convulsions','Bleeding','Dark urine',
  'Swollen lymph nodes','Dizziness','Chest pain',
];

const NG_DISEASES = [
  { name:'Malaria',                  risk:'high', zone:'Nationwide',               vector:'Mosquito (Anopheles)',         season:'Year-round, peaks rainy season' },
  { name:'Typhoid Fever',            risk:'high', zone:'Urban & peri-urban',        vector:'Contaminated food / water',    season:'Year-round' },
  { name:'Lassa Fever',              risk:'high', zone:'Edo, Ondo, Ebonyi, Bauchi', vector:'Mastomys rat contact',         season:'Nov – May' },
  { name:'Cholera',                  risk:'med',  zone:'Coastal & flood-prone',     vector:'Contaminated water',           season:'Rainy season' },
  { name:'Yellow Fever',             risk:'med',  zone:'North-central, South-west', vector:'Aedes mosquito',               season:'Rainy season' },
  { name:'Cerebrospinal Meningitis', risk:'med',  zone:'Meningitis belt (North)',   vector:'Neisseria meningitidis',       season:'Dry season (Dec – Jun)' },
  { name:'Monkeypox',                risk:'low',  zone:'South-south',               vector:'Animal contact / person–person',season:'Year-round' },
  { name:'Tuberculosis (TB)',        risk:'high', zone:'Urban, HIV co-infection',   vector:'Airborne (M. tuberculosis)',   season:'Year-round' },
];

// ── State ─────────────────────────────────────────────────────────────────────
let selectedSymptoms = [];
let chatHistory      = [];

// ── Helpers ───────────────────────────────────────────────────────────────────

async function api(path, body) {
  const opts = {
    method:  body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body:    body ? JSON.stringify(body) : undefined,
  };
  const res  = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function setResult(textEl, cardEl, text) {
  // Clear previous results
  textEl.innerHTML = '';
  
  // Render plain or Markdown-like text into structured, safe HTML
  try {
    if (typeof renderRichText === 'function') {
      const html = renderRichText(text || '');
      appendResultBubble(textEl, html, true);
    } else {
      appendResultBubble(textEl, text || '', true);
    }
  } catch (e) {
    appendResultBubble(textEl, text || '', true);
  }
  cardEl.style.display = 'block';
  cardEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function appendResultBubble(containerEl, content, isHtml = false) {
  const bubble = document.createElement('div');
  bubble.className = 'result-bubble';
  bubble.style.animation = 'slideIn .3s ease-out';
  
  if (isHtml) {
    bubble.innerHTML = content;
  } else {
    bubble.textContent = content;
  }
  
  containerEl.appendChild(bubble);
  containerEl.scrollTop = containerEl.scrollHeight;
}

// Lightweight, safe renderer for simple Markdown-like output returned by backend.
// Supports: numbered sections, unordered lists (*,+,-), bold (**text**), links (http(s)://...)
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function inlineFormat(s) {
  if (!s) return '';
  // bold **text**
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // inline code `code`
  s = s.replace(/`([^`]+?)`/g, '<code>$1</code>');
  // links
  s = s.replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
  return s;
}

function renderRichText(input) {
  const text = input == null ? '' : String(input);
  const esc = escapeHtml(text);
  const lines = esc.split(/\r?\n/);
  let out = '';
  let inUl = false;
  let inOl = false;

  function closeLists() {
    if (inUl) { out += '</ul>'; inUl = false; }
    if (inOl) { out += '</ol>'; inOl = false; }
  }

  for (let rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      closeLists();
      out += '<p></p>';
      continue;
    }

    // numbered list item like '1. Text' or '2) Text'
    const numMatch = line.match(/^(\d+)[\.)]\s+(.+)$/);
    const ulMatch = line.match(/^[-\*\+]\s+(.+)$/);
    if (numMatch) {
      if (inUl) { out += '</ul>'; inUl = false; }
      if (!inOl) { out += '<ol>'; inOl = true; }
      out += '<li>' + inlineFormat(numMatch[2]) + '</li>';
      continue;
    }
    if (ulMatch) {
      if (inOl) { out += '</ol>'; inOl = false; }
      if (!inUl) { out += '<ul>'; inUl = true; }
      out += '<li>' + inlineFormat(ulMatch[1]) + '</li>';
      continue;
    }

    // Section heading like '1. **Title**: description' handled as paragraph but bold preserved
    const headingMatch = line.match(/^\d+\.\s+\*\*(.+?)\*\*:?(.*)$/);
    if (headingMatch) {
      closeLists();
      out += '<h3>' + inlineFormat(headingMatch[1]) + '</h3>';
      if (headingMatch[2] && headingMatch[2].trim()) out += '<p>' + inlineFormat(headingMatch[2].trim()) + '</p>';
      continue;
    }

    // Default paragraph
    closeLists();
    out += '<p>' + inlineFormat(line) + '</p>';
  }

  closeLists();
  return out;
}

// ── App ───────────────────────────────────────────────────────────────────────

const App = {

  init() {
    const has = (sel) => !!document.querySelector(sel);

    if (has('#status-dot') || has('#status-label')) this.checkStatus();
    if (has('#symptom-pills')) this.buildSymptomPills();
    if (has('#disease-tab-endemic')) this.buildDiseaseList();
    if (has('.nav-item')) this.bindNav();
    if (has('#send-btn') || has('#chat-input')) this.bindChat();
    if (has('#upload-zone') || has('#file-input')) this.bindUpload();
    if (has('.qp-btn')) this.bindQuickPrompts();
    if (has('.disease-chip')) this.bindDashboardChips();
    if (has('[data-prevention]')) this.bindPreventionChips();
    if (has('#disease-tabs')) this.bindDiseaseTabs();
  },

  // ── Status check ──────────────────────────────────────────────────────────
  async checkStatus() {
    const dot   = document.getElementById('status-dot');
    const label = document.getElementById('status-label');
    try {
      const data = await api('/api/status');
      if (data.ai_ready) {
        dot.className   = 'status-dot ok';
        label.textContent = 'AI Ready';
      } else {
        dot.className   = 'status-dot err';
        label.textContent = 'AI not configured';
      }
    } catch {
      dot.className   = 'status-dot err';
      label.textContent = 'Connection error';
    }
  },

  // ── Navigation ────────────────────────────────────────────────────────────
  bindNav() {
    const titles = {
      dashboard: 'Dashboard', symptom:  'Symptom Checker',
      consult:   'AI Consultation', rag: 'Medical Docs RAG',
      diseases:  'Nigerian Diseases', prevention: 'Prevention & Care',
    };
    document.querySelectorAll('.nav-item').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const view = btn.dataset.view;
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        document.getElementById('view-' + view).classList.add('active');
        document.getElementById('topbar-title').textContent = titles[view] || view;
      });
    });
  },

  // ── Symptom checker ───────────────────────────────────────────────────────
  buildSymptomPills() {
    const container = document.getElementById('symptom-pills');
    container.innerHTML = SYMPTOMS.map(s =>
      `<button class="symptom-pill" data-symptom="${s}">${s}</button>`
    ).join('');
    container.addEventListener('click', e => {
      const btn = e.target.closest('.symptom-pill');
      if (!btn) return;
      const name = btn.dataset.symptom;
      if (btn.classList.toggle('selected')) {
        selectedSymptoms.push(name);
      } else {
        selectedSymptoms = selectedSymptoms.filter(s => s !== name);
      }
    });
  },

  addCustomSymptom() {
    const inp = document.getElementById('custom-symptom');
    const val = inp.value.trim();
    if (!val || selectedSymptoms.includes(val)) return;
    selectedSymptoms.push(val);
    const btn = Object.assign(document.createElement('button'), {
      className: 'symptom-pill selected',
      textContent: val,
    });
    btn.dataset.symptom = val;
    document.getElementById('symptom-pills').appendChild(btn);
    inp.value = '';
  },

  async runSymptomCheck() {
    if (!selectedSymptoms.length) { alert('Please select at least one symptom.'); return; }
    const rc = document.getElementById('symptom-result');
    const rt = document.getElementById('symptom-result-text');
    rt.innerHTML = '';
    setResult(rt, rc, 'Analyzing…');
    try {
      const data = await api('/api/symptom-check', {
        symptoms: selectedSymptoms,
        age:      document.getElementById('ctx-age').value,
        gender:   document.getElementById('ctx-gender').value,
        state:    document.getElementById('ctx-state').value,
        duration: document.getElementById('ctx-duration').value,
        notes:    document.getElementById('extra-notes').value,
      });
      rt.innerHTML = '';
      setResult(rt, rc, data.result);
    } catch (e) {
      rt.innerHTML = '';
      appendResultBubble(rt, `Error: ${e.message}`, false);
    }
  },

  // ── Chat ──────────────────────────────────────────────────────────────────
  bindChat() {
    document.getElementById('send-btn').addEventListener('click', () => this.sendChat());
    document.getElementById('chat-input').addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.sendChat(); }
    });
  },

  bindQuickPrompts() {
    document.querySelectorAll('.qp-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.getElementById('chat-input').value = btn.dataset.prompt;
        this.sendChat();
      });
    });
  },

  async sendChat() {
    const input = document.getElementById('chat-input');
    const msg   = input.value.trim();
    if (!msg) return;
    input.value = '';
    this.appendMsg('user', msg);
    chatHistory.push({ role: 'user', text: msg });
    const loadId = this.appendMsg('ai', null, true);
    document.getElementById('send-btn').disabled = true;
    try {
      const data  = await api('/api/chat', { message: msg, history: chatHistory.slice(-6) });
      document.getElementById(loadId).remove();
      this.appendMsg('ai', data.result);
      chatHistory.push({ role: 'ai', text: data.result });
    } catch (e) {
      document.getElementById(loadId).remove();
      this.appendMsg('ai', `Error: ${e.message}`);
    } finally {
      document.getElementById('send-btn').disabled = false;
    }
  },

  appendMsg(role, text, loading = false) {
    const id  = 'msg-' + Date.now() + Math.random().toString(36).slice(2);
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    div.id = id;
    const content = loading
      ? '<div class="loading-dots"><span></span><span></span><span></span></div>'
      : (text || '').replace(/\n/g, '<br>');
    div.innerHTML = `
      <div class="msg-avatar">${role === 'ai' ? 'AI' : 'U'}</div>
      <div class="msg-bubble">${content}</div>`;
    const container = document.getElementById('chat-messages');
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return id;
  },

  // ── Document upload ───────────────────────────────────────────────────────
  bindUpload() {
    const zone  = document.getElementById('upload-zone');
    const input = document.getElementById('file-input');
    zone.addEventListener('click',     () => input.click());
    zone.addEventListener('dragover',  e  => { e.preventDefault(); zone.classList.add('drag'); });
    zone.addEventListener('dragleave', ()  => zone.classList.remove('drag'));
    zone.addEventListener('drop', e => {
      e.preventDefault(); zone.classList.remove('drag');
      this.uploadFiles(e.dataTransfer.files);
    });
    input.addEventListener('change', e => this.uploadFiles(e.target.files));
  },

  async uploadFiles(files) {
    for (const file of files) {
      const form = new FormData();
      form.append('file', file);
      try {
        const res  = await fetch('/api/upload-doc', { method: 'POST', body: form });
        const data = await res.json();
        if (data.success) this.addDocItem(data.name, data.size);
        else alert(data.error || 'Upload failed.');
      } catch {
        alert('Upload failed — network error.');
      }
    }
  },

  addDocItem(name, size) {
    document.getElementById('doc-list-card').style.display = 'block';
    const item = document.createElement('div');
    item.className = 'doc-item';
    item.innerHTML = `
      <span style="font-size:18px;">📄</span>
      <span class="doc-name">${name}</span>
      <span class="doc-size">${Math.round(size / 1024)} KB</span>
      <span class="doc-status">✓ Loaded</span>`;
    document.getElementById('doc-list').appendChild(item);
  },

  async queryDocs(general) {
    const query = document.getElementById('rag-query').value.trim();
    if (!query) { alert('Please enter a query.'); return; }
    const rc = document.getElementById('rag-result');
    const rt = document.getElementById('rag-result-text');
    rt.innerHTML = '';
    setResult(rt, rc, 'Searching…');
    try {
      const data = await api('/api/query-docs', { query, general });
      rt.innerHTML = '';
      setResult(rt, rc, data.result);
    } catch (e) {
      rt.innerHTML = '';
      appendResultBubble(rt, `Error: ${e.message}`, false);
    }
  },

  // ── Disease list ──────────────────────────────────────────────────────────
  buildDiseaseList() {
    const container = document.getElementById('disease-tab-endemic');
    container.innerHTML = NG_DISEASES.map(d => `
      <div class="disease-row" data-disease="${d.name}" style="display:flex;justify-content:space-between;align-items:center;padding:12px 14px;background:#fff;border:1px solid rgba(0,0,0,.08);border-radius:10px;margin-bottom:8px;cursor:pointer;">
        <div>
          <div style="font-size:14px;font-weight:500;margin-bottom:3px;">${d.name}</div>
          <div style="font-size:12px;color:#666;">${d.zone} · ${d.season}</div>
          <div style="font-size:12px;color:#666;margin-top:1px;">Vector: ${d.vector}</div>
        </div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px;">
          <span class="risk-badge risk-${d.risk}">${d.risk === 'high' ? '● High' : d.risk === 'med' ? '● Moderate' : '● Low'}</span>
          <span style="font-size:12px;color:var(--green);font-weight:500;">Get info →</span>
        </div>
      </div>`).join('');
    container.addEventListener('click', e => {
      const row = e.target.closest('[data-disease]');
      if (row) this.loadDiseaseDetail(row.dataset.disease);
    });
  },

  bindDashboardChips() {
    document.querySelectorAll('.disease-chip[data-disease]').forEach(chip => {
      chip.addEventListener('click', () => {
        document.querySelector('[data-view="diseases"]').click();
        this.loadDiseaseDetail(chip.dataset.disease);
      });
    });
  },

  astext.innerHTML = '';
    document.getElementById('disease-detail-name').textContent = name;
    setResult(text, card, `Loading information about ${name}…`);
    try {
      const data = await api('/api/disease-info', { disease: name });
      text.innerHTML = '';
      setResult(text, card, data.result);
    } catch (e) {
      text.innerHTML = '';
      appendResultBubble(text, `Error: ${e.message}`, false)o', { disease: name });
      text.textContent = data.result;
    } catch (e) {
      text.textContent = `Error: ${e.message}`;
    }
  },

  bindDiseaseTabs() {
    document.querySelectorAll('#disease-tabs .s-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#disease-tabs .s-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const tab = btn.dataset.tab;
        ['endemic','genetic','nutrition'].forEach(t => {
          document.getElementById('disease-tab-' + t).style.display = t === tab ? 'block' : 'none';
        });
        if (tab === 'genetic' && !document.getElementById('disease-tab-genetic').innerHTML)
          this.buildStaticTab('disease-tab-genetic', '🧬 Genetic Conditions — High Prevalence in Nigeria', [
            'Sickle Cell Disease (SCD) — 1 in 4 Nigerians carry the trait',
            'G6PD Deficiency — Common; triggers haemolytic crises',
            'Hereditary Persistence of Foetal Haemoglobin (HbF)',
            'Alpha & Beta Thalassaemia',
          ]);
        if (tab === 'nutrition' && !document.getElementById('disease-tab-nutrition').innerHTML)
          this.buildStaticTab('disease-tab-nutrition', '🥗 Common Nutritional Deficiencies in Nigeria', [
            'Protein-Energy Malnutrition (PEM) — Kwashiorkor & Marasmus',
            'Vitamin A Deficiency — Leading cause of preventable blindness',
            'Iron Deficiency Anaemia — Especially women & children',
            'Iodine Deficiency Disorders — Goitre in northern states',
            'Zinc Deficiency — Common in children, affects immunity',
            'Vitamin D Deficiency — Prevalent in urban populations',
          ]);
      });
    });
  },

  buildStaticTab(id, title, items) {
    const el = document.getElementById(id);
    el.innerHTML = `<div class="card"><div class="card-title">${title}</div>
      <div style="display:flex;flex-direction:column;gap:8px;">
        ${items.map(item => {
          const name = item.split(' — ')[0];
          return `<div data-disease="${name}" style="padding:10px 14px;background:var(--gray-light);border-radius:9px;font-size:13.5px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;">
            <span>${item}</span>
            <span style="font-size:12px;color:var(--green);font-weight:500;white-space:nowrap;margin-left:12px;">Get info →</span>
          </div>`;
        }).join('')}
      </div></div>`;
    el.addEventListener('click', e => {
      const row = e.target.closest('[data-disease]');
      if (row) this.loadDiseaseDetail(row.dataset.disease);
    });
  },

  // ── Prevention ────────────────────────────────────────────────────────────
  bindPreventionChips() {
    document.querySelectorAll('.disease-chip[data-prevention]').forEach(chip => {
      chip.addEventListener('click', () => this.loadPrevention(chip.dataset.prevention));
    });
  },

  async loadPrevention(topic) {
    const rc = document.getElementById('prevention-result');
    const rt = document.getElementById('prevention-result-text');
    rt.innerHTML = '';
    setResult(rt, rc, 'Loading prevention guide…');
    try {
      const data = await api('/api/prevention', { topic });
      rt.innerHTML = '';
      setResult(rt, rc, data.result);
    } catch (e) {
      rt.innerHTML = '';
      appendResultBubble(rt, `Error: ${e.message}`, false);
    }
  },
};

// ── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => App.init());
