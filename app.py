import streamlit as st
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import base64
import json
import zipfile
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import feedparser
import re
import hashlib
import html

# ==================== CONFIGURAÇÃO ====================
st.set_page_config(
    page_title="Biblioteca Tributária Pro", 
    page_icon="⚖️", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "biblioteca.db"

# APIs
try:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except:
    client = None

try:
    GMAIL_USER = st.secrets["GMAIL_USER"]
    GMAIL_APP_PASSWORD = st.secrets["GMAIL_APP_PASSWORD"]
    EMAIL_DESTINO = st.secrets["EMAIL_DESTINO"]
except:
    GMAIL_USER = GMAIL_APP_PASSWORD = EMAIL_DESTINO = None

# ==================== HTTP SESSION ROBUSTA ====================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
}

def make_session():
    s = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

SESSION = make_session()

def fetch(url, timeout=20):
    try:
        r = SESSION.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        return r, None
    except requests.exceptions.Timeout as e:
        return None, f"TIMEOUT: {str(e)}"
    except requests.exceptions.ConnectionError as e:
        return None, f"CONNECTION ERROR: {str(e)}"
    except Exception as e:
        return None, f"ERRO: {str(e)}"

def parse_rss(url, debug=False):
    """Baixa RSS usando SESSION e parseia com feedparser"""
    erros = []
    
    resp, fetch_error = fetch(url, timeout=25)
    
    if fetch_error:
        return None, [f"❌ FALHOU: {fetch_error}"]
    
    if not resp:
        return None, ["❌ FALHOU: sem resposta"]
    
    if debug:
        erros.append(f"📍 URL: {url}")
        erros.append(f"📊 HTTP Status: {resp.status_code}")
        erros.append(f"🔄 Final URL: {resp.url}")
        content_type = resp.headers.get('Content-Type', 'N/A')
        erros.append(f"📄 Content-Type: {content_type}")
        erros.append(f"📦 Bytes: {len(resp.content)}")
        
        # Detectar página de bloqueio
        if 'html' in content_type.lower() and 'xml' not in content_type.lower():
            erros.append("⚠️ Content-Type suspeito (pode ser bloqueio)")
            if resp.content:
                snippet = resp.text[:300].replace("\n", " ").replace("<", "&lt;")
                erros.append(f"🧩 Snippet: {snippet}")
    
    if resp.status_code != 200:
        erros.append(f"❌ HTTP != 200 ({resp.status_code})")
        return None, erros
    
    d = feedparser.parse(resp.content)
    
    if debug:
        bozo = getattr(d, "bozo", False)
        if bozo:
            erros.append(f"⚠️ BOZO: {getattr(d, 'bozo_exception', 'erro de parse')}")
        erros.append(f"✅ Entries: {len(d.entries)}")
        if d.entries:
            erros.append(f"📋 Exemplo: {d.entries[0].get('title', 'N/A')[:60]}...")
    
    return d, erros

def normalize_date(entry):
    """Normaliza data do feed para YYYY-MM-DD (corrigido)"""
    # Primeiro tenta parsed do feedparser
    dt_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if dt_struct:
        try:
            return datetime(*dt_struct[:6]).strftime("%Y-%m-%d")
        except:
            pass
    
    # Fallback: texto raw
    txt = (entry.get("published") or entry.get("updated") or "").strip()
    if not txt:
        return ""
    
    # Normaliza ISO com Z
    iso_txt = txt.replace("Z", "+00:00")
    
    # Formatos comuns
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",     # RFC822
        "%a, %d %b %Y %H:%M:%S %Z",     # RFC822 com timezone nome
        "%a, %d %b %Y %H:%M:%S",        # RFC822 sem tz
        "%Y-%m-%dT%H:%M:%S%z",          # ISO com tz
        "%Y-%m-%dT%H:%M:%S",            # ISO sem tz
        "%Y-%m-%d %H:%M:%S",            # datetime simples
        "%Y-%m-%d",                     # data simples
        "%d/%m/%Y %H:%M:%S",            # BR com hora
        "%d/%m/%Y",                     # BR
    ]
    
    for candidate in (txt, iso_txt):
        for fmt in fmts:
            try:
                return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
            except:
                continue
    
    # Último recurso: extrai YYYY-MM-DD se existir
    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', txt)
    if match:
        return match.group(0)
    
    return txt[:10] if len(txt) >= 10 else txt

def gerar_hash(texto):
    return hashlib.md5(texto.encode()).hexdigest()[:16]

# ==================== CSS ====================
st.markdown("""
<style>
:root {
    --primary: #0f172a;
    --secondary: #1e293b;
    --accent: #3b82f6;
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
    border-right: 1px solid #334155;
}

.logo-container {
    text-align: center;
    padding: 1.5rem 1rem;
    border-bottom: 1px solid #334155;
    margin-bottom: 1rem;
}

.logo-text {
    font-size: 1.4rem;
    font-weight: 700;
    background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.logo-subtitle {
    font-size: 0.7rem;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}

.stat-card {
    background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%);
    border: 1px solid #334155;
    border-radius: 1rem;
    padding: 1.25rem;
    text-align: center;
    margin-bottom: 0.5rem;
}

.stat-value {
    font-size: 2rem;
    font-weight: 700;
    background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.stat-label {
    font-size: 0.75rem;
    color: #64748b;
    text-transform: uppercase;
}

.search-result {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 0.75rem;
    padding: 1.25rem;
    margin-bottom: 0.75rem;
    transition: all 0.2s ease;
}

.search-result:hover {
    border-color: #3b82f6;
    transform: translateX(4px);
}

.result-title {
    font-size: 0.95rem;
    font-weight: 600;
    color: #f8fafc;
    margin-bottom: 0.5rem;
}

.result-meta {
    font-size: 0.8rem;
    color: #64748b;
    margin-bottom: 0.5rem;
}

.result-description {
    font-size: 0.85rem;
    color: #94a3b8;
    margin-bottom: 0.75rem;
}

.card-badge {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: 9999px;
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    margin-right: 0.5rem;
}

.badge-federal { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
.badge-estadual { background: rgba(16, 185, 129, 0.2); color: #34d399; }
.badge-icms { background: rgba(59, 130, 246, 0.2); color: #60a5fa; }
.badge-rss { background: rgba(139, 92, 246, 0.2); color: #a78bfa; }
.badge-news { background: rgba(236, 72, 153, 0.2); color: #f472b6; }

.user-msg {
    background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
    color: white;
    padding: 1rem 1.25rem;
    border-radius: 1rem 1rem 0.25rem 1rem;
    margin: 0.75rem 0 0.75rem 20%;
    font-size: 0.9rem;
}

.assistant-msg {
    background: #1e293b;
    color: #f8fafc;
    padding: 1rem 1.25rem;
    border-radius: 1rem 1rem 1rem 0.25rem;
    margin: 0.75rem 20% 0.75rem 0;
    border: 1px solid #334155;
    font-size: 0.9rem;
}

.debug-log {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 0.5rem;
    padding: 0.5rem 0.75rem;
    margin: 0.25rem 0;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 0.75rem;
    color: #94a3b8;
    overflow-x: auto;
}

.debug-log.success { border-left: 3px solid #10b981; }
.debug-log.warning { border-left: 3px solid #f59e0b; }
.debug-log.error { border-left: 3px solid #ef4444; }

.debug-section {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 0.75rem;
    padding: 1rem;
    margin: 1rem 0;
}

.debug-section h4 {
    color: #f8fafc;
    margin: 0 0 0.75rem 0;
    font-size: 0.9rem;
}

#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #0f172a; }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)

# ==================== DATABASE ====================
def get_conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        nome TEXT NOT NULL, cnpj TEXT, observacoes TEXT, 
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS estudos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        cliente_id INTEGER NOT NULL, titulo TEXT NOT NULL, resumo TEXT NOT NULL, 
        tags TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS anexos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        estudo_id INTEGER NOT NULL, filename TEXT NOT NULL, 
        file_type TEXT NOT NULL, file_data TEXT NOT NULL, 
        file_size INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS chat_historico (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        role TEXT NOT NULL, content TEXT NOT NULL, 
        fontes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS atualizacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        hash_id TEXT UNIQUE, fonte TEXT NOT NULL, tipo TEXT, 
        titulo TEXT NOT NULL, resumo TEXT, link TEXT, 
        data_pub TEXT, oficial INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

init_db()

# ==================== SCRAPERS RSS ====================

def scrape_planalto_rss(debug=False):
    """RSS oficial do Portal da Legislação"""
    resultados = []
    feed_url = "https://www.planalto.gov.br/legislacao/rss"
    
    d, erros = parse_rss(feed_url, debug=debug)
    if not d:
        return [], erros
    
    for entry in d.entries[:50]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        summary = entry.get("summary", "") or entry.get("description", "")
        
        if not title or not link:
            continue
        
        tipo = "Legislação Federal"
        tupper = title.upper()
        if "LEI COMPLEMENTAR" in tupper:
            tipo = "Lei Complementar"
        elif "LEI" in tupper:
            tipo = "Lei Federal"
        elif "DECRETO" in tupper:
            tipo = "Decreto Federal"
        elif "MEDIDA PROVISÓRIA" in tupper or "MP " in tupper:
            tipo = "Medida Provisória"
        elif "EMENDA" in tupper:
            tipo = "Emenda Constitucional"
        elif "PORTARIA" in tupper:
            tipo = "Portaria"
        
        resultados.append({
            "fonte": "Planalto",
            "tipo": tipo,
            "titulo": title[:300],
            "resumo": summary[:500] if summary else "Legislação federal",
            "link": link,
            "data_pub": normalize_date(entry),
            "oficial": 1
        })
    
    if debug:
        erros.append(f"🎯 Processados: {len(resultados)} itens")
    
    return resultados[:40], erros

def scrape_confaz_rss(query="icms", debug=False):
    """RSS de busca do CONFAZ"""
    resultados = []
    feed_url = f"https://www.confaz.fazenda.gov.br/search_rss?SearchableText={query}&sort_on=Date&sort_order=reverse"
    
    d, erros = parse_rss(feed_url, debug=debug)
    if not d:
        return [], erros
    
    for entry in d.entries[:60]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        summary = entry.get("summary", "") or entry.get("description", "")
        
        if not title or not link:
            continue
        
        tipo = "CONFAZ"
        tupper = title.upper()
        if "CONVÊNIO" in tupper or "CONVENIO" in tupper:
            tipo = "Convênio ICMS"
        elif "AJUSTE" in tupper:
            tipo = "Ajuste SINIEF"
        elif "PROTOCOLO" in tupper:
            tipo = "Protocolo ICMS"
        elif "ATO COTEPE" in tupper:
            tipo = "Ato COTEPE"
        elif "DESPACHO" in tupper:
            tipo = "Despacho CONFAZ"
        
        resultados.append({
            "fonte": "CONFAZ",
            "tipo": tipo,
            "titulo": title[:300],
            "resumo": summary[:500] if summary else "Ato normativo CONFAZ",
            "link": link,
            "data_pub": normalize_date(entry),
            "oficial": 1
        })
    
    if debug:
        erros.append(f"🎯 Processados: {len(resultados)} itens")
    
    return resultados[:40], erros

def scrape_receita_federal_rss(debug=False):
    """RSS oficial da Receita Federal"""
    resultados = []
    all_erros = []
    
    feeds = [
        ("https://www.gov.br/receitafederal/pt-br/assuntos/noticias/RSS", "Notícias RFB"),
    ]
    
    for feed_url, feed_name in feeds:
        if debug:
            all_erros.append(f"--- {feed_name} ---")
        
        d, erros = parse_rss(feed_url, debug=debug)
        all_erros.extend(erros)
        
        if not d:
            continue
        
        for entry in d.entries[:25]:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            summary = entry.get("summary", "") or entry.get("description", "")
            
            if not title or not link:
                continue
            
            tipo = "Receita Federal"
            tupper = title.upper()
            if "INSTRUÇÃO NORMATIVA" in tupper or "IN RFB" in tupper:
                tipo = "Instrução Normativa"
            elif "PORTARIA" in tupper:
                tipo = "Portaria RFB"
            elif "SOLUÇÃO DE CONSULTA" in tupper:
                tipo = "Solução de Consulta"
            
            resultados.append({
                "fonte": "Receita Federal",
                "tipo": tipo,
                "titulo": title[:300],
                "resumo": summary[:500] if summary else "Publicação RFB",
                "link": link,
                "data_pub": normalize_date(entry),
                "oficial": 1
            })
    
    if debug:
        all_erros.append(f"�� Processados: {len(resultados)} itens")
    
    return resultados[:30], all_erros

def scrape_dou_rss(debug=False):
    """RSS do Diário Oficial - Seção 1 filtrado"""
    resultados = []
    
    # URL com filtro de seção (mais relevante e menor volume)
    feed_url = "https://www.in.gov.br/rss/home?jornal=515&secao=1"
    
    d, erros = parse_rss(feed_url, debug=debug)
    if not d:
        return [], erros
    
    keywords = ['TRIBUT', 'ICMS', 'IPI', 'PIS', 'COFINS', 'IMPOSTO', 'FISCAL', 
                'RECEITA', 'FAZENDA', 'CONTRIBUI', 'ADUANEIR', 'ALFANDEG', 'CARF']
    
    for entry in d.entries[:100]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        summary = entry.get("summary", "") or ""
        
        if not title:
            continue
        
        tupper = title.upper()
        if any(t in tupper for t in keywords):
            resultados.append({
                "fonte": "Diário Oficial",
                "tipo": "DOU Seção 1",
                "titulo": title[:300],
                "resumo": summary[:500] if summary else "Publicação DOU",
                "link": link,
                "data_pub": normalize_date(entry),
                "oficial": 1
            })
    
    if debug:
        erros.append(f"🎯 Tributários: {len(resultados)} de {len(d.entries)} no feed")
    
    return resultados[:25], erros

# ==================== SCRAPERS HTML ====================

def scrape_sefaz_sc_html(debug=False):
    resultados, erros = [], []
    url = "http://legislacao.sef.sc.gov.br/Consulta/Views/Publico/Frame.aspx?x=/Cabecalhos/frame_decretos_702702702.htm"
    
    if debug:
        erros.append(f"📍 URL: {url}")
    
    resp, fetch_error = fetch(url, timeout=15)
    if fetch_error:
        return [], [f"❌ {fetch_error}"]
    
    if debug:
        erros.append(f"📊 HTTP: {resp.status_code if resp else 'N/A'}")
    
    if resp and resp.status_code == 200:
        soup = BeautifulSoup(resp.content, 'html.parser')
        for link in soup.find_all('a', href=True)[:30]:
            texto = link.get_text(strip=True)
            href = link['href']
            if re.search(r'(decreto|ato|portaria)', texto.lower()) or re.search(r'\d{3,}', texto):
                if len(texto) > 5:
                    full_link = href if href.startswith('http') else f"http://legislacao.sef.sc.gov.br{href}"
                    resultados.append({
                        "fonte": "SEFAZ SC", "tipo": "Decreto SC",
                        "titulo": texto[:300], "resumo": "Legislação SC",
                        "link": full_link, "data_pub": "", "oficial": 1
                    })
        if debug:
            erros.append(f"🎯 Total: {len(resultados)}")
    return resultados[:25], erros

def scrape_sefaz_es_html(debug=False):
    resultados, erros = [], []
    url = "https://internet.sefaz.es.gov.br/legislacao/"
    
    if debug:
        erros.append(f"📍 URL: {url}")
    
    resp, fetch_error = fetch(url, timeout=15)
    if fetch_error:
        return [], [f"❌ {fetch_error}"]
    
    if debug:
        erros.append(f"📊 HTTP: {resp.status_code if resp else 'N/A'}")
    
    if resp and resp.status_code == 200:
        soup = BeautifulSoup(resp.content, 'html.parser')
        for link in soup.find_all('a', href=True)[:30]:
            texto = link.get_text(strip=True)
            href = link['href']
            if any(t in texto.upper() for t in ['DECRETO', 'LEI', 'PORTARIA', 'RICMS']):
                if len(texto) > 10:
                    full_link = href if href.startswith('http') else f"https://internet.sefaz.es.gov.br{href}"
                    resultados.append({
                        "fonte": "SEFAZ ES", "tipo": "Legislação ES",
                        "titulo": texto[:300], "resumo": "Legislação ES",
                        "link": full_link, "data_pub": "", "oficial": 1
                    })
        if debug:
            erros.append(f"🎯 Total: {len(resultados)}")
    return resultados[:20], erros

def scrape_portal_contabeis(debug=False):
    resultados, erros = [], []
    url = "https://www.contabeis.com.br/noticias/tributario/"
    
    if debug:
        erros.append(f"📍 URL: {url}")
    
    resp, fetch_error = fetch(url, timeout=15)
    if fetch_error:
        return [], [f"❌ {fetch_error}"]
    
    if debug:
        erros.append(f"📊 HTTP: {resp.status_code if resp else 'N/A'}")
    
    if resp and resp.status_code == 200:
        soup = BeautifulSoup(resp.content, 'html.parser')
        for article in soup.find_all(['article', 'div'], class_=re.compile(r'noticia|news|article|card'))[:20]:
            titulo_elem = article.find(['h2', 'h3', 'h4', 'a'])
            if titulo_elem:
                titulo = titulo_elem.get_text(strip=True)
                link_elem = article.find('a', href=True)
                link = link_elem['href'] if link_elem else ""
                if 25 < len(titulo) < 300:
                    resultados.append({
                        "fonte": "Portal Contábeis", "tipo": "Notícia",
                        "titulo": titulo[:300], "resumo": "Notícia tributária (não oficial)",
                        "link": link if link.startswith('http') else f"https://www.contabeis.com.br{link}",
                        "data_pub": datetime.now().strftime('%Y-%m-%d'), "oficial": 0
                    })
        if debug:
            erros.append(f"🎯 Total: {len(resultados)}")
    return resultados[:15], erros

def scrape_jota_tributario(debug=False):
    resultados, erros = [], []
    url = "https://www.jota.info/tributos-e-empresas"
    
    if debug:
        erros.append(f"📍 URL: {url}")
    
    resp, fetch_error = fetch(url, timeout=15)
    if fetch_error:
        return [], [f"❌ {fetch_error}"]
    
    if debug:
        erros.append(f"📊 HTTP: {resp.status_code if resp else 'N/A'}")
    
    if resp and resp.status_code == 200:
        soup = BeautifulSoup(resp.content, 'html.parser')
        for link in soup.find_all('a', href=True)[:50]:
            texto = link.get_text(strip=True)
            href = link['href']
            if any(t in texto.lower() for t in ['tribut', 'icms', 'imposto', 'fiscal', 'stf', 'carf']):
                if 30 < len(texto) < 200:
                    resultados.append({
                        "fonte": "JOTA", "tipo": "Análise",
                        "titulo": texto[:300], "resumo": "Análise jurídica (não oficial)",
                        "link": href if href.startswith('http') else f"https://www.jota.info{href}",
                        "data_pub": datetime.now().strftime('%Y-%m-%d'), "oficial": 0
                    })
        if debug:
            erros.append(f"🎯 Total: {len(resultados)}")
    return resultados[:15], erros

# ==================== MAPEAMENTO ====================

FONTES_CONFIG = {
    "Planalto (RSS)": {"fn": scrape_planalto_rss, "tipo": "rss", "oficial": True},
    "CONFAZ (RSS)": {"fn": lambda d=False: scrape_confaz_rss("icms", d), "tipo": "rss", "oficial": True},
    "Receita Federal (RSS)": {"fn": scrape_receita_federal_rss, "tipo": "rss", "oficial": True},
    "Diário Oficial (RSS)": {"fn": scrape_dou_rss, "tipo": "rss", "oficial": True},
    "SEFAZ SC": {"fn": scrape_sefaz_sc_html, "tipo": "html", "oficial": True},
    "SEFAZ ES": {"fn": scrape_sefaz_es_html, "tipo": "html", "oficial": True},
    "Portal Contábeis": {"fn": scrape_portal_contabeis, "tipo": "html", "oficial": False},
    "JOTA Tributos": {"fn": scrape_jota_tributario, "tipo": "html", "oficial": False},
}

def buscar_todas_fontes(fontes_selecionadas, debug=False):
    todos, logs = [], []
    
    for fonte in fontes_selecionadas:
        if fonte in FONTES_CONFIG:
            config = FONTES_CONFIG[fonte]
            logs.append(f"🔍 {fonte} ({config['tipo'].upper()})")
            
            try:
                resultados, erros = config["fn"](debug)
                todos.extend(resultados)
                logs.append(f"✅ {len(resultados)} itens")
                if debug:
                    logs.extend(erros)
            except Exception as e:
                logs.append(f"❌ Erro: {str(e)}")
            
            logs.append("")  # linha em branco
    
    return todos, logs

@st.cache_data(ttl=900)
def cached_buscar(fontes_tuple, debug=False):
    return buscar_todas_fontes(list(fontes_tuple), debug=debug)

def salvar_atualizacoes(atualizacoes):
    conn = get_conn()
    c = conn.cursor()
    novos = 0
    
    for att in atualizacoes:
        titulo = att.get("titulo", "").strip()[:500]
        if not titulo:
            continue
        
        # Hash melhorado: link + título + fonte
        hash_base = f"{att.get('link', '')}|{titulo}|{att.get('fonte', '')}"
        hash_id = gerar_hash(hash_base)
        
        c.execute("SELECT id FROM atualizacoes WHERE hash_id = ?", (hash_id,))
        if not c.fetchone():
            c.execute("""
                INSERT INTO atualizacoes (hash_id, fonte, tipo, titulo, resumo, link, data_pub, oficial) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (hash_id, att.get("fonte", ""), att.get("tipo", ""), titulo,
                  att.get("resumo", "")[:1000], att.get("link", ""), att.get("data_pub", ""), att.get("oficial", 1)))
            novos += 1
    
    conn.commit()
    conn.close()
    return novos

def obter_atualizacoes(filtro_oficial=None, limite=100):
    conn = get_conn()
    c = conn.cursor()
    
    # Ordenação robusta: data vazia vai pro final
    if filtro_oficial is not None:
        c.execute("""
            SELECT * FROM atualizacoes WHERE oficial = ?
            ORDER BY (CASE WHEN data_pub='' OR data_pub IS NULL THEN '0000-00-00' ELSE data_pub END) DESC,
                     created_at DESC LIMIT ?
        """, (filtro_oficial, limite))
    else:
        c.execute("""
            SELECT * FROM atualizacoes
            ORDER BY (CASE WHEN data_pub='' OR data_pub IS NULL THEN '0000-00-00' ELSE data_pub END) DESC,
                     created_at DESC LIMIT ?
        """, (limite,))
    
    r = [dict(row) for row in c.fetchall()]
    conn.close()
    return r

def limpar_atualizacoes():
    conn = get_conn()
    conn.cursor().execute("DELETE FROM atualizacoes")
    conn.commit()
    conn.close()

# ==================== IA CONSULTOR ====================

def buscar_biblioteca(pergunta):
    conn = get_conn()
    c = conn.cursor()
    palavras = [p.lower() for p in pergunta.split() if len(p) > 3]
    res, ids = [], set()
    for p in palavras:
        c.execute("""SELECT e.id, e.titulo, e.resumo, e.tags, c.nome as cliente 
            FROM estudos e JOIN clientes c ON e.cliente_id=c.id 
            WHERE LOWER(e.titulo) LIKE ? OR LOWER(e.resumo) LIKE ? LIMIT 5
        """, (f"%{p}%", f"%{p}%"))
        for r in c.fetchall():
            if r['id'] not in ids:
                res.append(dict(r))
                ids.add(r['id'])
    conn.close()
    return res[:5]

def buscar_atualizacoes_rel(pergunta):
    conn = get_conn()
    c = conn.cursor()
    palavras = [p.lower() for p in pergunta.split() if len(p) > 3]
    res = []
    for p in palavras[:3]:
        c.execute("SELECT titulo, link, fonte FROM atualizacoes WHERE LOWER(titulo) LIKE ? LIMIT 3", (f"%{p}%",))
        for r in c.fetchall():
            if dict(r) not in res:
                res.append(dict(r))
    conn.close()
    return res[:5]

def consultar_ia(pergunta, historico):
    if not client:
        return "❌ API OpenAI não configurada.", [], []
    
    materiais = buscar_biblioteca(pergunta)
    atualizacoes = buscar_atualizacoes_rel(pergunta)
    
    ctx = ""
    if materiais:
        ctx += "\n\n📚 BIBLIOTECA:\n" + "\n".join([f"- {m['titulo']}" for m in materiais])
    if atualizacoes:
        ctx += "\n\n📰 LEGISLAÇÃO:\n" + "\n".join([f"- {a['titulo']} ({a['fonte']})" for a in atualizacoes])
    
    try:
        msgs = [
            {"role": "system", "content": f"Você é um consultor tributário brasileiro. Responda de forma clara e profissional.{ctx}"},
            *[{"role": m["role"], "content": m["content"]} for m in historico[-6:]],
            {"role": "user", "content": pergunta}
        ]
        r = client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=2500, temperature=0.3)
        return r.choices[0].message.content, materiais, atualizacoes
    except Exception as e:
        return f"❌ Erro: {str(e)}", [], []

def salvar_msg(role, content, fontes=None):
    conn = get_conn()
    conn.cursor().execute("INSERT INTO chat_historico (role, content, fontes) VALUES (?, ?, ?)", 
                         (role, content, json.dumps(fontes) if fontes else None))
    conn.commit()
    conn.close()

def obter_historico():
    conn = get_conn()
    h = [{"role": r["role"], "content": r["content"]} 
         for r in conn.cursor().execute("SELECT role, content FROM chat_historico ORDER BY created_at ASC").fetchall()]
    conn.close()
    return h

def limpar_chat():
    conn = get_conn()
    conn.cursor().execute("DELETE FROM chat_historico")
    conn.commit()
    conn.close()

# ==================== EMAIL ====================

def enviar_email(atualizacoes, periodo=""):
    if not GMAIL_USER or not EMAIL_DESTINO:
        return False, "Email não configurado"
    
    h = f"""<!DOCTYPE html><html><head><style>
        body {{ font-family: Arial; background: #f1f5f9; padding: 20px; }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #1e293b, #334155); color: white; padding: 25px; border-radius: 12px 12px 0 0; }}
        .content {{ background: white; padding: 25px; border-radius: 0 0 12px 12px; }}
        .item {{ border-left: 3px solid #3b82f6; padding: 12px; margin: 10px 0; background: #f8fafc; }}
        .item h3 {{ margin: 0 0 5px; font-size: 14px; }}
        .item a {{ color: #3b82f6; font-size: 12px; }}
    </style></head><body><div class="container">
    <div class="header"><h1>⚖️ Biblioteca Tributária Pro</h1><p>{periodo}</p></div><div class="content">"""
    
    for fonte, lista in {}.items() or [(a.get('fonte',''), [a]) for a in atualizacoes]:
        pass
    
    por_fonte = {}
    for a in atualizacoes:
        por_fonte.setdefault(a.get('fonte', 'Outros'), []).append(a)
    
    for fonte, lista in por_fonte.items():
        h += f'<h2>{fonte}</h2>'
        for a in lista[:15]:
            h += f'<div class="item"><h3>{a.get("titulo", "")[:150]}</h3><p>📅 {a.get("data_pub", "")[:10]}</p><a href="{a.get("link", "#")}">🔗 Acessar</a></div>'
    
    h += '</div></div></body></html>'
    
    try:
        msg = MIMEMultipart()
        msg['Subject'] = f"⚖️ Atualizações - {periodo}"
        msg['From'] = GMAIL_USER
        msg['To'] = EMAIL_DESTINO
        msg.attach(MIMEText(h, 'html'))
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, EMAIL_DESTINO, msg.as_string())
        server.quit()
        return True, f"Enviado para {EMAIL_DESTINO}"
    except Exception as e:
        return False, str(e)

# ==================== CRUD ====================

def criar_cliente(nome, cnpj=None, obs=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO clientes (nome, cnpj, observacoes) VALUES (?, ?, ?)", (nome, cnpj, obs))
    conn.commit()
    id = c.lastrowid
    conn.close()
    return id

def listar_clientes():
    conn = get_conn()
    r = list(conn.cursor().execute("SELECT * FROM clientes ORDER BY nome").fetchall())
    conn.close()
    return r

def obter_cliente(id):
    conn = get_conn()
    r = conn.cursor().execute("SELECT * FROM clientes WHERE id=?", (id,)).fetchone()
    conn.close()
    return r

def excluir_cliente(id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM anexos WHERE estudo_id IN (SELECT id FROM estudos WHERE cliente_id=?)", (id,))
    c.execute("DELETE FROM estudos WHERE cliente_id=?", (id,))
    c.execute("DELETE FROM clientes WHERE id=?", (id,))
    conn.commit()
    conn.close()

def criar_estudo(cid, titulo, resumo, tags=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO estudos (cliente_id, titulo, resumo, tags) VALUES (?, ?, ?, ?)", (cid, titulo, resumo, tags))
    conn.commit()
    id = c.lastrowid
    conn.close()
    return id

def listar_estudos(cid=None):
    conn = get_conn()
    if cid:
        r = list(conn.cursor().execute("SELECT * FROM estudos WHERE cliente_id=? ORDER BY created_at DESC", (cid,)).fetchall())
    else:
        r = list(conn.cursor().execute("SELECT e.*, c.nome as cliente FROM estudos e JOIN clientes c ON e.cliente_id=c.id ORDER BY e.created_at DESC").fetchall())
    conn.close()
    return r

def obter_estudo(id):
    conn = get_conn()
    r = conn.cursor().execute("SELECT * FROM estudos WHERE id=?", (id,)).fetchone()
    conn.close()
    return r

def atualizar_estudo(id, titulo, resumo, tags):
    conn = get_conn()
    conn.cursor().execute("UPDATE estudos SET titulo=?, resumo=?, tags=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (titulo, resumo, tags, id))
    conn.commit()
    conn.close()

def excluir_estudo(id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM anexos WHERE estudo_id=?", (id,))
    c.execute("DELETE FROM estudos WHERE id=?", (id,))
    conn.commit()
    conn.close()

def add_anexo(eid, nome, tipo, dados, tam):
    conn = get_conn()
    conn.cursor().execute("INSERT INTO anexos (estudo_id, filename, file_type, file_data, file_size) VALUES (?, ?, ?, ?, ?)", 
                         (eid, nome, tipo, base64.b64encode(dados).decode(), tam))
    conn.commit()
    conn.close()

def listar_anexos(eid):
    conn = get_conn()
    r = list(conn.cursor().execute("SELECT id, filename, file_type, file_size FROM anexos WHERE estudo_id=?", (eid,)).fetchall())
    conn.close()
    return r

def obter_anexo(id):
    conn = get_conn()
    r = conn.cursor().execute("SELECT * FROM anexos WHERE id=?", (id,)).fetchone()
    conn.close()
    return r

def excluir_anexo(id):
    conn = get_conn()
    conn.cursor().execute("DELETE FROM anexos WHERE id=?", (id,))
    conn.commit()
    conn.close()

def stats():
    conn = get_conn()
    c = conn.cursor()
    s = {
        'clientes': c.execute("SELECT COUNT(*) FROM clientes").fetchone()[0],
        'estudos': c.execute("SELECT COUNT(*) FROM estudos").fetchone()[0],
        'anexos': c.execute("SELECT COUNT(*) FROM anexos").fetchone()[0],
        'atualizacoes': c.execute("SELECT COUNT(*) FROM atualizacoes").fetchone()[0],
        'oficiais': c.execute("SELECT COUNT(*) FROM atualizacoes WHERE oficial=1").fetchone()[0],
        'consultas': c.execute("SELECT COUNT(*) FROM chat_historico WHERE role='user'").fetchone()[0],
    }
    conn.close()
    return s

def backup():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        conn = get_conn()
        data = {"versao": "6.2", "data": datetime.now().isoformat()}
        for t in ["clientes", "estudos", "anexos", "chat_historico", "atualizacoes"]:
            data[t] = [dict(r) for r in conn.cursor().execute(f"SELECT * FROM {t}").fetchall()]
        conn.close()
        zf.writestr("backup.json", json.dumps(data, ensure_ascii=False, indent=2))
    buf.seek(0)
    return buf

def restaurar(file):
    try:
        content = file.read()
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                data = json.loads(zf.read("backup.json"))
        except:
            data = json.loads(content)
        
        conn = get_conn()
        c = conn.cursor()
        for t in ["anexos", "estudos", "clientes", "chat_historico", "atualizacoes"]:
            c.execute(f"DELETE FROM {t}")
        
        for cl in data.get("clientes", []):
            c.execute("INSERT INTO clientes (id,nome,cnpj,observacoes,created_at) VALUES (?,?,?,?,?)", 
                     (cl['id'], cl['nome'], cl.get('cnpj'), cl.get('observacoes'), cl.get('created_at')))
        for e in data.get("estudos", []):
            c.execute("INSERT INTO estudos (id,cliente_id,titulo,resumo,tags,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", 
                     (e['id'], e['cliente_id'], e['titulo'], e['resumo'], e.get('tags'), e.get('created_at'), e.get('updated_at')))
        for a in data.get("anexos", []):
            c.execute("INSERT INTO anexos (id,estudo_id,filename,file_type,file_data,file_size,created_at) VALUES (?,?,?,?,?,?,?)", 
                     (a['id'], a['estudo_id'], a['filename'], a['file_type'], a['file_data'], a.get('file_size'), a.get('created_at')))
        for ch in data.get("chat_historico", []):
            c.execute("INSERT INTO chat_historico (id,role,content,fontes,created_at) VALUES (?,?,?,?,?)", 
                     (ch['id'], ch['role'], ch['content'], ch.get('fontes'), ch.get('created_at')))
        for at in data.get("atualizacoes", []):
            c.execute("INSERT INTO atualizacoes (id,hash_id,fonte,tipo,titulo,resumo,link,data_pub,oficial,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", 
                     (at['id'], at.get('hash_id'), at.get('fonte'), at.get('tipo'), at['titulo'], at.get('resumo'), 
                      at.get('link'), at.get('data_pub'), at.get('oficial', 1), at.get('created_at')))
        
        conn.commit()
        conn.close()
        return True, "Restaurado!"
    except Exception as e:
        return False, str(e)

# ==================== ESTADO ====================

if "pagina" not in st.session_state:
    st.session_state.pagina = "dashboard"
if "cliente_id" not in st.session_state:
    st.session_state.cliente_id = None
if "estudo_id" not in st.session_state:
    st.session_state.estudo_id = None
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False
if "show_hist" not in st.session_state:
    st.session_state.show_hist = False

def navegar(p, c=None, e=None):
    st.session_state.pagina = p
    st.session_state.cliente_id = c
    st.session_state.estudo_id = e
    st.session_state.edit_mode = False

# ==================== SIDEBAR ====================

with st.sidebar:
    st.markdown("""<div class="logo-container">
        <p class="logo-text">⚖️ Biblioteca Tributária</p>
        <p class="logo-subtitle">Professional v6.2</p>
    </div>""", unsafe_allow_html=True)
    
    for icon, label, page in [
        ("📊", "Dashboard", "dashboard"),
        ("🤖", "Consultor IA", "consultor"),
        ("📡", "Atualizações", "atualizacoes"),
        ("📚", "Biblioteca", "biblioteca"),
        ("👥", "Clientes", "clientes"),
        ("➕", "Novo Cadastro", "novo"),
        ("⚙️", "Configurações", "config"),
    ]:
        if st.button(f"{icon}  {label}", key=f"nav_{page}", use_container_width=True,
                    type="primary" if st.session_state.pagina == page else "secondary"):
            navegar(page)
            st.rerun()
    
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        st.success("IA ✓") if client else st.error("IA ✗")
    with col2:
        st.success("Email ✓") if GMAIL_USER else st.error("Email ✗")
    st.caption("© 2025 MP Solutions")

# ==================== PÁGINAS ====================

if st.session_state.pagina == "dashboard":
    st.markdown("## 📊 Dashboard")
    
    s = stats()
    cols = st.columns(6)
    for col, (icon, label, value) in zip(cols, [
        ("👥", "Clientes", s['clientes']), ("📚", "Estudos", s['estudos']),
        ("📎", "Anexos", s['anexos']), ("📡", "Total", s['atualizacoes']),
        ("✅", "Oficiais", s['oficiais']), ("💬", "Consultas", s['consultas']),
    ]):
        with col:
            st.markdown(f'<div class="stat-card"><div class="stat-value">{value}</div><div class="stat-label">{icon} {label}</div></div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 📰 Últimas Atualizações")
        for att in obter_atualizacoes(limite=5):
            st.markdown(f'<div class="search-result"><span class="card-badge badge-{"federal" if att.get("oficial") else "news"}">{att.get("fonte", "")}</span><div class="result-title">{att.get("titulo", "")[:80]}...</div><div class="result-meta">📅 {att.get("data_pub", "")[:10]}</div></div>', unsafe_allow_html=True)
    
    with col2:
        st.markdown("### 📚 Estudos Recentes")
        for est in listar_estudos()[:5]:
            est = dict(est)
            st.markdown(f'<div class="search-result"><span class="card-badge badge-estadual">{est.get("cliente", "")}</span><div class="result-title">{est["titulo"][:60]}...</div></div>', unsafe_allow_html=True)

elif st.session_state.pagina == "consultor":
    st.markdown("## 🤖 Consultor Tributário IA")
    
    with st.form("chat", clear_on_submit=True):
        pergunta = st.text_area("Sua pergunta:", height=100, placeholder="Ex: Prazo de ICMS-ST em SC?")
        col1, col2 = st.columns([4, 1])
        with col1:
            enviar = st.form_submit_button("🔍 Consultar", use_container_width=True, type="primary")
        with col2:
            limpar = st.form_submit_button("🗑️", use_container_width=True)
    
    if st.button("📜 Ver Histórico"):
        st.session_state.show_hist = not st.session_state.show_hist
    
    if limpar:
        limpar_chat()
        st.rerun()
    
    if enviar and pergunta.strip():
        salvar_msg("user", pergunta)
        with st.spinner("Consultando..."):
            resp, _, _ = consultar_ia(pergunta, obter_historico()[:-1])
            salvar_msg("assistant", resp)
        st.rerun()
    
    hist = obter_historico()
    for msg in (hist if st.session_state.show_hist else hist[-6:]):
        cls = "user-msg" if msg["role"] == "user" else "assistant-msg"
        icon = "🧑‍💼" if msg["role"] == "user" else "🤖"
        st.markdown(f'<div class="{cls}">{icon} {msg["content"]}</div>', unsafe_allow_html=True)

elif st.session_state.pagina == "atualizacoes":
    st.markdown("## 📡 Central de Atualizações")
    
    debug_mode = st.checkbox("🛠️ Modo Debug", value=False)
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("##### ✅ Oficiais (RSS)")
        sel_of = st.multiselect("", [k for k, v in FONTES_CONFIG.items() if v['oficial']],
            default=["Planalto (RSS)", "CONFAZ (RSS)", "Receita Federal (RSS)"], key="sel_of")
    with col2:
        st.markdown("##### 📰 Não-Oficiais")
        sel_nof = st.multiselect("", [k for k, v in FONTES_CONFIG.items() if not v['oficial']], key="sel_nof")
    
    todas = sel_of + sel_nof
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        buscar = st.button("🔍 Buscar", use_container_width=True, type="primary")
    with col2:
        forcar = st.button("🔄 Forçar", use_container_width=True)
    with col3:
        email_btn = st.button("📧 Email", use_container_width=True)
    with col4:
        limpar_btn = st.button("🗑️ Limpar", use_container_width=True)
    
    filtro = st.selectbox("Filtrar:", ["Todas", "Oficiais", "Não-Oficiais"])
    
    if (buscar or forcar) and todas:
        if forcar:
            cached_buscar.clear()
        
        with st.spinner("Buscando..."):
            resultados, logs = cached_buscar(tuple(todas), debug=debug_mode)
        
        if debug_mode:
            st.markdown("### 📋 Debug Log")
            st.markdown('<div class="debug-section">', unsafe_allow_html=True)
            for log in logs:
                escaped = html.escape(str(log))
                css_class = "success" if "✅" in log else "error" if "❌" in log else ""
                st.markdown(f'<div class="debug-log {css_class}">{escaped}</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        if resultados:
            novos = salvar_atualizacoes(resultados)
            st.success(f"✅ {len(resultados)} encontrados, {novos} novos!")
        else:
            st.warning("⚠️ Nenhum resultado. Ative Debug para ver detalhes.")
    
    if email_btn:
        atts = obter_atualizacoes(limite=50)
        ok, msg = enviar_email(atts, datetime.now().strftime("%d/%m/%Y")) if atts else (False, "Sem dados")
        st.success(msg) if ok else st.error(msg)
    
    if limpar_btn:
        limpar_atualizacoes()
        st.rerun()
    
    st.markdown("---")
    
    filtro_val = 1 if filtro == "Oficiais" else 0 if filtro == "Não-Oficiais" else None
    atts = obter_atualizacoes(filtro_oficial=filtro_val, limite=100)
    
    if atts:
        st.markdown(f"### 📋 {len(atts)} Atualizações")
        por_fonte = {}
        for a in atts:
            por_fonte.setdefault(a.get('fonte', 'Outros'), []).append(a)
        
        for fonte, lista in por_fonte.items():
            with st.expander(f"🏛️ {fonte} ({len(lista)})", expanded=len(por_fonte) <= 3):
                for a in lista:
                    badge = "badge-rss" if a.get('oficial') else "badge-news"
                    st.markdown(f'<div class="search-result"><span class="card-badge {badge}">{a.get("tipo", "")}</span><div class="result-title">{a.get("titulo", "")[:180]}</div><div class="result-meta">📅 {a.get("data_pub", "")[:10]}</div><a href="{a.get("link", "#")}" target="_blank" style="color:#3b82f6;font-size:0.8rem;">🔗 Acessar</a></div>', unsafe_allow_html=True)
    else:
        st.info("👆 Selecione fontes e clique em Buscar")

elif st.session_state.pagina == "biblioteca":
    st.markdown("## 📚 Biblioteca")
    busca = st.text_input("🔍 Buscar:", placeholder="Digite...")
    
    if busca:
        conn = get_conn()
        estudos = [dict(r) for r in conn.cursor().execute(
            "SELECT e.*, c.nome as cliente FROM estudos e JOIN clientes c ON e.cliente_id=c.id WHERE e.titulo LIKE ? OR e.resumo LIKE ?",
            (f"%{busca}%", f"%{busca}%")).fetchall()]
        conn.close()
    else:
        estudos = [dict(r) for r in listar_estudos()]
    
    for est in estudos:
        with st.expander(f"📄 {est['titulo'][:50]}... - {est.get('cliente', '')}"):
            st.markdown(est.get('resumo', '')[:400] + "...")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("📖 Abrir", key=f"a_{est['id']}"):
                    navegar("estudo_view", est.get('cliente_id'), est['id'])
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"d_{est['id']}"):
                    excluir_estudo(est['id'])
                    st.rerun()

elif st.session_state.pagina == "clientes":
    st.markdown("## 👥 Clientes")
    for cl in listar_clientes():
        cl = dict(cl)
        estudos_cl = listar_estudos(cl['id'])
        with st.expander(f"🏢 {cl['nome']}" + (f" - {cl.get('cnpj', '')}" if cl.get('cnpj') else "")):
            st.markdown(f"**Estudos:** {len(estudos_cl)}")
            for est in estudos_cl[:5]:
                est = dict(est)
                if st.button(f"📄 {est['titulo'][:35]}...", key=f"e_{cl['id']}_{est['id']}"):
                    navegar("estudo_view", cl['id'], est['id'])
                    st.rerun()
            if st.button("🗑️ Excluir", key=f"dc_{cl['id']}"):
                excluir_cliente(cl['id'])
                st.rerun()

elif st.session_state.pagina == "novo":
    st.markdown("## ➕ Novo Cadastro")
    tab1, tab2 = st.tabs(["📄 Estudo", "👤 Cliente"])
    
    with tab1:
        clientes = listar_clientes()
        if not clientes:
            st.warning("Cadastre um cliente primeiro")
        else:
            with st.form("f_estudo"):
                opts = {c['nome']: c['id'] for c in clientes}
                cliente = st.selectbox("Cliente:", list(opts.keys()))
                titulo = st.text_input("Título:")
                resumo = st.text_area("Resumo:", height=200)
                tags = st.text_input("Tags:")
                arquivos = st.file_uploader("Anexos:", accept_multiple_files=True)
                if st.form_submit_button("💾 Salvar", type="primary"):
                    if titulo and resumo:
                        eid = criar_estudo(opts[cliente], titulo, resumo, tags)
                        for arq in arquivos:
                            add_anexo(eid, arq.name, arq.type or "", arq.read(), arq.size)
                        st.success("✅ Criado!")
                        st.balloons()
                    else:
                        st.error("Preencha título e resumo")
    
    with tab2:
        with st.form("f_cliente"):
            nome = st.text_input("Nome:")
            cnpj = st.text_input("CNPJ:")
            obs = st.text_area("Obs:")
            if st.form_submit_button("💾 Salvar", type="primary"):
                if nome:
                    criar_cliente(nome, cnpj, obs)
                    st.success("✅ Criado!")
                else:
                    st.error("Nome obrigatório")

elif st.session_state.pagina == "config":
    st.markdown("## ⚙️ Configurações")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**OpenAI**")
        st.success("✅ OK") if client else st.error("❌ N/A")
    with col2:
        st.markdown("**Email**")
        st.success("✅ OK") if GMAIL_USER else st.error("❌ N/A")
    with col3:
        st.markdown("**RSS**")
        st.success("✅ Ativo")
    
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📥 Backup", use_container_width=True):
            st.download_button("⬇️ Baixar", backup(), f"backup_{datetime.now():%Y%m%d}.zip", use_container_width=True)
    with col2:
        arq = st.file_uploader("Restaurar:", type=["zip", "json"])
        if arq and st.button("📤 Restaurar", use_container_width=True):
            ok, msg = restaurar(arq)
            st.success(msg) if ok else st.error(msg)
    
    st.markdown("---")
    st.markdown("""
    **v6.2** - Correções finais:
    - ✅ normalize_date() robusto
    - ✅ Debug com CSS (sem backticks)
    - ✅ ORDER BY com CASE para vazios
    - ✅ DOU com filtro de seção
    - ✅ Snippet de bloqueio no debug
    """)

elif st.session_state.pagina == "estudo_view":
    estudo = obter_estudo(st.session_state.estudo_id)
    cliente = obter_cliente(st.session_state.cliente_id)
    
    if estudo and cliente:
        estudo, cliente = dict(estudo), dict(cliente)
        
        col1, col2, col3 = st.columns([4, 1, 1])
        with col1:
            st.markdown(f"## 📖 {estudo['titulo']}")
            st.caption(f"👤 {cliente['nome']}")
        with col2:
            if st.button("✏️"):
                st.session_state.edit_mode = True
                st.rerun()
        with col3:
            if st.button("🗑️"):
                excluir_estudo(estudo['id'])
                navegar("biblioteca")
                st.rerun()
        
        st.markdown("---")
        
        if st.session_state.edit_mode:
            with st.form("f_edit"):
                titulo = st.text_input("Título:", estudo['titulo'])
                resumo = st.text_area("Resumo:", estudo['resumo'], height=300)
                tags = st.text_input("Tags:", estudo.get('tags', ''))
                col1, col2 = st.columns(2)
                with col1:
                    if st.form_submit_button("💾"):
                        atualizar_estudo(estudo['id'], titulo, resumo, tags)
                        st.session_state.edit_mode = False
                        st.rerun()
                with col2:
                    if st.form_submit_button("❌"):
                        st.session_state.edit_mode = False
                        st.rerun()
        else:
            st.markdown(estudo['resumo'])
        
        st.markdown("### 📎 Anexos")
        for anx in listar_anexos(estudo['id']):
            anx = dict(anx)
            col1, col2, col3 = st.columns([4, 1, 1])
            with col1:
                st.markdown(f"📄 {anx['filename']}")
            with col2:
                anexo_full = obter_anexo(anx['id'])
                if anexo_full:
                    st.download_button("⬇️", base64.b64decode(anexo_full['file_data']), anx['filename'], anx['file_type'], key=f"dl_{anx['id']}")
            with col3:
                if st.button("🗑️", key=f"da_{anx['id']}"):
                    excluir_anexo(anx['id'])
                    st.rerun()
        
        with st.form("f_upload", clear_on_submit=True):
            novos = st.file_uploader("Adicionar:", accept_multiple_files=True)
            if st.form_submit_button("📤") and novos:
                for arq in novos:
                    add_anexo(estudo['id'], arq.name, arq.type or "", arq.read(), arq.size)
                st.rerun()
        
        if st.button("← Voltar"):
            navegar("biblioteca")
            st.rerun()

st.markdown("---")
st.caption("⚖️ Biblioteca Tributária Pro v6.2 | © 2025 MP Solutions")
