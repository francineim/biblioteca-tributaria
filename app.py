import streamlit as st
import sqlite3
from datetime import datetime
from pathlib import Path
import base64
import json
import zipfile
import io
from openai import OpenAI

st.set_page_config(page_title="Biblioteca Tributária", page_icon="📚", layout="wide", initial_sidebar_state="collapsed")
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "biblioteca.db"

# Configurar OpenAI
try:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except:
    client = None

st.markdown("""<style>
/* Geral */
.main-header {font-size: 2.5rem; font-weight: bold; color: #1f4e79; margin-bottom: 0.5rem; text-align: center;}
.sub-header {font-size: 1.1rem; color: #666; text-align: center; margin-bottom: 2rem;}

/* Cards de estatísticas */
.stat-card {background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 12px; padding: 1.5rem; color: white; text-align: center;}
.stat-number {font-size: 2.5rem; font-weight: bold;}
.stat-label {font-size: 0.9rem; opacity: 0.9;}

/* Tags */
.tag {display: inline-block; background-color: #e3f2fd; color: #1565c0; padding: 0.2rem 0.6rem; border-radius: 15px; font-size: 0.8rem; margin-right: 0.3rem; margin-bottom: 0.3rem;}

/* Chat */
.chat-container {max-width: 900px; margin: 0 auto; padding: 20px;}
.user-message {background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 15px 20px; border-radius: 20px 20px 5px 20px; margin: 10px 0; margin-left: 15%;}
.assistant-message {background-color: #f7f7f8; padding: 15px 20px; border-radius: 20px 20px 20px 5px; margin: 10px 0; margin-right: 15%; border: 1px solid #e5e5e5;}
.fonte-card {background-color: #f0f9ff; border-left: 4px solid #0ea5e9; padding: 12px 15px; margin: 8px 0; border-radius: 0 8px 8px 0;}
.fonte-card a {color: #0369a1; text-decoration: none; font-weight: 500;}
.fonte-card a:hover {text-decoration: underline;}
.biblioteca-card {background-color: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px 15px; margin: 8px 0; border-radius: 0 8px 8px 0;}

/* Input de chat */
.stTextArea textarea {font-size: 16px !important; border-radius: 15px !important;}

/* Botões */
.stButton button {border-radius: 10px !important;}

/* Backup */
.backup-box {background-color: #fff3cd; border: 1px solid #ffc107; border-radius: 8px; padding: 1rem; margin: 1rem 0;}

/* Esconder menu hamburguer quando sidebar está collapsed */
section[data-testid="stSidebar"][aria-expanded="false"] {display: none;}
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
    conn.commit()
    conn.close()

init_db()

# ==================== FONTES OFICIAIS ====================

FONTES_OFICIAIS = {
    "Receita Federal": {
        "url": "https://www.gov.br/receitafederal",
        "descricao": "Tributos federais, IRPJ, CSLL, PIS, COFINS, IPI"
    },
    "Planalto - Legislação": {
        "url": "https://www.planalto.gov.br/ccivil_03/leis/",
        "descricao": "Leis federais, Código Tributário Nacional"
    },
    "Portal da Reforma Tributária": {
        "url": "https://www.gov.br/fazenda/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria",
        "descricao": "Informações oficiais sobre a Reforma Tributária"
    },
    "SEFAZ SC": {
        "url": "https://www.sef.sc.gov.br",
        "descricao": "ICMS Santa Catarina, TTD, benefícios fiscais"
    },
    "SEFAZ ES": {
        "url": "https://www.sefaz.es.gov.br",
        "descricao": "ICMS Espírito Santo, INVEST-ES"
    },
    "SEFAZ MG": {
        "url": "https://www.fazenda.mg.gov.br",
        "descricao": "ICMS Minas Gerais, RICMS/MG"
    },
    "SEFAZ SP": {
        "url": "https://portal.fazenda.sp.gov.br",
        "descricao": "ICMS São Paulo, RICMS/SP, ST"
    },
    "SEFAZ RJ": {
        "url": "https://www.fazenda.rj.gov.br",
        "descricao": "ICMS Rio de Janeiro"
    },
    "SEFAZ PE": {
        "url": "https://www.sefaz.pe.gov.br",
        "descricao": "ICMS Pernambuco"
    },
    "SEFAZ CE": {
        "url": "https://www.sefaz.ce.gov.br",
        "descricao": "ICMS Ceará"
    },
    "CONFAZ": {
        "url": "https://www.confaz.fazenda.gov.br",
        "descricao": "Convênios ICMS, protocolos, ajustes SINIEF"
    },
    "STF - Supremo Tribunal Federal": {
        "url": "https://portal.stf.jus.br",
        "descricao": "Jurisprudência tributária, ADIs"
    },
    "STJ - Superior Tribunal de Justiça": {
        "url": "https://www.stj.jus.br",
        "descricao": "Jurisprudência tributária, REsp"
    },
}

def buscar_na_biblioteca(pergunta):
    """Busca estudos relacionados na biblioteca local"""
    conn = get_conn()
    c = conn.cursor()
    
    # Extrair palavras-chave
    palavras = [p.strip().lower() for p in pergunta.split() if len(p) > 3]
    
    resultados = []
    ids_vistos = set()
    
    for palavra in palavras:
        c.execute("""
            SELECT e.id, e.titulo, e.resumo, e.tags, c.nome as cliente_nome 
            FROM estudos e 
            JOIN clientes c ON e.cliente_id = c.id 
            WHERE LOWER(e.titulo) LIKE ? OR LOWER(e.resumo) LIKE ? OR LOWER(e.tags) LIKE ?
            ORDER BY e.created_at DESC LIMIT 5
        """, (f"%{palavra}%", f"%{palavra}%", f"%{palavra}%"))
        
        for row in c.fetchall():
            if row['id'] not in ids_vistos:
                resultados.append(dict(row))
                ids_vistos.add(row['id'])
    
    conn.close()
    return resultados[:5]

def identificar_fontes_relevantes(pergunta):
    """Identifica fontes oficiais relevantes para a pergunta"""
    pergunta_lower = pergunta.lower()
    fontes = []
    
    # Palavras-chave para cada fonte
    mapeamento = {
        "reforma tributária": ["Portal da Reforma Tributária", "Receita Federal", "Planalto - Legislação"],
        "reforma": ["Portal da Reforma Tributária", "Receita Federal"],
        "ibs": ["Portal da Reforma Tributária", "CONFAZ"],
        "cbs": ["Portal da Reforma Tributária", "Receita Federal"],
        "split payment": ["Portal da Reforma Tributária"],
        "icms": ["CONFAZ"],
        "icms sc": ["SEFAZ SC", "CONFAZ"],
        "icms es": ["SEFAZ ES", "CONFAZ"],
        "icms mg": ["SEFAZ MG", "CONFAZ"],
        "icms sp": ["SEFAZ SP", "CONFAZ"],
        "icms rj": ["SEFAZ RJ", "CONFAZ"],
        "icms pe": ["SEFAZ PE", "CONFAZ"],
        "icms ce": ["SEFAZ CE", "CONFAZ"],
        "santa catarina": ["SEFAZ SC"],
        "espírito santo": ["SEFAZ ES"],
        "espirito santo": ["SEFAZ ES"],
        "minas gerais": ["SEFAZ MG"],
        "são paulo": ["SEFAZ SP"],
        "sao paulo": ["SEFAZ SP"],
        "rio de janeiro": ["SEFAZ RJ"],
        "pernambuco": ["SEFAZ PE"],
        "ceará": ["SEFAZ CE"],
        "ceara": ["SEFAZ CE"],
        "pis": ["Receita Federal"],
        "cofins": ["Receita Federal"],
        "irpj": ["Receita Federal"],
        "csll": ["Receita Federal"],
        "ipi": ["Receita Federal"],
        "federal": ["Receita Federal", "Planalto - Legislação"],
        "lei": ["Planalto - Legislação"],
        "decreto": ["Planalto - Legislação"],
        "convênio": ["CONFAZ"],
        "protocolo": ["CONFAZ"],
        "substituição tributária": ["CONFAZ", "SEFAZ SP"],
        "st": ["CONFAZ"],
        "difal": ["CONFAZ"],
        "stf": ["STF - Supremo Tribunal Federal"],
        "supremo": ["STF - Supremo Tribunal Federal"],
        "stj": ["STJ - Superior Tribunal de Justiça"],
        "jurisprudência": ["STF - Supremo Tribunal Federal", "STJ - Superior Tribunal de Justiça"],
    }
    
    fontes_adicionadas = set()
    
    for termo, lista_fontes in mapeamento.items():
        if termo in pergunta_lower:
            for fonte in lista_fontes:
                if fonte not in fontes_adicionadas:
                    fontes.append({
                        "nome": fonte,
                        "url": FONTES_OFICIAIS[fonte]["url"],
                        "descricao": FONTES_OFICIAIS[fonte]["descricao"]
                    })
                    fontes_adicionadas.add(fonte)
    
    # Sempre adicionar Receita Federal e Planalto para questões tributárias
    if not fontes:
        fontes.append({
            "nome": "Receita Federal",
            "url": FONTES_OFICIAIS["Receita Federal"]["url"],
            "descricao": FONTES_OFICIAIS["Receita Federal"]["descricao"]
        })
        fontes.append({
            "nome": "Planalto - Legislação",
            "url": FONTES_OFICIAIS["Planalto - Legislação"]["url"],
            "descricao": FONTES_OFICIAIS["Planalto - Legislação"]["descricao"]
        })
    
    return fontes[:6]

def obter_contexto_biblioteca():
    """Obtém resumo da biblioteca para contexto"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT e.titulo, e.resumo, e.tags, c.nome as cliente_nome 
        FROM estudos e 
        JOIN clientes c ON e.cliente_id = c.id 
        ORDER BY e.created_at DESC LIMIT 15
    """)
    estudos = c.fetchall()
    conn.close()
    
    if not estudos:
        return "Biblioteca vazia - nenhum estudo cadastrado ainda."
    
    contexto = ""
    for est in estudos:
        contexto += f"• {est['titulo']} (Cliente: {est['cliente_nome']}, Tags: {est['tags'] or 'sem tags'})\n"
    
    return contexto

def consultar_agente(pergunta, historico_mensagens):
    """Consulta o agente de IA"""
    if not client:
        return "❌ API Key da OpenAI não configurada. Vá em Configurações para verificar.", [], []
    
    # Buscar na biblioteca
    materiais = buscar_na_biblioteca(pergunta)
    
    # Identificar fontes relevantes
    fontes = identificar_fontes_relevantes(pergunta)
    
    # Contexto da biblioteca
    contexto_biblioteca = obter_contexto_biblioteca()
    
    # Montar contexto dos materiais encontrados
    contexto_materiais = ""
    if materiais:
        contexto_materiais = "\n\nMATERIAIS ENCONTRADOS NA BIBLIOTECA DO USUÁRIO:\n"
        for m in materiais:
            contexto_materiais += f"\n📄 **{m['titulo']}** (Cliente: {m['cliente_nome']})\n"
            contexto_materiais += f"   Resumo: {m['resumo'][:300]}...\n"
    
    system_prompt = f"""Você é um assistente especialista em tributação brasileira, similar ao ChatGPT, integrado a uma biblioteca de estudos tributários.

BIBLIOTECA DO USUÁRIO (estudos cadastrados):
{contexto_biblioteca}
{contexto_materiais}

SUAS CAPACIDADES:
1. Responder perguntas sobre tributação brasileira (ICMS, PIS, COFINS, IRPJ, CSLL, IPI, ISS, etc.)
2. Explicar a Reforma Tributária (EC 132/2023, IBS, CBS, IS)
3. Consultar e recomendar estudos da biblioteca do usuário
4. Indicar fontes oficiais para consulta atualizada
5. Explicar legislação, jurisprudência e procedimentos fiscais

INSTRUÇÕES DE RESPOSTA:
- Seja claro, objetivo e didático
- Use linguagem profissional mas acessível
- Estruture a resposta com tópicos quando apropriado
- Se houver materiais relevantes na biblioteca, mencione-os naturalmente
- Sempre indique que o usuário deve verificar a legislação vigente
- Cite leis, decretos e normas quando relevante
- Use markdown para formatar (negrito, listas, etc.)

IMPORTANTE: 
- Você tem conhecimento até sua data de corte, mas a legislação tributária muda frequentemente
- Sempre recomende consultar as fontes oficiais para informações atualizadas
- Se não souber algo com certeza, seja honesto e indique onde buscar"""

    try:
        # Preparar mensagens
        messages = [{"role": "system", "content": system_prompt}]
        
        # Adicionar histórico (últimas 10 mensagens)
        for msg in historico_mensagens[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        
        # Adicionar pergunta atual
        messages.append({"role": "user", "content": pergunta})
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=2500,
            temperature=0.4
        )
        
        resposta = response.choices[0].message.content
        return resposta, materiais, fontes
    
    except Exception as e:
        return f"❌ Erro ao consultar: {str(e)}", [], []

def salvar_mensagem(role, content, fontes=None):
    """Salva mensagem no histórico"""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO chat_historico (role, content, fontes) VALUES (?, ?, ?)",
        (role, content, json.dumps(fontes) if fontes else None)
    )
    conn.commit()
    conn.close()

def obter_historico():
    """Obtém histórico de mensagens"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT role, content, fontes, created_at FROM chat_historico ORDER BY created_at ASC")
    historico = [{"role": r["role"], "content": r["content"], "fontes": r["fontes"], "created_at": r["created_at"]} for r in c.fetchall()]
    conn.close()
    return historico

def limpar_historico():
    """Limpa histórico"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM chat_historico")
    conn.commit()
    conn.close()

# ==================== FUNÇÕES CRUD (mantidas) ====================

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
            c.execute("INSERT INTO chat_historico (id, role, content, fontes, created_at) VALUES (?, ?, ?, ?, ?)", (chat['id'], chat['role'], chat['content'], chat.get('fontes'), chat.get('created_at')))
        conn.commit()
        conn.close()
        return True, f"Restaurado com sucesso!"
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
    c.execute("SELECT COUNT(*) FROM chat_historico WHERE role='user'")
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

if "pag" not in st.session_state: st.session_state.pag = "chat"
if "cli" not in st.session_state: st.session_state.cli = None
if "est" not in st.session_state: st.session_state.est = None
if "edit" not in st.session_state: st.session_state.edit = False
if "ultima_resposta" not in st.session_state: st.session_state.ultima_resposta = None
if "ultimos_materiais" not in st.session_state: st.session_state.ultimos_materiais = []
if "ultimas_fontes" not in st.session_state: st.session_state.ultimas_fontes = []

def go(p, c=None, e=None):
    st.session_state.pag = p
    st.session_state.cli = c
    st.session_state.est = e
    st.session_state.edit = False

# ==================== NAVEGAÇÃO SUPERIOR ====================

col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 2])
with col1:
    if st.button("🤖 Consultor IA", use_container_width=True, type="primary" if st.session_state.pag == "chat" else "secondary"):
        go("chat")
with col2:
    if st.button("📚 Biblioteca", use_container_width=True, type="primary" if st.session_state.pag == "biblioteca" else "secondary"):
        go("biblioteca")
with col3:
    if st.button("➕ Novo Estudo", use_container_width=True, type="primary" if st.session_state.pag == "novo" else "secondary"):
        go("novo")
with col4:
    if st.button("👥 Clientes", use_container_width=True, type="primary" if st.session_state.pag == "clientes" else "secondary"):
        go("clientes")
with col5:
    if st.button("⚙️ Config", use_container_width=True, type="primary" if st.session_state.pag == "config" else "secondary"):
        go("config")

st.markdown("---")

# ==================== PÁGINAS ====================

if st.session_state.pag == "chat":
    st.markdown('<h1 class="main-header">🤖 Consultor Tributário IA</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Pergunte sobre tributação, reforma tributária, ICMS, PIS/COFINS e muito mais.<br>Busco na sua biblioteca e em fontes oficiais.</p>', unsafe_allow_html=True)
    
    # Container do chat
    chat_container = st.container()
    
    # Obter histórico
    historico = obter_historico()
    
    # Exibir histórico de mensagens
    with chat_container:
        for msg in historico[-20:]:  # Últimas 20 mensagens
            if msg["role"] == "user":
                st.markdown(f'<div class="user-message">🧑 {msg["content"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="assistant-message">{msg["content"]}</div>', unsafe_allow_html=True)
                
                # Exibir fontes se houver
                if msg.get("fontes"):
                    try:
                        fontes = json.loads(msg["fontes"])
                        if fontes:
                            st.markdown("**🔗 Fontes consultadas:**")
                            for f in fontes:
                                st.markdown(f'<div class="fonte-card"><a href="{f["url"]}" target="_blank">🏛️ {f["nome"]}</a> - {f["descricao"]}</div>', unsafe_allow_html=True)
                    except:
                        pass
    
    st.markdown("---")
    
    # Campo de input fixo no final
    st.markdown("### 💬 Faça sua pergunta")
    
    with st.form("chat_form", clear_on_submit=True):
        pergunta = st.text_area(
            "Digite sua pergunta aqui:",
            placeholder="Ex: Me explique sobre a reforma tributária e seus impactos no ICMS...\nOu: Tenho algum estudo sobre substituição tributária em SP?",
            height=100,
            label_visibility="collapsed"
        )
        
        col1, col2, col3 = st.columns([4, 1, 1])
        with col1:
            submit = st.form_submit_button("🔍 Enviar Pergunta", use_container_width=True, type="primary")
        with col2:
            nova_conversa = st.form_submit_button("🗑️ Nova", use_container_width=True)
    
    # Processar nova conversa
    if nova_conversa:
        limpar_historico()
        st.rerun()
    
    # Processar pergunta
    if submit and pergunta.strip():
        # Salvar pergunta do usuário
        salvar_mensagem("user", pergunta)
        
        with st.spinner("🔄 Pesquisando na biblioteca e fontes oficiais..."):
            # Obter histórico atualizado para contexto
            hist_mensagens = [{"role": m["role"], "content": m["content"]} for m in obter_historico()]
            
            # Consultar agente
            resposta, materiais, fontes = consultar_agente(pergunta, hist_mensagens[:-1])  # Excluir a última (já está na pergunta)
            
            # Salvar resposta
            salvar_mensagem("assistant", resposta, fontes)
            
            st.session_state.ultimos_materiais = materiais
            st.session_state.ultimas_fontes = fontes
        
        st.rerun()
    
    # Mostrar materiais da biblioteca encontrados (última consulta)
    if st.session_state.ultimos_materiais:
        st.markdown("---")
        st.markdown("### �� Materiais relacionados na sua biblioteca")
        for m in st.session_state.ultimos_materiais:
            st.markdown(f"""
            <div class="biblioteca-card">
                <strong>📄 {m['titulo']}</strong><br>
                <small>Cliente: {m['cliente_nome']} | Tags: {m['tags'] or 'Sem tags'}</small><br>
                <small>{m['resumo'][:150]}...</small>
            </div>
            """, unsafe_allow_html=True)

elif st.session_state.pag == "biblioteca":
    st.markdown("## �� Biblioteca de Estudos")
    
    # Busca
    busca = st.text_input("🔍 Buscar estudos", placeholder="Digite para buscar...")
    
    if busca:
        resultados = buscar_estudos(busca)
        st.markdown(f"### Resultados para '{busca}' ({len(resultados)})")
    else:
        resultados = estudos_recentes(20)
        st.markdown("### Estudos Recentes")
    
    if resultados:
        for r in resultados:
            with st.expander(f"📄 {r['titulo']} - {r['cliente_nome']}"):
                st.markdown(f"**Cliente:** {r['cliente_nome']}")
                st.markdown(f"**Data:** {fmt_date(r['created_at'])}")
                if r['tags']:
                    st.markdown("**Tags:** " + " ".join([f'`{t.strip()}`' for t in r['tags'].split(",")]))
                st.markdown("**Resumo:**")
                st.markdown(r['resumo'][:500] + "..." if len(r['resumo']) > 500 else r['resumo'])
                
                if st.button("Abrir completo", key=f"abrir_{r['id']}"):
                    go("estudo", r['cliente_id'], r['id'])
                    st.rerun()
    else:
        st.info("Nenhum estudo encontrado.")

elif st.session_state.pag == "novo":
    st.markdown("## ➕ Novo Cadastro")
    
    t1, t2 = st.tabs(["📄 Novo Estudo", "👤 Novo Cliente"])
    
    with t1:
        cls = listar_clientes()
        if not cls:
            st.warning("⚠️ Cadastre um cliente primeiro na aba 'Novo Cliente'")
        else:
            with st.form("form_estudo"):
                opts = {c['nome']: c['id'] for c in cls}
                cliente = st.selectbox("Cliente *", list(opts.keys()))
                titulo = st.text_input("Título do Estudo *")
                resumo = st.text_area("Resumo / Conteúdo *", height=300, placeholder="Descreva o estudo tributário em detalhes...")
                tags = st.text_input("Tags (separadas por vírgula)", placeholder="ICMS, ST, SP, Reforma")
                arquivos = st.file_uploader("📎 Anexos", accept_multiple_files=True, type=["pdf", "xls", "xlsx", "doc", "docx", "txt", "csv", "png", "jpg"])
                
                if st.form_submit_button("💾 Salvar Estudo", use_container_width=True, type="primary"):
                    if not titulo or not resumo:
                        st.error("Título e Resumo são obrigatórios!")
                    else:
                        eid = criar_estudo(opts[cliente], titulo, resumo, tags)
                        if arquivos:
                            for a in arquivos:
                                add_anexo(eid, a.name, a.type or "application/octet-stream", a.read(), a.size)
                        st.success(f"✅ Estudo '{titulo}' criado!")
                        st.balloons()
    
    with t2:
        with st.form("form_cliente"):
            nome = st.text_input("Nome do Cliente *")
            cnpj = st.text_input("CNPJ")
            obs = st.text_area("Observações")
            
            if st.form_submit_button("💾 Salvar Cliente", use_container_width=True, type="primary"):
                if not nome:
                    st.error("Nome é obrigatório!")
                else:
                    criar_cliente(nome, cnpj, obs)
                    st.success(f"✅ Cliente '{nome}' cadastrado!")
                    st.balloons()

elif st.session_state.pag == "clientes":
    st.markdown("## 👥 Clientes")
    
    clientes = listar_clientes()
    
    if clientes:
        for cl in clientes:
            with st.expander(f"📁 {cl['nome']}" + (f" - CNPJ: {cl['cnpj']}" if cl['cnpj'] else "")):
                estudos = listar_estudos(cl['id'])
                st.markdown(f"**Estudos:** {len(estudos)}")
                
                if cl['observacoes']:
                    st.markdown(f"**Obs:** {cl['observacoes']}")
                
                if estudos:
                    st.markdown("**Estudos:**")
                    for e in estudos[:5]:
                        if st.button(f"📄 {e['titulo']}", key=f"est_{cl['id']}_{e['id']}"):
                            go("estudo", cl['id'], e['id'])
                            st.rerun()
                
                if st.button("🗑️ Excluir Cliente", key=f"del_cli_{cl['id']}"):
                    excluir_cliente(cl['id'])
                    st.rerun()
    else:
        st.info("Nenhum cliente cadastrado. Vá em 'Novo Estudo' para cadastrar.")

elif st.session_state.pag == "config":
    st.markdown("## ⚙️ Configurações")
    
    # Status
    col1, col2, col3, col4 = st.columns(4)
    s = stats()
    with col1: st.metric("Clientes", s["clientes"])
    with col2: st.metric("Estudos", s["estudos"])
    with col3: st.metric("Anexos", s["anexos"])
    with col4: st.metric("Consultas IA", s["consultas"])
    
    st.markdown("---")
    
    # API Status
    st.markdown("### 🔑 API OpenAI")
    if client:
        st.success("✅ Conectada e funcionando")
    else:
        st.error("❌ Não configurada - adicione a chave em .streamlit/secrets.toml")
    
    st.markdown("---")
    
    # Backup
    st.markdown("### 💾 Backup")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📥 Gerar Backup", use_container_width=True):
            backup = criar_backup()
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button("⬇️ Baixar Backup", backup, f"backup_{ts}.zip", "application/zip", use_container_width=True)
    
    with col2:
        uploaded = st.file_uploader("Restaurar backup", type=["zip", "json"])
        if uploaded:
            if st.button("📤 Restaurar", use_container_width=True, type="primary"):
                ok, msg = restaurar_backup(uploaded)
                if ok:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")

elif st.session_state.pag == "estudo":
    est = obter_estudo(st.session_state.est)
    cl = obter_cliente(st.session_state.cli)
    
    if est and cl:
        # Cabeçalho
        col1, col2, col3 = st.columns([4, 1, 1])
        with col1:
            st.markdown(f"## 📖 {est['titulo']}")
            st.caption(f"👤 {cl['nome']} | 📅 {fmt_date(est['created_at'])}")
        with col2:
            if st.button("✏️ Editar"):
                st.session_state.edit = True
                st.rerun()
        with col3:
            if st.button("🗑️ Excluir"):
                excluir_estudo(est['id'])
                go("biblioteca")
                st.rerun()
        
        # Tags
        if est['tags']:
            st.markdown(" ".join([f'<span class="tag">{t.strip()}</span>' for t in est['tags'].split(",")]), unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Modo edição
        if st.session_state.edit:
            with st.form("form_editar"):
                novo_titulo = st.text_input("Título", value=est['titulo'])
                novo_resumo = st.text_area("Resumo", value=est['resumo'], height=400)
                novas_tags = st.text_input("Tags", value=est['tags'] or "")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.form_submit_button("💾 Salvar", use_container_width=True, type="primary"):
                        atualizar_estudo(est['id'], novo_titulo, novo_resumo, novas_tags)
                        st.session_state.edit = False
                        st.rerun()
                with col2:
                    if st.form_submit_button("❌ Cancelar", use_container_width=True):
                        st.session_state.edit = False
                        st.rerun()
        else:
            st.markdown("### 📋 Conteúdo")
            st.markdown(est['resumo'])
        
        # Anexos
        st.markdown("---")
        st.markdown("### 📎 Anexos")
        
        anexos = listar_anexos(est['id'])
        if anexos:
            for a in anexos:
                col1, col2, col3 = st.columns([4, 1, 1])
                with col1:
                    st.markdown(f"{file_icon(a['file_type'])} **{a['filename']}** ({fmt_size(a['file_size'])})")
                with col2:
                    anx_data = obter_anexo(a['id'])
                    if anx_data:
                        st.download_button("⬇️", base64.b64decode(anx_data['file_data']), a['filename'], a['file_type'], key=f"dl_{a['id']}")
                with col3:
                    if st.button("🗑️", key=f"del_{a['id']}"):
                        excluir_anexo(a['id'])
                        st.rerun()
        else:
            st.info("Nenhum anexo")
        
        # Upload de novos anexos
        with st.form("form_anexos", clear_on_submit=True):
            novos = st.file_uploader("Adicionar anexos", accept_multiple_files=True, type=["pdf", "xls", "xlsx", "doc", "docx", "txt", "png", "jpg"])
            if st.form_submit_button("📤 Enviar", use_container_width=True):
                if novos:
                    for a in novos:
                        content = a.read()
                        add_anexo(est['id'], a.name, a.type or "application/octet-stream", content, len(content))
                    st.success(f"✅ {len(novos)} arquivo(s) adicionado(s)!")
                    st.rerun()
        
        # Botão voltar
        st.markdown("---")
        if st.button("← Voltar para Biblioteca"):
            go("biblioteca")
            st.rerun()

# Footer
st.markdown("---")
st.caption("📚 Biblioteca Tributária | 🤖 Consultor IA Integrado")
