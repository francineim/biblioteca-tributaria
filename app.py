import streamlit as st
import sqlite3
from datetime import datetime
from pathlib import Path
import base64
import json
import zipfile
import io

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

.card-badge {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: 9999px;
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    margin-right: 0.5rem;
}

.badge-estadual { background: rgba(16, 185, 129, 0.2); color: #34d399; }

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
    """Mantém compatibilidade com banco antigo (tabelas extras podem existir)."""
    conn = get_conn()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        cnpj TEXT,
        observacoes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS estudos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL,
        titulo TEXT NOT NULL,
        resumo TEXT NOT NULL,
        tags TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS anexos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        estudo_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        file_type TEXT NOT NULL,
        file_data TEXT NOT NULL,
        file_size INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    conn.commit()
    conn.close()

init_db()

# ==================== CRUD ====================
def criar_cliente(nome, cnpj=None, obs=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO clientes (nome, cnpj, observacoes) VALUES (?, ?, ?)", (nome, cnpj, obs))
    conn.commit()
    cid = c.lastrowid
    conn.close()
    return cid

def listar_clientes():
    conn = get_conn()
    r = list(conn.cursor().execute("SELECT * FROM clientes ORDER BY nome").fetchall())
    conn.close()
    return r

def obter_cliente(cid):
    conn = get_conn()
    r = conn.cursor().execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone()
    conn.close()
    return r

def excluir_cliente(cid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM anexos WHERE estudo_id IN (SELECT id FROM estudos WHERE cliente_id=?)", (cid,))
    c.execute("DELETE FROM estudos WHERE cliente_id=?", (cid,))
    c.execute("DELETE FROM clientes WHERE id=?", (cid,))
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

def listar_estudos(cid=None):
    conn = get_conn()
    if cid:
        r = list(conn.cursor().execute(
            "SELECT * FROM estudos WHERE cliente_id=? ORDER BY created_at DESC", (cid,)
        ).fetchall())
    else:
        r = list(conn.cursor().execute(
            "SELECT e.*, c.nome as cliente FROM estudos e JOIN clientes c ON e.cliente_id=c.id ORDER BY e.created_at DESC"
        ).fetchall())
    conn.close()
    return r

def obter_estudo(eid):
    conn = get_conn()
    r = conn.cursor().execute("SELECT * FROM estudos WHERE id=?", (eid,)).fetchone()
    conn.close()
    return r

def atualizar_estudo(eid, titulo, resumo, tags):
    conn = get_conn()
    conn.cursor().execute(
        "UPDATE estudos SET titulo=?, resumo=?, tags=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (titulo, resumo, tags, eid)
    )
    conn.commit()
    conn.close()

def excluir_estudo(eid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM anexos WHERE estudo_id=?", (eid,))
    c.execute("DELETE FROM estudos WHERE id=?", (eid,))
    conn.commit()
    conn.close()

def add_anexo(eid, nome, tipo, dados, tam):
    conn = get_conn()
    conn.cursor().execute(
        "INSERT INTO anexos (estudo_id, filename, file_type, file_data, file_size) VALUES (?, ?, ?, ?, ?)",
        (eid, nome, tipo or "", base64.b64encode(dados).decode(), tam)
    )
    conn.commit()
    conn.close()

def listar_anexos(eid):
    conn = get_conn()
    r = list(conn.cursor().execute(
        "SELECT id, filename, file_type, file_size FROM anexos WHERE estudo_id=? ORDER BY created_at DESC", (eid,)
    ).fetchall())
    conn.close()
    return r

def obter_anexo(aid):
    conn = get_conn()
    r = conn.cursor().execute("SELECT * FROM anexos WHERE id=?", (aid,)).fetchone()
    conn.close()
    return r

def excluir_anexo(aid):
    conn = get_conn()
    conn.cursor().execute("DELETE FROM anexos WHERE id=?", (aid,))
    conn.commit()
    conn.close()

def stats():
    conn = get_conn()
    c = conn.cursor()
    s = {
        "clientes": c.execute("SELECT COUNT(*) FROM clientes").fetchone()[0],
        "estudos": c.execute("SELECT COUNT(*) FROM estudos").fetchone()[0],
        "anexos": c.execute("SELECT COUNT(*) FROM anexos").fetchone()[0],
    }
    conn.close()
    return s

# ==================== BACKUP / RESTORE (CORE) ====================
def backup():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        conn = get_conn()
        data = {
            "versao": "6.3",
            "data": datetime.now().isoformat(),
            "clientes": [dict(r) for r in conn.cursor().execute("SELECT * FROM clientes").fetchall()],
            "estudos": [dict(r) for r in conn.cursor().execute("SELECT * FROM estudos").fetchall()],
            "anexos": [dict(r) for r in conn.cursor().execute("SELECT * FROM anexos").fetchall()],
        }
        conn.close()
        zf.writestr("backup.json", json.dumps(data, ensure_ascii=False, indent=2))
    buf.seek(0)
    return buf

def restaurar(file):
    try:
        content = file.read()
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            data = json.loads(zf.read("backup.json"))
    except zipfile.BadZipFile:
        data = json.loads(content)

    try:
        conn = get_conn()
        c = conn.cursor()

        # limpa core
        for t in ["anexos", "estudos", "clientes"]:
            c.execute(f"DELETE FROM {t}")

        # restaura (tolerante a campos faltantes)
        for cl in data.get("clientes", []):
            c.execute(
                "INSERT INTO clientes (id, nome, cnpj, observacoes, created_at) VALUES (?, ?, ?, ?, ?)",
                (cl.get("id"), cl.get("nome"), cl.get("cnpj"), cl.get("observacoes"), cl.get("created_at"))
            )

        for e in data.get("estudos", []):
            c.execute(
                "INSERT INTO estudos (id, cliente_id, titulo, resumo, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (e.get("id"), e.get("cliente_id"), e.get("titulo"), e.get("resumo"), e.get("tags"),
                 e.get("created_at"), e.get("updated_at"))
            )

        for a in data.get("anexos", []):
            c.execute(
                "INSERT INTO anexos (id, estudo_id, filename, file_type, file_data, file_size, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (a.get("id"), a.get("estudo_id"), a.get("filename"), a.get("file_type"),
                 a.get("file_data"), a.get("file_size"), a.get("created_at"))
            )

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

def navegar(p, c=None, e=None):
    st.session_state.pagina = p
    st.session_state.cliente_id = c
    st.session_state.estudo_id = e
    st.session_state.edit_mode = False

# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown("""<div class="logo-container">
        <p class="logo-text">⚖️ Biblioteca Tributária</p>
        <p class="logo-subtitle">Core v6.3</p>
    </div>""", unsafe_allow_html=True)

    menu = [
        ("📊", "Dashboard", "dashboard"),
        ("📚", "Biblioteca", "biblioteca"),
        ("👥", "Clientes", "clientes"),
        ("➕", "Novo Cadastro", "novo"),
        ("⚙️", "Configurações", "config"),
    ]

    for icon, label, page in menu:
        if st.button(
            f"{icon}  {label}",
            key=f"nav_{page}",
            use_container_width=True,
            type="primary" if st.session_state.pagina == page else "secondary"
        ):
            navegar(page)
            st.rerun()

    st.markdown("---")
    st.caption("✅ Agente removido | ✅ Atualizações removidas")
    st.caption("© 2025 MP Solutions")

# ==================== PÁGINAS ====================
if st.session_state.pagina == "dashboard":
    st.markdown("## 📊 Dashboard")

    s = stats()
    cols = st.columns(3)
    for col, (icon, label, value) in zip(cols, [
        ("👥", "Clientes", s["clientes"]),
        ("📚", "Estudos", s["estudos"]),
        ("📎", "Anexos", s["anexos"]),
    ]):
        with col:
            st.markdown(
                f'<div class="stat-card"><div class="stat-value">{value}</div><div class="stat-label">{icon} {label}</div></div>',
                unsafe_allow_html=True
            )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📚 Estudos Recentes")
    for est in listar_estudos()[:8]:
        est = dict(est)
        st.markdown(
            f'<div class="search-result">'
            f'<span class="card-badge badge-estadual">{est.get("cliente","")}</span>'
            f'<div class="result-title">{est.get("titulo","")[:90]}{"..." if len(est.get("titulo",""))>90 else ""}</div>'
            f'<div class="result-meta">🕒 {str(est.get("created_at",""))[:16]}</div>'
            f'</div>',
            unsafe_allow_html=True
        )

elif st.session_state.pagina == "biblioteca":
    st.markdown("## 📚 Biblioteca")
    busca = st.text_input("🔍 Buscar:", placeholder="Digite para filtrar por título ou resumo...")

    if busca:
        conn = get_conn()
        estudos = [dict(r) for r in conn.cursor().execute(
            """SELECT e.*, c.nome as cliente
               FROM estudos e JOIN clientes c ON e.cliente_id=c.id
               WHERE e.titulo LIKE ? OR e.resumo LIKE ?
               ORDER BY e.created_at DESC""",
            (f"%{busca}%", f"%{busca}%")
        ).fetchall()]
        conn.close()
    else:
        estudos = [dict(r) for r in listar_estudos()]

    if not estudos:
        st.info("Nenhum estudo encontrado.")
    else:
        for est in estudos:
            with st.expander(f"📄 {est['titulo'][:55]}... - {est.get('cliente', '')}"):
                st.markdown(f"**Tags:** {est.get('tags') or 'Sem tags'}")
                st.markdown((est.get("resumo") or "")[:600] + ("..." if len(est.get("resumo") or "") > 600 else ""))

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("📖 Abrir", key=f"a_{est['id']}"):
                        navegar("estudo_view", est.get("cliente_id"), est["id"])
                        st.rerun()
                with col2:
                    if st.button("🗑️ Excluir", key=f"d_{est['id']}"):
                        excluir_estudo(est["id"])
                        st.rerun()

elif st.session_state.pagina == "clientes":
    st.markdown("## 👥 Clientes")

    clientes = listar_clientes()
    if not clientes:
        st.info("Nenhum cliente cadastrado ainda.")
    else:
        for cl in clientes:
            cl = dict(cl)
            estudos_cl = listar_estudos(cl["id"])

            with st.expander(f"🏢 {cl['nome']}" + (f" - {cl.get('cnpj','')}" if cl.get("cnpj") else "")):
                st.markdown(f"**Estudos:** {len(estudos_cl)}")

                for est in estudos_cl[:8]:
                    est = dict(est)
                    if st.button(f"📄 {est['titulo'][:45]}...", key=f"e_{cl['id']}_{est['id']}"):
                        navegar("estudo_view", cl["id"], est["id"])
                        st.rerun()

                if st.button("🗑️ Excluir Cliente", key=f"dc_{cl['id']}"):
                    excluir_cliente(cl["id"])
                    st.rerun()

elif st.session_state.pagina == "novo":
    st.markdown("## ➕ Novo Cadastro")
    tab1, tab2 = st.tabs(["📄 Estudo", "👤 Cliente"])

    with tab1:
        clientes = listar_clientes()
        if not clientes:
            st.warning("Cadastre um cliente primeiro.")
        else:
            with st.form("f_estudo"):
                opts = {c["nome"]: c["id"] for c in clientes}
                cliente_nome = st.selectbox("Cliente:", list(opts.keys()))
                titulo = st.text_input("Título:")
                resumo = st.text_area("Resumo:", height=220)
                tags = st.text_input("Tags (vírgula):")
                arquivos = st.file_uploader("Anexos:", accept_multiple_files=True)

                if st.form_submit_button("💾 Salvar", type="primary"):
                    if not titulo or not resumo:
                        st.error("Preencha título e resumo.")
                    else:
                        eid = criar_estudo(opts[cliente_nome], titulo, resumo, tags)
                        for arq in arquivos or []:
                            add_anexo(eid, arq.name, arq.type or "", arq.read(), arq.size)
                        st.success("✅ Estudo criado!")
                        st.balloons()

    with tab2:
        with st.form("f_cliente"):
            nome = st.text_input("Nome:")
            cnpj = st.text_input("CNPJ:")
            obs = st.text_area("Observações:")
            if st.form_submit_button("💾 Salvar", type="primary"):
                if not nome:
                    st.error("Nome é obrigatório.")
                else:
                    criar_cliente(nome, cnpj, obs)
                    st.success("✅ Cliente criado!")

elif st.session_state.pagina == "config":
    st.markdown("## ⚙️ Configurações")

    st.markdown("### 💾 Backup")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("📥 Gerar Backup", use_container_width=True):
            bkp = backup()
            st.download_button(
                "⬇️ Baixar",
                bkp,
                f"backup_{datetime.now():%Y%m%d_%H%M}.zip",
                use_container_width=True
            )

    with col2:
        arq = st.file_uploader("Restaurar:", type=["zip", "json"])
        if arq and st.button("�� Restaurar", use_container_width=True):
            ok, msg = restaurar(arq)
            st.success(msg) if ok else st.error(msg)

    st.markdown("---")
    st.markdown("""
**v6.3 (Core)**
- ✅ Consultor IA removido
- ✅ Atualizações removidas
- ✅ App focado na biblioteca (clientes/estudos/anexos)
- ✅ Backup/restore do núcleo
""")

elif st.session_state.pagina == "estudo_view":
    estudo = obter_estudo(st.session_state.estudo_id)
    cliente = obter_cliente(st.session_state.cliente_id)

    if not estudo or not cliente:
        st.error("Estudo/cliente não encontrado.")
    else:
        estudo, cliente = dict(estudo), dict(cliente)

        col1, col2, col3 = st.columns([4, 1, 1])
        with col1:
            st.markdown(f"## 📖 {estudo['titulo']}")
            st.caption(f"👤 {cliente['nome']}")
        with col2:
            if st.button("✏️ Editar"):
                st.session_state.edit_mode = True
                st.rerun()
        with col3:
            if st.button("🗑️ Excluir"):
                excluir_estudo(estudo["id"])
                navegar("biblioteca")
                st.rerun()

        st.markdown("---")

        if st.session_state.edit_mode:
            with st.form("f_edit"):
                titulo = st.text_input("Título:", estudo["titulo"])
                resumo = st.text_area("Resumo:", estudo["resumo"], height=300)
                tags = st.text_input("Tags:", estudo.get("tags", ""))

                colA, colB = st.columns(2)
                with colA:
                    if st.form_submit_button("💾 Salvar"):
                        atualizar_estudo(estudo["id"], titulo, resumo, tags)
                        st.session_state.edit_mode = False
                        st.rerun()
                with colB:
                    if st.form_submit_button("❌ Cancelar"):
                        st.session_state.edit_mode = False
                        st.rerun()
        else:
            st.markdown(estudo["resumo"])
            st.markdown(f"**Tags:** {estudo.get('tags') or 'Sem tags'}")

        st.markdown("---")
        st.markdown("### 📎 Anexos")

        anexos = listar_anexos(estudo["id"])
        if not anexos:
            st.info("Nenhum anexo neste estudo.")
        else:
            for anx in anexos:
                anx = dict(anx)
                colA, colB, colC = st.columns([4, 1, 1])
                with colA:
                    st.markdown(f"📄 {anx['filename']}")
                with colB:
                    anexo_full = obter_anexo(anx["id"])
                    if anexo_full:
                        st.download_button(
                            "⬇️",
                            base64.b64decode(anexo_full["file_data"]),
                            anx["filename"],
                            anx["file_type"],
                            key=f"dl_{anx['id']}"
                        )
                with colC:
                    if st.button("🗑️", key=f"da_{anx['id']}"):
                        excluir_anexo(anx["id"])
                        st.rerun()

        with st.form("f_upload", clear_on_submit=True):
            novos = st.file_uploader("Adicionar:", accept_multiple_files=True)
            if st.form_submit_button("📤 Upload") and novos:
                for arq in novos:
                    add_anexo(estudo["id"], arq.name, arq.type or "", arq.read(), arq.size)
                st.rerun()

        if st.button("← Voltar"):
            navegar("biblioteca")
            st.rerun()

st.markdown("---")
st.caption("⚖️ Biblioteca Tributária Pro v6.3 (Core) | © 2025 MP Solutions")
