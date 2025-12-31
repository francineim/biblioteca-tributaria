import streamlit as st
import sqlite3
from datetime import datetime
from pathlib import Path
import base64
import json
import zipfile
import io
import requests
from openai import OpenAI

st.set_page_config(page_title="Biblioteca Tributária", page_icon="📚", layout="wide", initial_sidebar_state="expanded")
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "biblioteca.db"

# Configurar OpenAI
try:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except:
    client = None

st.markdown("""<style>
.main-header {font-size: 2.2rem; font-weight: bold; color: #1f4e79; margin-bottom: 1rem; text-align: center;}
.stat-card {background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 12px; padding: 1.5rem; color: white; text-align: center;}
.stat-number {font-size: 2.5rem; font-weight: bold;}
.stat-label {font-size: 0.9rem; opacity: 0.9;}
.tag {display: inline-block; background-color: #e3f2fd; color: #1565c0; padding: 0.2rem 0.6rem; border-radius: 15px; font-size: 0.8rem; margin-right: 0.3rem;}
.backup-box {background-color: #fff3cd; border: 1px solid #ffc107; border-radius: 8px; padding: 1rem; margin: 1rem 0;}
.chat-user {background-color: #e3f2fd; padding: 10px 15px; border-radius: 15px; margin: 5px 0; margin-left: 20%;}
.chat-assistant {background-color: #f0f0f0; padding: 10px 15px; border-radius: 15px; margin: 5px 0; margin-right: 20%;}
.fonte-oficial {background-color: #e8f5e9; border-left: 4px solid #4caf50; padding: 10px; margin: 5px 0; border-radius: 0 8px 8px 0;}
.material-sugerido {background-color: #fff3e0; border-left: 4px solid #ff9800; padding: 10px; margin: 5px 0; border-radius: 0 8px 8px 0;}
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
    c.execute("CREATE TABLE IF NOT EXISTS chat_historico (id INTEGER PRIMARY KEY AUTOINCREMENT, pergunta TEXT NOT NULL, resposta TEXT NOT NULL, fontes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    conn.close()

init_db()

# ==================== FUNÇÕES DO AGENTE ====================

FONTES_OFICIAIS = {
    "Receita Federal": "https://www.gov.br/receitafederal",
    "Planalto - Legislação": "https://www.planalto.gov.br/legislacao",
    "SEFAZ SC": "https://www.sef.sc.gov.br",
    "SEFAZ ES": "https://www.sefaz.es.gov.br",
    "SEFAZ MG": "https://www.fazenda.mg.gov.br",
    "SEFAZ SP": "https://portal.fazenda.sp.gov.br",
    "SEFAZ RJ": "https://www.fazenda.rj.gov.br",
    "SEFAZ PE": "https://www.sefaz.pe.gov.br",
    "SEFAZ CE": "https://www.sefaz.ce.gov.br",
}

def buscar_na_biblioteca(termo):
    """Busca estudos relacionados na biblioteca local"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT e.id, e.titulo, e.resumo, e.tags, c.nome as cliente_nome 
        FROM estudos e 
        JOIN clientes c ON e.cliente_id = c.id 
        WHERE e.titulo LIKE ? OR e.resumo LIKE ? OR e.tags LIKE ? OR c.nome LIKE ?
        ORDER BY e.created_at DESC LIMIT 5
    """, (f"%{termo}%", f"%{termo}%", f"%{termo}%", f"%{termo}%"))
    resultados = c.fetchall()
    conn.close()
    return resultados

def obter_contexto_biblioteca():
    """Obtém resumo de toda a biblioteca para contexto"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT e.titulo, e.resumo, e.tags, c.nome as cliente_nome 
        FROM estudos e 
        JOIN clientes c ON e.cliente_id = c.id 
        ORDER BY e.created_at DESC LIMIT 20
    """)
    estudos = c.fetchall()
    conn.close()
    
    if not estudos:
        return "A biblioteca está vazia."
    
    contexto = "ESTUDOS DISPONÍVEIS NA BIBLIOTECA:\n\n"
    for est in estudos:
        contexto += f"- **{est['titulo']}** (Cliente: {est['cliente_nome']})\n"
        contexto += f"  Tags: {est['tags'] or 'Sem tags'}\n"
        contexto += f"  Resumo: {est['resumo'][:200]}...\n\n"
    
    return contexto

def gerar_links_fontes(pergunta):
    """Gera links relevantes baseado na pergunta"""
    links = []
    pergunta_lower = pergunta.lower()
    
    # Sempre incluir fontes federais para questões tributárias
    links.append(("Receita Federal", FONTES_OFICIAIS["Receita Federal"]))
    links.append(("Legislação Federal", FONTES_OFICIAIS["Planalto - Legislação"]))
    
    # Detectar estados mencionados
    estados = {
        "sc": "SEFAZ SC", "santa catarina": "SEFAZ SC",
        "es": "SEFAZ ES", "espirito santo": "SEFAZ ES", "espírito santo": "SEFAZ ES",
        "mg": "SEFAZ MG", "minas": "SEFAZ MG", "minas gerais": "SEFAZ MG",
        "sp": "SEFAZ SP", "são paulo": "SEFAZ SP", "sao paulo": "SEFAZ SP",
        "rj": "SEFAZ RJ", "rio de janeiro": "SEFAZ RJ",
        "pe": "SEFAZ PE", "pernambuco": "SEFAZ PE",
        "ce": "SEFAZ CE", "ceará": "SEFAZ CE", "ceara": "SEFAZ CE",
    }
    
    for termo, sefaz in estados.items():
        if termo in pergunta_lower:
            links.append((sefaz, FONTES_OFICIAIS[sefaz]))
    
    # Se mencionar ICMS, IPI, ISS, etc., adicionar SEFAZ relevantes
    if any(imp in pergunta_lower for imp in ["icms", "difal", "substituição", "st", "antecipação"]):
        for sefaz in ["SEFAZ SP", "SEFAZ MG", "SEFAZ RJ"]:
            if (sefaz, FONTES_OFICIAIS[sefaz]) not in links:
                links.append((sefaz, FONTES_OFICIAIS[sefaz]))
    
    return links[:5]  # Máximo 5 links

def consultar_agente(pergunta):
    """Consulta o agente de IA com contexto da biblioteca"""
    if not client:
        return "❌ API Key da OpenAI não configurada.", [], []
    
    # Buscar materiais relacionados
    palavras = pergunta.split()
    materiais = []
    for palavra in palavras:
        if len(palavra) > 3:
            materiais.extend(buscar_na_biblioteca(palavra))
    
    # Remover duplicados
    materiais_unicos = []
    ids_vistos = set()
    for m in materiais:
        if m['id'] not in ids_vistos:
            materiais_unicos.append(m)
            ids_vistos.add(m['id'])
    
    # Obter contexto
    contexto = obter_contexto_biblioteca()
    
    # Gerar links de fontes oficiais
    fontes = gerar_links_fontes(pergunta)
    
    # Prompt do sistema
    system_prompt = f"""Você é um assistente especialista em tributação brasileira, integrado a uma biblioteca de estudos tributários.

SUA BASE DE CONHECIMENTO LOCAL:
{contexto}

FONTES OFICIAIS DISPONÍVEIS:
- Receita Federal (www.gov.br/receitafederal)
- Portal da Legislação - Planalto (www.planalto.gov.br)
- SEFAZ de diversos estados (SC, ES, MG, SP, RJ, PE, CE)

INSTRUÇÕES:
1. Responda de forma clara, objetiva e tecnicamente precisa
2. Se houver estudos relevantes na biblioteca, mencione-os
3. Cite a legislação aplicável (Lei, Decreto, IN, etc.)
4. Indique quando o usuário deve consultar as fontes oficiais para informações atualizadas
5. Se não souber algo com certeza, indique que o usuário deve verificar nas fontes oficiais
6. Use linguagem profissional mas acessível
7. Formate a resposta com markdown para melhor leitura

IMPORTANTE: Sempre alerte sobre a necessidade de verificar a legislação vigente, pois as normas tributárias mudam frequentemente."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": pergunta}
            ],
            max_tokens=2000,
            temperature=0.3
        )
        resposta = response.choices[0].message.content
        
        # Salvar no histórico
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO chat_historico (pergunta, resposta, fontes) VALUES (?, ?, ?)",
            (pergunta, resposta, json.dumps([f[0] for f in fontes]))
        )
        conn.commit()
        conn.close()
        
        return resposta, materiais_unicos[:3], fontes
    
    except Exception as e:
        return f"❌ Erro ao consultar: {str(e)}", [], []

def obter_historico_chat(limite=10):
    """Obtém histórico de conversas"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM chat_historico ORDER BY created_at DESC LIMIT ?", (limite,))
    historico = c.fetchall()
    conn.close()
    return historico

def limpar_historico():
    """Limpa histórico de conversas"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM chat_historico")
    conn.commit()
    conn.close()

# ==================== FUNÇÕES CRUD ====================

def criar_backup():
    backup_data = io.BytesIO()
    with zipfile.ZipFile(backup_data, 'w', zipfile.ZIP_DEFLATED) as zf:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM clientes")
        clientes = [dict(row) for row in c.fetchall()]
        c.execute("SELECT * FROM estudos")
        estudos = [dict(row) for row in c.fetchall()]
        c.execute("SELECT * FROM anexos")
        anexos = [dict(row) for row in c.fetchall()]
        c.execute("SELECT * FROM chat_historico")
        historico = [dict(row) for row in c.fetchall()]
        conn.close()
        backup_json = {"versao": "2.0", "data_backup": datetime.now().isoformat(), "clientes": clientes, "estudos": estudos, "anexos": anexos, "chat_historico": historico}
        zf.writestr("backup_data.json", json.dumps(backup_json, ensure_ascii=False, indent=2))
    backup_data.seek(0)
    return backup_data

def restaurar_backup(backup_file):
    try:
        content = backup_file.read()
        backup_file.seek(0)
        try:
            with zipfile.ZipFile(io.BytesIO(content), 'r') as zf:
                if "backup_data.json" in zf.namelist():
                    backup = json.loads(zf.read("backup_data.json"))
                else:
                    return False, "ZIP inválido"
        except zipfile.BadZipFile:
            try:
                backup = json.loads(content.decode('utf-8'))
            except:
                return False, "Arquivo inválido"
        conn = get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM anexos")
        c.execute("DELETE FROM estudos")
        c.execute("DELETE FROM clientes")
        c.execute("DELETE FROM chat_historico")
        for cl in backup.get("clientes", []):
            c.execute("INSERT INTO clientes (id, nome, cnpj, observacoes, created_at) VALUES (?, ?, ?, ?, ?)", (cl['id'], cl['nome'], cl.get('cnpj'), cl.get('observacoes'), cl.get('created_at')))
        for est in backup.get("estudos", []):
            c.execute("INSERT INTO estudos (id, cliente_id, titulo, resumo, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (est['id'], est['cliente_id'], est['titulo'], est['resumo'], est.get('tags'), est.get('created_at'), est.get('updated_at')))
        for anx in backup.get("anexos", []):
            c.execute("INSERT INTO anexos (id, estudo_id, filename, file_type, file_data, file_size, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (anx['id'], anx['estudo_id'], anx['filename'], anx['file_type'], anx['file_data'], anx.get('file_size'), anx.get('created_at')))
        for chat in backup.get("chat_historico", []):
            c.execute("INSERT INTO chat_historico (id, pergunta, resposta, fontes, created_at) VALUES (?, ?, ?, ?, ?)", (chat['id'], chat['pergunta'], chat['resposta'], chat.get('fontes'), chat.get('created_at')))
        conn.commit()
        conn.close()
        return True, f"Restaurado: {len(backup.get('clientes', []))} clientes, {len(backup.get('estudos', []))} estudos, {len(backup.get('anexos', []))} anexos"
    except Exception as e:
        return False, f"Erro: {str(e)}"

def criar_cliente(nome, cnpj=None, obs=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO clientes (nome, cnpj, observacoes) VALUES (?, ?, ?)", (nome, cnpj, obs))
    conn.commit()
    cid = c.lastrowid
    conn.close()
    return cid

def listar_clientes(busca=None):
    conn = get_conn()
    c = conn.cursor()
    if busca:
        c.execute("SELECT * FROM clientes WHERE nome LIKE ? OR cnpj LIKE ? ORDER BY nome", (f"%{busca}%", f"%{busca}%"))
    else:
        c.execute("SELECT * FROM clientes ORDER BY nome")
    r = c.fetchall()
    conn.close()
    return r

def obter_cliente(cid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM clientes WHERE id = ?", (cid,))
    r = c.fetchone()
    conn.close()
    return r

def excluir_cliente(cid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM anexos WHERE estudo_id IN (SELECT id FROM estudos WHERE cliente_id = ?)", (cid,))
    c.execute("DELETE FROM estudos WHERE cliente_id = ?", (cid,))
    c.execute("DELETE FROM clientes WHERE id = ?", (cid,))
    conn.commit()
    conn.close()

def criar_estudo(cid, titulo, resumo, tags=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO estudos (cliente_id, titulo, resumo, tags) VALUES (?, ?, ?, ?)", (cid, titulo, resumo, tags))
    conn.commit()
    eid = c.lastrowid
    conn.close()
    return eid

def listar_estudos(cid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM estudos WHERE cliente_id = ? ORDER BY created_at DESC", (cid,))
    r = c.fetchall()
    conn.close()
    return r

def obter_estudo(eid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM estudos WHERE id = ?", (eid,))
    r = c.fetchone()
    conn.close()
    return r

def atualizar_estudo(eid, titulo, resumo, tags):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE estudos SET titulo=?, resumo=?, tags=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (titulo, resumo, tags, eid))
    conn.commit()
    conn.close()

def excluir_estudo(eid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM anexos WHERE estudo_id = ?", (eid,))
    c.execute("DELETE FROM estudos WHERE id = ?", (eid,))
    conn.commit()
    conn.close()

def estudos_recentes(lim=5):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT e.*, c.nome as cliente_nome FROM estudos e JOIN clientes c ON e.cliente_id = c.id ORDER BY e.created_at DESC LIMIT ?", (lim,))
    r = c.fetchall()
    conn.close()
    return r

def buscar_estudos(termo):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT e.*, c.nome as cliente_nome FROM estudos e JOIN clientes c ON e.cliente_id = c.id WHERE e.titulo LIKE ? OR e.resumo LIKE ? OR e.tags LIKE ? OR c.nome LIKE ? ORDER BY e.created_at DESC", (f"%{termo}%", f"%{termo}%", f"%{termo}%", f"%{termo}%"))
    r = c.fetchall()
    conn.close()
    return r

def add_anexo(eid, fname, ftype, fdata, fsize):
    conn = get_conn()
    c = conn.cursor()
    fb64 = base64.b64encode(fdata).decode('utf-8')
    c.execute("INSERT INTO anexos (estudo_id, filename, file_type, file_data, file_size) VALUES (?, ?, ?, ?, ?)", (eid, fname, ftype, fb64, fsize))
    conn.commit()
    conn.close()

def listar_anexos(eid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, filename, file_type, file_size, created_at FROM anexos WHERE estudo_id = ?", (eid,))
    r = c.fetchall()
    conn.close()
    return r

def obter_anexo(aid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM anexos WHERE id = ?", (aid,))
    r = c.fetchone()
    conn.close()
    return r

def excluir_anexo(aid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM anexos WHERE id = ?", (aid,))
    conn.commit()
    conn.close()

def stats():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM clientes")
    tc = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM estudos")
    te = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM anexos")
    ta = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM chat_historico")
    th = c.fetchone()[0]
    conn.close()
    return {"clientes": tc, "estudos": te, "anexos": ta, "consultas": th}

def fmt_date(d):
    if not d: return "N/A"
    try: return datetime.fromisoformat(str(d)).strftime("%d/%m/%Y %H:%M")
    except: return str(d)

def file_icon(ft):
    icons = {"application/pdf": "📕", "application/vnd.ms-excel": "📊", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "📊", "text/plain": "📝", "image/png": "🖼️", "image/jpeg": "🖼️"}
    return icons.get(ft, "📎")

def fmt_size(s):
    if not s: return "N/A"
    if s < 1024: return f"{s} B"
    elif s < 1048576: return f"{s/1024:.1f} KB"
    return f"{s/1048576:.1f} MB"

# ==================== ESTADO ====================

if "pag" not in st.session_state: st.session_state.pag = "home"
if "cli" not in st.session_state: st.session_state.cli = None
if "est" not in st.session_state: st.session_state.est = None
if "edit" not in st.session_state: st.session_state.edit = False
if "chat_resposta" not in st.session_state: st.session_state.chat_resposta = None
if "chat_materiais" not in st.session_state: st.session_state.chat_materiais = []
if "chat_fontes" not in st.session_state: st.session_state.chat_fontes = []

def go(p, c=None, e=None):
    st.session_state.pag = p
    st.session_state.cli = c
    st.session_state.est = e
    st.session_state.edit = False

# ==================== SIDEBAR ====================

with st.sidebar:
    st.markdown("## 📚 Biblioteca Tributária")
    st.markdown("---")
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🏠 Início", use_container_width=True): go("home")
    with c2:
        if st.button("➕ Novo", use_container_width=True): go("novo")
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🤖 Consultar", use_container_width=True): go("agente")
    with c2:
        if st.button("⚙️ Backup", use_container_width=True): go("config")
    
    st.markdown("---")
    busca = st.text_input("🔍 Buscar", placeholder="Cliente, estudo ou tag...")
    if busca:
        st.markdown("### 📋 Resultados")
        res = buscar_estudos(busca)
        if res:
            for r in res[:10]:
                if st.button(f"📄 {r['titulo'][:30]}...", key=f"b_{r['id']}", use_container_width=True): go("estudo", r['cliente_id'], r['id'])
        else: st.info("Nenhum resultado")
    else:
        st.markdown("### 👥 Clientes")
        cls = listar_clientes()
        if not cls: st.info("Nenhum cliente")
        for cl in cls:
            with st.expander(f"📁 {cl['nome']}", expanded=st.session_state.cli == cl['id']):
                if st.button("👁️ Ver", key=f"v_{cl['id']}", use_container_width=True): go("cliente", cl['id'])
                for es in listar_estudos(cl['id'])[:5]:
                    t = es['titulo'][:25] + "..." if len(es['titulo']) > 25 else es['titulo']
                    if st.button(f"�� {t}", key=f"e_{es['id']}", use_container_width=True): go("estudo", cl['id'], es['id'])

# ==================== PÁGINAS ====================

if st.session_state.pag == "home":
    st.markdown('<h1 class="main-header">📚 Biblioteca de Estudos Tributários</h1>', unsafe_allow_html=True)
    s = stats()
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(f'<div class="stat-card"><div class="stat-number">{s["clientes"]}</div><div class="stat-label">👥 Clientes</div></div>', unsafe_allow_html=True)
    with c2: st.markdown(f'<div class="stat-card"><div class="stat-number">{s["estudos"]}</div><div class="stat-label">📄 Estudos</div></div>', unsafe_allow_html=True)
    with c3: st.markdown(f'<div class="stat-card"><div class="stat-number">{s["anexos"]}</div><div class="stat-label">📎 Anexos</div></div>', unsafe_allow_html=True)
    with c4: st.markdown(f'<div class="stat-card"><div class="stat-number">{s["consultas"]}</div><div class="stat-label">🤖 Consultas</div></div>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Acesso rápido ao Agente
    st.markdown("### 🤖 Consulta Rápida")
    pergunta_rapida = st.text_input("Faça uma pergunta tributária...", placeholder="Ex: Como funciona o ICMS-ST em SP?", key="pergunta_home")
    if pergunta_rapida:
        if st.button("🔍 Consultar", key="btn_consulta_rapida"):
            go("agente")
            st.session_state.pergunta_inicial = pergunta_rapida
            st.rerun()
    
    st.markdown("---")
    st.markdown("### 📅 Estudos Recentes")
    rec = estudos_recentes(5)
    if rec:
        for r in rec:
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**{r['titulo']}**")
                st.caption(f"👤 {r['cliente_nome']} | 📅 {fmt_date(r['created_at'])}")
                if r['tags']: st.markdown(" ".join([f'<span class="tag">{t.strip()}</span>' for t in r['tags'].split(",")]), unsafe_allow_html=True)
            with c2:
                if st.button("Abrir", key=f"a_{r['id']}"): go("estudo", r['cliente_id'], r['id'])
            st.markdown("---")
    else: st.info("Nenhum estudo. Clique em '➕ Novo' para começar!")

elif st.session_state.pag == "agente":
    st.markdown("## 🤖 Consultor Tributário IA")
    st.markdown("Faça perguntas sobre tributação. O agente consulta sua biblioteca e fontes oficiais.")
    
    # Status da API
    if client:
        st.success("✅ OpenAI conectada")
    else:
        st.error("❌ API Key não configurada. Adicione em .streamlit/secrets.toml")
    
    st.markdown("---")
    
    # Formulário de pergunta
    with st.form("form_pergunta", clear_on_submit=True):
        pergunta = st.text_area(
            "💬 Sua pergunta:", 
            placeholder="Ex: Qual a alíquota de ICMS para venda interestadual de SP para MG?\nOu: Tenho algum estudo sobre substituição tributária?",
            height=100,
            value=st.session_state.get("pergunta_inicial", "")
        )
        
        col1, col2 = st.columns([3, 1])
        with col1:
            submit = st.form_submit_button("🔍 Consultar", use_container_width=True, type="primary")
        with col2:
            if st.form_submit_button("🗑️ Limpar", use_container_width=True):
                st.session_state.chat_resposta = None
                st.session_state.chat_materiais = []
                st.session_state.chat_fontes = []
                st.rerun()
    
    # Limpar pergunta inicial após uso
    if "pergunta_inicial" in st.session_state:
        del st.session_state.pergunta_inicial
    
    # Processar pergunta
    if submit and pergunta:
        with st.spinner("🔄 Consultando base de conhecimento e fontes oficiais..."):
            resposta, materiais, fontes = consultar_agente(pergunta)
            st.session_state.chat_resposta = resposta
            st.session_state.chat_materiais = materiais
            st.session_state.chat_fontes = fontes
    
    # Exibir resposta
    if st.session_state.chat_resposta:
        st.markdown("### 💡 Resposta")
        st.markdown(st.session_state.chat_resposta)
        
        # Materiais da biblioteca
        if st.session_state.chat_materiais:
            st.markdown("---")
            st.markdown("### 📚 Materiais Relacionados na Biblioteca")
            for mat in st.session_state.chat_materiais:
                st.markdown(f"""
                <div class="material-sugerido">
                    <strong>📄 {mat['titulo']}</strong><br>
                    <small>Cliente: {mat['cliente_nome']} | Tags: {mat['tags'] or 'Sem tags'}</small><br>
                    <small>{mat['resumo'][:150]}...</small>
                </div>
                """, unsafe_allow_html=True)
                if st.button(f"Abrir estudo", key=f"abrir_mat_{mat['id']}"):
                    # Buscar cliente_id
                    conn = get_conn()
                    c = conn.cursor()
                    c.execute("SELECT cliente_id FROM estudos WHERE id = ?", (mat['id'],))
                    cli_id = c.fetchone()[0]
                    conn.close()
                    go("estudo", cli_id, mat['id'])
                    st.rerun()
        
        # Fontes oficiais
        if st.session_state.chat_fontes:
            st.markdown("---")
            st.markdown("### 🔗 Fontes Oficiais para Consulta")
            for nome, url in st.session_state.chat_fontes:
                st.markdown(f"""
                <div class="fonte-oficial">
                    <strong>🏛️ {nome}</strong><br>
                    <a href="{url}" target="_blank">{url}</a>
                </div>
                """, unsafe_allow_html=True)
    
    # Histórico
    st.markdown("---")
    with st.expander("📜 Histórico de Consultas"):
        historico = obter_historico_chat(10)
        if historico:
            for h in historico:
                st.markdown(f"**🗣️ {h['pergunta'][:100]}...**")
                st.caption(f"📅 {fmt_date(h['created_at'])}")
                st.markdown("---")
            if st.button("🗑️ Limpar Histórico"):
                limpar_historico()
                st.success("Histórico limpo!")
                st.rerun()
        else:
            st.info("Nenhuma consulta realizada ainda.")

elif st.session_state.pag == "novo":
    st.markdown("## ➕ Novo Cadastro")
    t1, t2 = st.tabs(["👤 Novo Cliente", "📄 Novo Estudo"])
    with t1:
        with st.form("fc"):
            nome = st.text_input("Nome do Cliente *")
            cnpj = st.text_input("CNPJ")
            obs = st.text_area("Observações")
            if st.form_submit_button("💾 Salvar"):
                if not nome: st.error("Nome obrigatório!")
                else:
                    criar_cliente(nome, cnpj, obs)
                    st.success(f"✅ Cliente '{nome}' cadastrado!")
                    st.balloons()
    with t2:
        cls = listar_clientes()
        if not cls: st.warning("⚠️ Cadastre um cliente primeiro!")
        else:
            with st.form("fe"):
                opts = {c['nome']: c['id'] for c in cls}
                cn = st.selectbox("Cliente *", list(opts.keys()))
                tit = st.text_input("Título *")
                res = st.text_area("Resumo da Operação *", height=250)
                tags = st.text_input("Tags (separadas por vírgula)", placeholder="ICMS, ST, SP, MG")
                arqs = st.file_uploader("📎 Anexos", accept_multiple_files=True, type=["pdf", "xls", "xlsx", "doc", "docx", "txt", "csv", "png", "jpg", "jpeg"])
                if st.form_submit_button("💾 Salvar"):
                    if not tit or not res: st.error("Título e Resumo obrigatórios!")
                    else:
                        eid = criar_estudo(opts[cn], tit, res, tags)
                        if arqs:
                            for a in arqs: add_anexo(eid, a.name, a.type or "application/octet-stream", a.read(), a.size)
                        st.success(f"✅ Estudo '{tit}' criado!")
                        st.balloons()

elif st.session_state.pag == "config":
    st.markdown("## ⚙️ Configurações")
    
    tab1, tab2 = st.tabs(["💾 Backup", "🔑 API"])
    
    with tab1:
        st.markdown('<div class="backup-box">⚠️ <strong>Importante:</strong> Faça backup regularmente!</div>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### 📥 Criar Backup")
            if st.button("🔄 Gerar Backup", use_container_width=True):
                backup_zip = criar_backup()
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button("⬇️ Baixar Backup", backup_zip, f"backup_biblioteca_{ts}.zip", "application/zip", use_container_width=True)
                st.success("✅ Backup gerado!")
        with col2:
            st.markdown("#### 📤 Restaurar Backup")
            up = st.file_uploader("Arquivo .zip ou .json", type=["zip", "json"])
            if up:
                if st.button("🔄 Restaurar", use_container_width=True, type="primary"):
                    ok, msg = restaurar_backup(up)
                    if ok:
                        st.success(f"✅ {msg}")
                        st.balloons()
                    else:
                        st.error(f"❌ {msg}")
    
    with tab2:
        st.markdown("#### 🔑 Status da API OpenAI")
        if client:
            st.success("✅ API Key configurada e funcionando")
        else:
            st.error("❌ API Key não configurada")
            st.markdown("""
            Para configurar:
            1. Crie o arquivo `.streamlit/secrets.toml`
            2. Adicione: `OPENAI_API_KEY = "sua-chave-aqui"`
            """)
    
    st.markdown("---")
    st.markdown("### 📊 Estatísticas")
    s = stats()
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("Clientes", s["clientes"])
    with c2: st.metric("Estudos", s["estudos"])
    with c3: st.metric("Anexos", s["anexos"])
    with c4: st.metric("Consultas IA", s["consultas"])

elif st.session_state.pag == "cliente":
    cl = obter_cliente(st.session_state.cli)
    if cl:
        c1, c2 = st.columns([4, 1])
        with c1:
            st.markdown(f"## 📁 {cl['nome']}")
            if cl['cnpj']: st.caption(f"CNPJ: {cl['cnpj']}")
        with c2:
            if st.button("🗑️ Excluir"):
                excluir_cliente(cl['id'])
                go("home")
                st.rerun()
        if cl['observacoes']: st.info(cl['observacoes'])
        st.markdown("---")
        ests = listar_estudos(cl['id'])
        if ests:
            st.markdown(f"### 📚 Estudos ({len(ests)})")
            for e in ests:
                c1, c2 = st.columns([4, 1])
                with c1:
                    st.markdown(f"#### {e['titulo']}")
                    st.caption(f"📅 {fmt_date(e['created_at'])}")
                    if e['tags']: st.markdown(" ".join([f'<span class="tag">{t.strip()}</span>' for t in e['tags'].split(",")]), unsafe_allow_html=True)
                with c2:
                    if st.button("📖 Abrir", key=f"ae_{e['id']}"): go("estudo", cl['id'], e['id'])
                st.markdown("---")
        else: st.info("Nenhum estudo.")

elif st.session_state.pag == "estudo":
    est = obter_estudo(st.session_state.est)
    cl = obter_cliente(st.session_state.cli)
    if est and cl:
        c1, c2, c3 = st.columns([3, 1, 1])
        with c1:
            st.markdown(f"## 📖 {est['titulo']}")
            st.caption(f"👤 {cl['nome']} | 📅 {fmt_date(est['created_at'])}")
        with c2:
            if st.button("✏️ Editar"):
                st.session_state.edit = True
                st.rerun()
        with c3:
            if st.button("🗑️ Excluir"):
                excluir_estudo(est['id'])
                go("cliente", cl['id'])
                st.rerun()
        if est['tags']: st.markdown(" ".join([f'<span class="tag">{t.strip()}</span>' for t in est['tags'].split(",")]), unsafe_allow_html=True)
        st.markdown("---")
        if st.session_state.edit:
            with st.form("fed"):
                nt = st.text_input("Título", value=est['titulo'])
                nr = st.text_area("Resumo", value=est['resumo'], height=300)
                ntg = st.text_input("Tags", value=est['tags'] or "")
                c1, c2 = st.columns(2)
                with c1:
                    if st.form_submit_button("💾 Salvar"):
                        atualizar_estudo(est['id'], nt, nr, ntg)
                        st.session_state.edit = False
                        st.rerun()
                with c2:
                    if st.form_submit_button("❌ Cancelar"):
                        st.session_state.edit = False
                        st.rerun()
        else:
            st.markdown("### 📋 Resumo")
            st.markdown(est['resumo'])
        
        st.markdown("---")
        st.markdown("### 📎 Anexos")
        anxs = listar_anexos(est['id'])
        if anxs:
            for a in anxs:
                c1, c2, c3, c4 = st.columns([0.5, 3, 1, 0.5])
                with c1: st.markdown(file_icon(a['file_type']))
                with c2: st.markdown(f"**{a['filename']}** ({fmt_size(a['file_size'])})")
                with c3:
                    ac = obter_anexo(a['id'])
                    if ac: st.download_button("⬇️", base64.b64decode(ac['file_data']), a['filename'], a['file_type'], key=f"d_{a['id']}")
                with c4:
                    if st.button("🗑️", key=f"x_{a['id']}"):
                        excluir_anexo(a['id'])
                        st.rerun()
        else: 
            st.info("Nenhum anexo")
        
        st.markdown("---")
        st.markdown("#### ➕ Adicionar Novos Anexos")
        with st.form("form_novos_anexos", clear_on_submit=True):
            novos_arquivos = st.file_uploader(
                "Selecione os arquivos", 
                accept_multiple_files=True, 
                type=["pdf", "xls", "xlsx", "doc", "docx", "txt", "png", "jpg", "jpeg"],
                key="upload_novos"
            )
            submit_upload = st.form_submit_button("📤 Enviar Arquivos", use_container_width=True)
            
            if submit_upload and novos_arquivos:
                for arq in novos_arquivos:
                    file_content = arq.read()
                    add_anexo(
                        est['id'], 
                        arq.name, 
                        arq.type or "application/octet-stream", 
                        file_content, 
                        len(file_content)
                    )
                st.success(f"✅ {len(novos_arquivos)} arquivo(s) adicionado(s)!")
                st.rerun()

st.markdown("---")
st.caption("📚 Biblioteca de Estudos Tributários | 🤖 Agente IA Integrado")
