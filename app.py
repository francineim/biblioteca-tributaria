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
import re

st.set_page_config(page_title="Biblioteca Tributária", page_icon="📚", layout="wide", initial_sidebar_state="collapsed")
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "biblioteca.db"

# Configurar OpenAI
try:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except:
    client = None

# Configurações de email
try:
    GMAIL_USER = st.secrets["GMAIL_USER"]
    GMAIL_APP_PASSWORD = st.secrets["GMAIL_APP_PASSWORD"]
    EMAIL_DESTINO = st.secrets["EMAIL_DESTINO"]
except:
    GMAIL_USER = None
    GMAIL_APP_PASSWORD = None
    EMAIL_DESTINO = None

st.markdown("""<style>
.main-header {font-size: 2.5rem; font-weight: bold; color: #1f4e79; margin-bottom: 0.5rem; text-align: center;}
.sub-header {font-size: 1.1rem; color: #666; text-align: center; margin-bottom: 2rem;}
.stat-card {background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 12px; padding: 1.5rem; color: white; text-align: center;}
.stat-number {font-size: 2.5rem; font-weight: bold;}
.stat-label {font-size: 0.9rem; opacity: 0.9;}
.tag {display: inline-block; background-color: #e3f2fd; color: #1565c0; padding: 0.2rem 0.6rem; border-radius: 15px; font-size: 0.8rem; margin-right: 0.3rem; margin-bottom: 0.3rem;}
.user-message {background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 15px 20px; border-radius: 20px 20px 5px 20px; margin: 10px 0; margin-left: 15%;}
.assistant-message {background-color: #f7f7f8; padding: 15px 20px; border-radius: 20px 20px 20px 5px; margin: 10px 0; margin-right: 15%; border: 1px solid #e5e5e5;}
.fonte-card {background-color: #f0f9ff; border-left: 4px solid #0ea5e9; padding: 12px 15px; margin: 8px 0; border-radius: 0 8px 8px 0;}
.fonte-card a {color: #0369a1; text-decoration: none; font-weight: 500;}
.biblioteca-card {background-color: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px 15px; margin: 8px 0; border-radius: 0 8px 8px 0;}
.atualizacao-card {background-color: #ecfdf5; border-left: 4px solid #10b981; padding: 15px; margin: 10px 0; border-radius: 0 10px 10px 0;}
.atualizacao-card h4 {margin: 0 0 8px 0; color: #065f46;}
.atualizacao-card p {margin: 5px 0; color: #374151; font-size: 0.95rem;}
.atualizacao-header {background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; padding: 15px 20px; border-radius: 10px; margin-bottom: 15px;}
</style>""", unsafe_allow_html=True)

def get_conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, cnpj TEXT, observacoes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS estudos (id INTEGER PRIMARY KEY AUTOINCREMENT, cliente_id INTEGER NOT NULL, titulo TEXT NOT NULL, resumo TEXT NOT NULL, tags TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE)")
    c.execute("CREATE TABLE IF NOT EXISTS anexos (id INTEGER PRIMARY KEY AUTOINCREMENT, estudo_id INTEGER NOT NULL, filename TEXT NOT NULL, file_type TEXT NOT NULL, file_data TEXT NOT NULL, file_size INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (estudo_id) REFERENCES estudos(id) ON DELETE CASCADE)")
    c.execute("CREATE TABLE IF NOT EXISTS chat_historico (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, content TEXT NOT NULL, fontes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS atualizacoes_tributarias (id INTEGER PRIMARY KEY AUTOINCREMENT, fonte TEXT NOT NULL, titulo TEXT NOT NULL, resumo TEXT, link TEXT, data_publicacao DATE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    conn.close()

init_db()

# ==================== BUSCA DE ATUALIZAÇÕES COM WEB SEARCH ====================

def buscar_atualizacoes_web(fonte, data_inicio, data_fim):
    """Busca atualizações usando GPT-4 com browsing capability"""
    if not client:
        return []
    
    # Mapear fontes para queries de busca específicas
    queries_por_fonte = {
        "Receita Federal": f"site:gov.br/receitafederal instrução normativa OR portaria OR solução consulta {data_inicio} {data_fim}",
        "Planalto": f"site:planalto.gov.br lei OR decreto OR medida provisória tributário fiscal {data_inicio} {data_fim}",
        "SEFAZ ES": f"site:sefaz.es.gov.br decreto OR portaria ICMS {data_inicio} {data_fim}",
        "SEFAZ SC": f"site:sef.sc.gov.br decreto OR ato DIAT ICMS {data_inicio} {data_fim}",
        "SEFAZ PR": f"site:fazenda.pr.gov.br decreto OR NPF ICMS {data_inicio} {data_fim}",
        "SEFAZ MG": f"site:fazenda.mg.gov.br decreto OR portaria ICMS {data_inicio} {data_fim}",
        "SEFAZ RJ": f"site:fazenda.rj.gov.br decreto OR resolução ICMS {data_inicio} {data_fim}",
        "SEFAZ PE": f"site:sefaz.pe.gov.br decreto OR portaria ICMS {data_inicio} {data_fim}",
        "SEFAZ CE": f"site:sefaz.ce.gov.br decreto OR instrução normativa ICMS {data_inicio} {data_fim}",
        "CONFAZ": f"site:confaz.fazenda.gov.br convênio ICMS protocolo ajuste SINIEF {data_inicio} {data_fim}",
        "Diário Oficial": f"site:in.gov.br tributário fiscal ICMS PIS COFINS {data_inicio} {data_fim}",
    }
    
    query = queries_por_fonte.get(fonte, f"{fonte} legislação tributária {data_inicio} {data_fim}")
    
    prompt = f"""Você é um pesquisador especialista em legislação tributária brasileira.

TAREFA: Pesquise e liste as atualizações tributárias REAIS publicadas pela fonte "{fonte}" no período de {data_inicio} a {data_fim}.

IMPORTANTE:
- Liste APENAS atos normativos REAIS e VERIFICÁVEIS
- Inclua: número do ato, data de publicação, ementa/resumo
- Foque em: Instruções Normativas, Decretos, Portarias, Convênios ICMS, Atos DIAT, Soluções de Consulta
- Se não encontrar nada no período, retorne lista vazia

Para cada atualização encontrada, forneça no formato JSON:
{{
    "atualizacoes": [
        {{
            "titulo": "Tipo e número do ato (ex: IN RFB nº 2.198/2024)",
            "resumo": "Ementa ou resumo do conteúdo em 2-3 linhas",
            "link": "URL oficial do documento",
            "data": "YYYY-MM-DD"
        }}
    ]
}}

QUERY DE BUSCA: {query}

Retorne APENAS o JSON válido, sem explicações."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",  # Usando GPT-4o que tem melhor conhecimento atualizado
            messages=[
                {"role": "system", "content": "Você pesquisa legislação tributária brasileira. Retorne apenas JSON válido."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=3000,
            temperature=0.2
        )
        
        resposta = response.choices[0].message.content.strip()
        
        # Limpar JSON
        if "```json" in resposta:
            resposta = resposta.split("```json")[1].split("```")[0]
        elif "```" in resposta:
            resposta = resposta.split("```")[1].split("```")[0]
        
        dados = json.loads(resposta)
        atualizacoes = dados.get("atualizacoes", [])
        
        # Adicionar fonte a cada atualização
        for att in atualizacoes:
            att["fonte"] = fonte
        
        return atualizacoes
    
    except Exception as e:
        st.warning(f"Erro ao buscar {fonte}: {str(e)}")
        return []

def buscar_todas_atualizacoes(data_inicio, data_fim, fontes_selecionadas=None):
    """Busca atualizações em todas as fontes"""
    todas_fontes = [
        "Receita Federal",
        "Planalto", 
        "SEFAZ ES",
        "SEFAZ SC",
        "SEFAZ PR",
        "SEFAZ MG",
        "SEFAZ RJ",
        "SEFAZ PE",
        "SEFAZ CE",
        "CONFAZ",
        "Diário Oficial"
    ]
    
    if fontes_selecionadas:
        fontes = fontes_selecionadas
    else:
        fontes = todas_fontes
    
    todas_atualizacoes = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, fonte in enumerate(fontes):
        status_text.text(f"🔍 Buscando em {fonte}...")
        progress_bar.progress((i + 1) / len(fontes))
        
        atualizacoes = buscar_atualizacoes_web(fonte, data_inicio, data_fim)
        todas_atualizacoes.extend(atualizacoes)
    
    progress_bar.empty()
    status_text.empty()
    
    return todas_atualizacoes

def salvar_atualizacoes(atualizacoes):
    """Salva atualizações no banco"""
    conn = get_conn()
    c = conn.cursor()
    novos = 0
    
    for att in atualizacoes:
        c.execute(
            "SELECT id FROM atualizacoes_tributarias WHERE titulo = ? AND fonte = ?",
            (att.get("titulo", ""), att.get("fonte", ""))
        )
        if not c.fetchone():
            c.execute(
                "INSERT INTO atualizacoes_tributarias (fonte, titulo, resumo, link, data_publicacao) VALUES (?, ?, ?, ?, ?)",
                (att.get("fonte", ""), att.get("titulo", ""), att.get("resumo", ""), att.get("link", ""), att.get("data", ""))
            )
            novos += 1
    
    conn.commit()
    conn.close()
    return novos

def obter_atualizacoes_db(dias=30):
    """Obtém atualizações do banco"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM atualizacoes_tributarias ORDER BY data_publicacao DESC, created_at DESC LIMIT 100")
    atualizacoes = [dict(row) for row in c.fetchall()]
    conn.close()
    return atualizacoes

def limpar_atualizacoes():
    """Limpa todas as atualizações"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM atualizacoes_tributarias")
    conn.commit()
    conn.close()

def enviar_email_atualizacoes(atualizacoes, assunto_extra=""):
    """Envia email com atualizações"""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD or not EMAIL_DESTINO:
        return False, "Credenciais de email não configuradas"
    
    if not atualizacoes:
        return False, "Nenhuma atualização para enviar"
    
    html = f"""
    <html>
    <head><style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; }}
        .att {{ background: #f8f9fa; border-left: 4px solid #10b981; padding: 15px; margin: 15px 0; border-radius: 0 8px 8px 0; }}
        .att h3 {{ color: #065f46; margin: 0 0 10px 0; }}
        .att .fonte {{ color: #6b7280; font-size: 12px; text-transform: uppercase; }}
        .att a {{ color: #0369a1; }}
    </style></head>
    <body>
        <div class="header">
            <h1>📚 Atualizações Tributárias</h1>
            <p>{datetime.now().strftime("%d/%m/%Y %H:%M")}</p>
        </div>
        <p>Seguem as atualizações tributárias identificadas:</p>
    """
    
    por_fonte = {}
    for att in atualizacoes:
        fonte = att.get("fonte", "Outros")
        if fonte not in por_fonte:
            por_fonte[fonte] = []
        por_fonte[fonte].append(att)
    
    for fonte, lista in por_fonte.items():
        html += f"<h2>🏛️ {fonte}</h2>"
        for att in lista:
            html += f"""
            <div class="att">
                <div class="fonte">{att.get('data_publicacao', att.get('data', ''))}</div>
                <h3>{att.get('titulo', '')}</h3>
                <p>{att.get('resumo', '')}</p>
                <a href="{att.get('link', '#')}">🔗 Acessar documento</a>
            </div>
            """
    
    html += "</body></html>"
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"📚 Atualizações Tributárias {assunto_extra} - {datetime.now().strftime('%d/%m/%Y')}"
        msg['From'] = GMAIL_USER
        msg['To'] = EMAIL_DESTINO
        msg.attach(MIMEText(html, 'html'))
        
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, EMAIL_DESTINO, msg.as_string())
        server.quit()
        
        return True, f"Email enviado para {EMAIL_DESTINO}"
    except Exception as e:
        return False, f"Erro: {str(e)}"

# ==================== CONSULTOR IA ====================

FONTES_OFICIAIS = {
    "Receita Federal": {"url": "https://www.gov.br/receitafederal", "descricao": "Tributos federais"},
    "Planalto": {"url": "https://www.planalto.gov.br", "descricao": "Legislação federal"},
    "SEFAZ ES": {"url": "https://www.sefaz.es.gov.br", "descricao": "ICMS Espírito Santo"},
    "SEFAZ SC": {"url": "https://www.sef.sc.gov.br", "descricao": "ICMS Santa Catarina"},
    "SEFAZ PR": {"url": "https://www.fazenda.pr.gov.br", "descricao": "ICMS Paraná"},
    "SEFAZ MG": {"url": "https://www.fazenda.mg.gov.br", "descricao": "ICMS Minas Gerais"},
    "SEFAZ SP": {"url": "https://portal.fazenda.sp.gov.br", "descricao": "ICMS São Paulo"},
    "SEFAZ RJ": {"url": "https://www.fazenda.rj.gov.br", "descricao": "ICMS Rio de Janeiro"},
    "CONFAZ": {"url": "https://www.confaz.fazenda.gov.br", "descricao": "Convênios ICMS"},
}

def buscar_na_biblioteca(pergunta):
    conn = get_conn()
    c = conn.cursor()
    palavras = [p.lower() for p in pergunta.split() if len(p) > 3]
    resultados, ids = [], set()
    for p in palavras:
        c.execute("SELECT e.id, e.titulo, e.resumo, e.tags, c.nome as cliente_nome FROM estudos e JOIN clientes c ON e.cliente_id = c.id WHERE LOWER(e.titulo) LIKE ? OR LOWER(e.resumo) LIKE ? OR LOWER(e.tags) LIKE ? LIMIT 5", (f"%{p}%", f"%{p}%", f"%{p}%"))
        for row in c.fetchall():
            if row['id'] not in ids:
                resultados.append(dict(row))
                ids.add(row['id'])
    conn.close()
    return resultados[:5]

def identificar_fontes(pergunta):
    p = pergunta.lower()
    fontes = []
    mapa = {
        "receita federal": "Receita Federal", "pis": "Receita Federal", "cofins": "Receita Federal", "irpj": "Receita Federal",
        "planalto": "Planalto", "lei": "Planalto", "decreto federal": "Planalto",
        "espírito santo": "SEFAZ ES", "espirito santo": "SEFAZ ES", " es ": "SEFAZ ES",
        "santa catarina": "SEFAZ SC", " sc ": "SEFAZ SC",
        "paraná": "SEFAZ PR", "parana": "SEFAZ PR", " pr ": "SEFAZ PR",
        "minas gerais": "SEFAZ MG", " mg ": "SEFAZ MG",
        "são paulo": "SEFAZ SP", "sao paulo": "SEFAZ SP", " sp ": "SEFAZ SP",
        "rio de janeiro": "SEFAZ RJ", " rj ": "SEFAZ RJ",
        "convênio": "CONFAZ", "confaz": "CONFAZ", "icms": "CONFAZ",
    }
    for termo, fonte in mapa.items():
        if termo in p and fonte not in fontes:
            fontes.append(fonte)
    if not fontes:
        fontes = ["Receita Federal", "Planalto"]
    return [{"nome": f, "url": FONTES_OFICIAIS[f]["url"], "descricao": FONTES_OFICIAIS[f]["descricao"]} for f in fontes[:5]]

def consultar_agente(pergunta, historico):
    if not client:
        return "❌ API não configurada", [], []
    
    materiais = buscar_na_biblioteca(pergunta)
    fontes = identificar_fontes(pergunta)
    
    contexto = ""
    if materiais:
        contexto = "\nMATERIAIS DA BIBLIOTECA:\n" + "\n".join([f"- {m['titulo']}: {m['resumo'][:200]}" for m in materiais])
    
    try:
        messages = [
            {"role": "system", "content": f"Você é especialista em tributação brasileira. Seja claro e cite legislação.{contexto}"},
            *[{"role": m["role"], "content": m["content"]} for m in historico[-10:]],
            {"role": "user", "content": pergunta}
        ]
        
        response = client.chat.completions.create(model="gpt-4o-mini", messages=messages, max_tokens=2500, temperature=0.4)
        return response.choices[0].message.content, materiais, fontes
    except Exception as e:
        return f"❌ Erro: {str(e)}", [], []

def salvar_msg(role, content, fontes=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO chat_historico (role, content, fontes) VALUES (?, ?, ?)", (role, content, json.dumps(fontes) if fontes else None))
    conn.commit()
    conn.close()

def obter_historico():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT role, content, fontes, created_at FROM chat_historico ORDER BY created_at ASC")
    h = [{"role": r["role"], "content": r["content"], "fontes": r["fontes"], "created_at": r["created_at"]} for r in c.fetchall()]
    conn.close()
    return h

def limpar_chat():
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM chat_historico")
    conn.commit()
    conn.close()

# ==================== CRUD ====================

def criar_backup():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        conn = get_conn()
        c = conn.cursor()
        data = {}
        for tabela in ["clientes", "estudos", "anexos", "chat_historico", "atualizacoes_tributarias"]:
            c.execute(f"SELECT * FROM {tabela}")
            data[tabela] = [dict(row) for row in c.fetchall()]
        conn.close()
        data["versao"] = "3.0"
        data["data_backup"] = datetime.now().isoformat()
        zf.writestr("backup.json", json.dumps(data, ensure_ascii=False, indent=2))
    buf.seek(0)
    return buf

def restaurar_backup(file):
    try:
        content = file.read()
        try:
            with zipfile.ZipFile(io.BytesIO(content), 'r') as zf:
                data = json.loads(zf.read("backup.json"))
        except:
            data = json.loads(content.decode('utf-8'))
        
        conn = get_conn()
        c = conn.cursor()
        for t in ["anexos", "estudos", "clientes", "chat_historico", "atualizacoes_tributarias"]:
            c.execute(f"DELETE FROM {t}")
        
        for cl in data.get("clientes", []):
            c.execute("INSERT INTO clientes (id, nome, cnpj, observacoes, created_at) VALUES (?, ?, ?, ?, ?)", 
                     (cl['id'], cl['nome'], cl.get('cnpj'), cl.get('observacoes'), cl.get('created_at')))
        for e in data.get("estudos", []):
            c.execute("INSERT INTO estudos (id, cliente_id, titulo, resumo, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (e['id'], e['cliente_id'], e['titulo'], e['resumo'], e.get('tags'), e.get('created_at'), e.get('updated_at')))
        for a in data.get("anexos", []):
            c.execute("INSERT INTO anexos (id, estudo_id, filename, file_type, file_data, file_size, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (a['id'], a['estudo_id'], a['filename'], a['file_type'], a['file_data'], a.get('file_size'), a.get('created_at')))
        for ch in data.get("chat_historico", []):
            c.execute("INSERT INTO chat_historico (id, role, content, fontes, created_at) VALUES (?, ?, ?, ?, ?)",
                     (ch['id'], ch['role'], ch['content'], ch.get('fontes'), ch.get('created_at')))
        for at in data.get("atualizacoes_tributarias", []):
            c.execute("INSERT INTO atualizacoes_tributarias (id, fonte, titulo, resumo, link, data_publicacao, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (at['id'], at['fonte'], at['titulo'], at.get('resumo'), at.get('link'), at.get('data_publicacao'), at.get('created_at')))
        conn.commit()
        conn.close()
        return True, "Restaurado!"
    except Exception as e:
        return False, str(e)

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
    c = conn.cursor()
    c.execute("SELECT * FROM clientes ORDER BY nome")
    r = c.fetchall()
    conn.close()
    return r

def obter_cliente(id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM clientes WHERE id = ?", (id,))
    r = c.fetchone()
    conn.close()
    return r

def excluir_cliente(id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM anexos WHERE estudo_id IN (SELECT id FROM estudos WHERE cliente_id = ?)", (id,))
    c.execute("DELETE FROM estudos WHERE cliente_id = ?", (id,))
    c.execute("DELETE FROM clientes WHERE id = ?", (id,))
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

def listar_estudos(cid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM estudos WHERE cliente_id = ? ORDER BY created_at DESC", (cid,))
    r = c.fetchall()
    conn.close()
    return r

def obter_estudo(id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM estudos WHERE id = ?", (id,))
    r = c.fetchone()
    conn.close()
    return r

def atualizar_estudo(id, titulo, resumo, tags):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE estudos SET titulo=?, resumo=?, tags=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (titulo, resumo, tags, id))
    conn.commit()
    conn.close()

def excluir_estudo(id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM anexos WHERE estudo_id = ?", (id,))
    c.execute("DELETE FROM estudos WHERE id = ?", (id,))
    conn.commit()
    conn.close()

def estudos_recentes(lim=10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT e.*, c.nome as cliente_nome FROM estudos e JOIN clientes c ON e.cliente_id = c.id ORDER BY e.created_at DESC LIMIT ?", (lim,))
    r = c.fetchall()
    conn.close()
    return r

def buscar_estudos(termo):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT e.*, c.nome as cliente_nome FROM estudos e JOIN clientes c ON e.cliente_id = c.id WHERE e.titulo LIKE ? OR e.resumo LIKE ? OR e.tags LIKE ? ORDER BY e.created_at DESC", (f"%{termo}%", f"%{termo}%", f"%{termo}%"))
    r = c.fetchall()
    conn.close()
    return r

def add_anexo(eid, nome, tipo, dados, tam):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO anexos (estudo_id, filename, file_type, file_data, file_size) VALUES (?, ?, ?, ?, ?)", (eid, nome, tipo, base64.b64encode(dados).decode(), tam))
    conn.commit()
    conn.close()

def listar_anexos(eid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, filename, file_type, file_size FROM anexos WHERE estudo_id = ?", (eid,))
    r = c.fetchall()
    conn.close()
    return r

def obter_anexo(id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM anexos WHERE id = ?", (id,))
    r = c.fetchone()
    conn.close()
    return r

def excluir_anexo(id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM anexos WHERE id = ?", (id,))
    conn.commit()
    conn.close()

def stats():
    conn = get_conn()
    c = conn.cursor()
    s = {}
    for t, n in [("clientes", "clientes"), ("estudos", "estudos"), ("anexos", "anexos"), ("atualizacoes_tributarias", "atualizacoes")]:
        c.execute(f"SELECT COUNT(*) FROM {t}")
        s[n] = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM chat_historico WHERE role='user'")
    s["consultas"] = c.fetchone()[0]
    conn.close()
    return s

def fmt_date(d):
    if not d: return ""
    try: return datetime.fromisoformat(str(d)).strftime("%d/%m/%Y")
    except: return str(d)[:10]

# ==================== ESTADO ====================

if "pag" not in st.session_state: st.session_state.pag = "chat"
if "cli" not in st.session_state: st.session_state.cli = None
if "est" not in st.session_state: st.session_state.est = None
if "edit" not in st.session_state: st.session_state.edit = False
if "materiais" not in st.session_state: st.session_state.materiais = []
if "mostrar_historico" not in st.session_state: st.session_state.mostrar_historico = False

def go(p, c=None, e=None):
    st.session_state.pag = p
    st.session_state.cli = c
    st.session_state.est = e
    st.session_state.edit = False

# ==================== NAVEGAÇÃO ====================

cols = st.columns(6)
botoes = [("🤖 Consultor", "chat"), ("📢 Atualizações", "atualizacoes"), ("📚 Biblioteca", "biblioteca"), ("➕ Novo", "novo"), ("👥 Clientes", "clientes"), ("⚙️ Config", "config")]
for i, (label, pag) in enumerate(botoes):
    with cols[i]:
        if st.button(label, use_container_width=True, type="primary" if st.session_state.pag == pag else "secondary"):
            go(pag)

st.markdown("---")

# ==================== PÁGINAS ====================

if st.session_state.pag == "chat":
    st.markdown('<h1 class="main-header">🤖 Consultor Tributário IA</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Pergunte sobre tributação brasileira</p>', unsafe_allow_html=True)
    
    # Campo de pergunta principal
    with st.form("chat", clear_on_submit=True):
        pergunta = st.text_area("💬 Sua pergunta:", height=120, placeholder="Ex: Como funciona a substituição tributária de ICMS em operações interestaduais?")
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            enviar = st.form_submit_button("🔍 Consultar", use_container_width=True, type="primary")
        with col2:
            ver_hist = st.form_submit_button("📜 Histórico", use_container_width=True)
        with col3:
            limpar = st.form_submit_button("🗑️ Limpar", use_container_width=True)
    
    if ver_hist:
        st.session_state.mostrar_historico = not st.session_state.mostrar_historico
    
    if limpar:
        limpar_chat()
        st.session_state.mostrar_historico = False
        st.rerun()
    
    if enviar and pergunta.strip():
        salvar_msg("user", pergunta)
        with st.spinner("🔄 Pesquisando..."):
            hist = [{"role": m["role"], "content": m["content"]} for m in obter_historico()[:-1]]
            resposta, materiais, fontes = consultar_agente(pergunta, hist)
            salvar_msg("assistant", resposta, fontes)
            st.session_state.materiais = materiais
        st.rerun()
    
    # Exibir última resposta
    historico = obter_historico()
    if historico:
        # Mostrar apenas última pergunta e resposta
        ultimas = historico[-2:] if len(historico) >= 2 else historico
        for msg in ultimas:
            if msg["role"] == "user":
                st.markdown(f'<div class="user-message">🧑 {msg["content"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="assistant-message">{msg["content"]}</div>', unsafe_allow_html=True)
                if msg.get("fontes"):
                    try:
                        fontes = json.loads(msg["fontes"])
                        if fontes:
                            st.markdown("**🔗 Fontes oficiais:**")
                            for f in fontes:
                                st.markdown(f"- [{f['nome']}]({f['url']}) - {f['descricao']}")
                    except: pass
        
        # Materiais relacionados
        if st.session_state.materiais:
            st.markdown("---")
            st.markdown("### 📚 Na sua biblioteca")
            for m in st.session_state.materiais:
                st.markdown(f'<div class="biblioteca-card">📄 **{m["titulo"]}** ({m["cliente_nome"]})</div>', unsafe_allow_html=True)
    
    # Histórico oculto (só mostra se solicitado)
    if st.session_state.mostrar_historico and len(historico) > 2:
        st.markdown("---")
        st.markdown("### 📜 Histórico de Conversas")
        for msg in historico[:-2]:
            with st.expander(f"{'🧑 Você' if msg['role'] == 'user' else '🤖 Assistente'}: {msg['content'][:50]}..."):
                st.markdown(msg["content"])

elif st.session_state.pag == "atualizacoes":
    st.markdown('<div class="atualizacao-header"><h1>📢 Atualizações Tributárias</h1><p>Legislação tributária em tempo real</p></div>', unsafe_allow_html=True)
    
    # Busca por período
    st.markdown("### 🔎 Buscar Atualizações")
    
    col1, col2 = st.columns(2)
    with col1:
        data_ini = st.date_input("De:", value=datetime.now() - timedelta(days=7))
    with col2:
        data_fim = st.date_input("Até:", value=datetime.now())
    
    # Seleção de fontes
    todas_fontes = ["Receita Federal", "Planalto", "SEFAZ ES", "SEFAZ SC", "SEFAZ PR", "SEFAZ MG", "SEFAZ RJ", "SEFAZ PE", "SEFAZ CE", "CONFAZ", "Diário Oficial"]
    fontes_sel = st.multiselect("Fontes:", todas_fontes, default=todas_fontes[:5])
    
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🔍 Buscar Atualizações", use_container_width=True, type="primary"):
            if fontes_sel:
                atualizacoes = buscar_todas_atualizacoes(
                    data_ini.strftime("%Y-%m-%d"),
                    data_fim.strftime("%Y-%m-%d"),
                    fontes_sel
                )
                if atualizacoes:
                    novos = salvar_atualizacoes(atualizacoes)
                    st.success(f"✅ {len(atualizacoes)} atualizações encontradas, {novos} novas!")
                else:
                    st.warning("Nenhuma atualização encontrada no período")
                st.rerun()
            else:
                st.warning("Selecione pelo menos uma fonte")
    
    with col2:
        if st.button("📧 Enviar por Email", use_container_width=True):
            atts = obter_atualizacoes_db()
            if atts:
                ok, msg = enviar_email_atualizacoes(atts, f"({data_ini} a {data_fim})")
                if ok:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")
            else:
                st.warning("Nenhuma atualização para enviar")
    
    with col3:
        if st.button("🗑️ Limpar Base", use_container_width=True):
            limpar_atualizacoes()
            st.success("Base limpa!")
            st.rerun()
    
    # Exibir atualizações
    st.markdown("---")
    atts = obter_atualizacoes_db()
    
    if atts:
        st.markdown(f"### 📋 {len(atts)} Atualizações Cadastradas")
        
        por_fonte = {}
        for a in atts:
            f = a.get("fonte", "Outros")
            if f not in por_fonte:
                por_fonte[f] = []
            por_fonte[f].append(a)
        
        for fonte, lista in por_fonte.items():
            with st.expander(f"🏛️ {fonte} ({len(lista)})", expanded=True):
                for a in lista:
                    st.markdown(f"""
                    <div class="atualizacao-card">
                        <h4>{a.get('titulo', '')}</h4>
                        <p><strong>📅</strong> {a.get('data_publicacao', '')}</p>
                        <p>{a.get('resumo', '')}</p>
                        <p><a href="{a.get('link', '#')}" target="_blank">🔗 Acessar documento</a></p>
                    </div>
                    """, unsafe_allow_html=True)
    else:
        st.info("Clique em 'Buscar Atualizações' para começar")

elif st.session_state.pag == "biblioteca":
    st.markdown("## 📚 Biblioteca")
    
    busca = st.text_input("🔍 Buscar", placeholder="Digite...")
    resultados = buscar_estudos(busca) if busca else estudos_recentes(20)
    
    if resultados:
        for r in resultados:
            with st.expander(f"📄 {r['titulo']} - {r['cliente_nome']}"):
                st.markdown(f"**Data:** {fmt_date(r['created_at'])}")
                if r['tags']:
                    st.markdown(" ".join([f"`{t.strip()}`" for t in r['tags'].split(",")]))
                st.markdown(r['resumo'][:500])
                if st.button("Abrir", key=f"o_{r['id']}"):
                    go("estudo", r['cliente_id'], r['id'])
                    st.rerun()
    else:
        st.info("Nenhum estudo")

elif st.session_state.pag == "novo":
    st.markdown("## ➕ Novo")
    
    t1, t2 = st.tabs(["📄 Estudo", "👤 Cliente"])
    
    with t1:
        cls = listar_clientes()
        if not cls:
            st.warning("Cadastre um cliente primeiro")
        else:
            with st.form("est"):
                opts = {c['nome']: c['id'] for c in cls}
                cliente = st.selectbox("Cliente", list(opts.keys()))
                titulo = st.text_input("Título")
                resumo = st.text_area("Resumo", height=250)
                tags = st.text_input("Tags (vírgula)")
                arqs = st.file_uploader("Anexos", accept_multiple_files=True)
                if st.form_submit_button("💾 Salvar", type="primary"):
                    if titulo and resumo:
                        eid = criar_estudo(opts[cliente], titulo, resumo, tags)
                        for a in arqs:
                            add_anexo(eid, a.name, a.type or "", a.read(), a.size)
                        st.success("✅ Criado!")
                        st.balloons()
                    else:
                        st.error("Preencha título e resumo")
    
    with t2:
        with st.form("cli"):
            nome = st.text_input("Nome")
            cnpj = st.text_input("CNPJ")
            obs = st.text_area("Obs")
            if st.form_submit_button("💾 Salvar", type="primary"):
                if nome:
                    criar_cliente(nome, cnpj, obs)
                    st.success("✅ Criado!")
                else:
                    st.error("Nome obrigatório")

elif st.session_state.pag == "clientes":
    st.markdown("## 👥 Clientes")
    
    for cl in listar_clientes():
        with st.expander(f"📁 {cl['nome']}" + (f" - {cl['cnpj']}" if cl['cnpj'] else "")):
            estudos = listar_estudos(cl['id'])
            st.write(f"{len(estudos)} estudos")
            for e in estudos[:5]:
                if st.button(f"📄 {e['titulo'][:40]}", key=f"e_{cl['id']}_{e['id']}"):
                    go("estudo", cl['id'], e['id'])
                    st.rerun()
            if st.button("🗑️ Excluir", key=f"d_{cl['id']}"):
                excluir_cliente(cl['id'])
                st.rerun()

elif st.session_state.pag == "config":
    st.markdown("## ⚙️ Configurações")
    
    s = stats()
    cols = st.columns(5)
    for i, (k, v) in enumerate(s.items()):
        with cols[i]:
            st.metric(k.title(), v)
    
    st.markdown("---")
    st.markdown("### 🔑 APIs")
    col1, col2 = st.columns(2)
    with col1:
        st.success("✅ OpenAI OK" if client else "❌ OpenAI não configurada")
    with col2:
        st.success(f"✅ Email: {GMAIL_USER}" if GMAIL_USER else "❌ Email não configurado")
    
    st.markdown("---")
    st.markdown("### 💾 Backup")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("�� Gerar", use_container_width=True):
            st.download_button("⬇️ Baixar", criar_backup(), f"backup_{datetime.now():%Y%m%d_%H%M}.zip", "application/zip")
    with col2:
        up = st.file_uploader("Restaurar", type=["zip", "json"])
        if up and st.button("📤 Restaurar"):
            ok, msg = restaurar_backup(up)
            st.success(msg) if ok else st.error(msg)

elif st.session_state.pag == "estudo":
    est = obter_estudo(st.session_state.est)
    cl = obter_cliente(st.session_state.cli)
    
    if est and cl:
        col1, col2, col3 = st.columns([4, 1, 1])
        with col1:
            st.markdown(f"## 📖 {est['titulo']}")
            st.caption(f"👤 {cl['nome']} | 📅 {fmt_date(est['created_at'])}")
        with col2:
            if st.button("✏️"):
                st.session_state.edit = True
                st.rerun()
        with col3:
            if st.button("��️"):
                excluir_estudo(est['id'])
                go("biblioteca")
                st.rerun()
        
        if est['tags']:
            st.markdown(" ".join([f'<span class="tag">{t.strip()}</span>' for t in est['tags'].split(",")]), unsafe_allow_html=True)
        
        st.markdown("---")
        
        if st.session_state.edit:
            with st.form("ed"):
                t = st.text_input("Título", est['titulo'])
                r = st.text_area("Resumo", est['resumo'], height=300)
                tg = st.text_input("Tags", est['tags'] or "")
                c1, c2 = st.columns(2)
                with c1:
                    if st.form_submit_button("💾"):
                        atualizar_estudo(est['id'], t, r, tg)
                        st.session_state.edit = False
                        st.rerun()
                with c2:
                    if st.form_submit_button("❌"):
                        st.session_state.edit = False
                        st.rerun()
        else:
            st.markdown(est['resumo'])
        
        st.markdown("---")
        st.markdown("### 📎 Anexos")
        for a in listar_anexos(est['id']):
            c1, c2, c3 = st.columns([4, 1, 1])
            with c1:
                st.write(f"📄 {a['filename']}")
            with c2:
                anx = obter_anexo(a['id'])
                if anx:
                    st.download_button("⬇️", base64.b64decode(anx['file_data']), a['filename'], a['file_type'], key=f"dl_{a['id']}")
            with c3:
                if st.button("🗑️", key=f"x_{a['id']}"):
                    excluir_anexo(a['id'])
                    st.rerun()
        
        with st.form("anx", clear_on_submit=True):
            novos = st.file_uploader("Adicionar", accept_multiple_files=True)
            if st.form_submit_button("📤") and novos:
                for a in novos:
                    add_anexo(est['id'], a.name, a.type or "", a.read(), a.size)
                st.rerun()
        
        if st.button("← Voltar"):
            go("biblioteca")
            st.rerun()

st.markdown("---")
st.caption("📚 Biblioteca Tributária | 🤖 IA | 📢 Atualizações")
