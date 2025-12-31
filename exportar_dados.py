import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path("data/biblioteca.db")

if not DB_PATH.exists():
    print("❌ Banco não encontrado em data/biblioteca.db")
    exit()

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

c = conn.cursor()

# Exportar clientes
c.execute("SELECT * FROM clientes")
clientes = [dict(row) for row in c.fetchall()]

# Exportar estudos
c.execute("SELECT * FROM estudos")
estudos = [dict(row) for row in c.fetchall()]

# Exportar anexos
c.execute("SELECT * FROM anexos")
anexos = [dict(row) for row in c.fetchall()]

conn.close()

backup = {
    "versao": "1.0",
    "data_backup": datetime.now().isoformat(),
    "clientes": clientes,
    "estudos": estudos,
    "anexos": anexos
}

with open("meu_backup.json", "w", encoding="utf-8") as f:
    json.dump(backup, f, ensure_ascii=False, indent=2)

print(f"✅ Backup criado: meu_backup.json")
print(f"   - {len(clientes)} clientes")
print(f"   - {len(estudos)} estudos")
print(f"   - {len(anexos)} anexos")
print("")
print("📥 Agora baixe o arquivo 'meu_backup.json':")
print("   Clique com botão direito no arquivo → Download")
