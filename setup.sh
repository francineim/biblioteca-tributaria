#!/bin/bash
echo "📚 Criando Biblioteca de Estudos Tributários..."
mkdir -p .streamlit data uploads
echo "streamlit>=1.28.0" > requirements.txt
echo -e "__pycache__/\n*.py[cod]\n.env\n*.db\n.DS_Store" > .gitignore
cat > .streamlit/config.toml << 'EOF'
[theme]
primaryColor = "#1f4e79"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f0f4f8"
textColor = "#262730"
[server]
maxUploadSize = 50
[browser]
gatherUsageStats = false
EOF
touch data/.gitkeep uploads/.gitkeep
cat > app.py << 'APPEOF'
import streamlit as st
import sqlite3
from datetime import datetime
from pathlib import Path
import base64

st.set_page_config(page_title="Biblioteca Tributária", page_icon="📚", layout="wide", initial_sidebar_state="expanded")
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "biblioteca.db"

st.markdown("""<style>
.main-header {font-size: 2.2rem; font-weight: bold; color: #1f4e79; margin-bottom: 1rem; text-align: center;}
.stat-card {background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 12px; padding: 1.5rem; color: white; text-align: center;}
.stat-number {font-size: 2.5rem; font-weight: bold;}
.stat-label {font-size: 0.9rem; opacity: 0.9;}
.tag {display: inline-block; background-color: #e3f2fd; color: #1565c0; padding: 0.2rem 0.6rem; border-radius: 15px; font-size: 0.8rem; margin-right: 0.3rem;}
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
    conn.commit()
    conn.close()

init_db()

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
    conn.close()
    return {"clientes": tc, "estudos": te, "anexos": ta}

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

if "pag" not in st.session_state: st.session_state.pag = "home"
if "cli" not in st.session_state: st.session_state.cli = None
if "est" not in st.session_state: st.session_state.est = None
if "edit" not in st.session_state: st.session_state.edit = False

def go(p, c=None, e=None):
    st.session_state.pag = p
    st.session_state.cli = c
    st.session_state.est = e
    st.session_state.edit = False

with st.sidebar:
    st.markdown("## 📚 Biblioteca Tributária")
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🏠 Início", use_container_width=True): go("home")
    with c2:
        if st.button("➕ Novo", use_container_width=True): go("novo")
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
                    if st.button(f"📄 {t}", key=f"e_{es['id']}", use_container_width=True): go("estudo", cl['id'], es['id'])

if st.session_state.pag == "home":
    st.markdown('<h1 class="main-header">📚 Biblioteca de Estudos Tributários</h1>', unsafe_allow_html=True)
    s = stats()
    c1, c2, c3 = st.columns(3)
    with c1: st.markdown(f'<div class="stat-card"><div class="stat-number">{s["clientes"]}</div><div class="stat-label">👥 Clientes</div></div>', unsafe_allow_html=True)
    with c2: st.markdown(f'<div class="stat-card"><div class="stat-number">{s["estudos"]}</div><div class="stat-label">📄 Estudos</div></div>', unsafe_allow_html=True)
    with c3: st.markdown(f'<div class="stat-card"><div class="stat-number">{s["anexos"]}</div><div class="stat-label">📎 Anexos</div></div>', unsafe_allow_html=True)
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
                tags = st.text_input("Tags (separadas por vírgula)")
                arqs = st.file_uploader("📎 Anexos", accept_multiple_files=True, type=["pdf", "xls", "xlsx", "doc", "docx", "txt", "csv", "png", "jpg", "jpeg"])
                if st.form_submit_button("💾 Salvar"):
                    if not tit or not res: st.error("Título e Resumo obrigatórios!")
                    else:
                        eid = criar_estudo(opts[cn], tit, res, tags)
                        if arqs:
                            for a in arqs: add_anexo(eid, a.name, a.type or "application/octet-stream", a.read(), a.size)
                        st.success(f"✅ Estudo '{tit}' criado!")
                        st.balloons()

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
        else: st.info("Nenhum anexo")
        st.markdown("#### Adicionar Anexos")
        novos = st.file_uploader("Selecione", accept_multiple_files=True, type=["pdf", "xls", "xlsx", "doc", "docx", "txt", "png", "jpg"], key="na")
        if novos and st.button("📤 Upload"):
            for a in novos: add_anexo(est['id'], a.name, a.type or "application/octet-stream", a.read(), a.size)
            st.rerun()

st.markdown("---")
st.caption("📚 Biblioteca de Estudos Tributários | Streamlit")
APPEOF
echo "✅ Projeto criado!"
echo ""
echo "📁 Arquivos:"
ls -la
echo ""
echo "🚀 Próximos passos:"
echo "1. Testar: pip install streamlit && streamlit run app.py"
echo "2. Salvar: git add . && git commit -m 'Biblioteca tributaria' && git push"
echo "3. Deploy: https://share.streamlit.io"
