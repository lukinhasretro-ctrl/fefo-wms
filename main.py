from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
import sqlite3, os, csv, io
from datetime import date, datetime
from contextlib import contextmanager

app = FastAPI(title="FEFO WMS Controller")

DB_PATH = "fefo.db"

# ── banco ──────────────────────────────────────────────────────────
def init_db():
    with get_db() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS lotes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sku         TEXT    NOT NULL,
            descricao   TEXT,
            lote        TEXT    NOT NULL,
            validade    TEXT    NOT NULL,
            quantidade  REAL    NOT NULL,
            unidade     TEXT    DEFAULT 'UN',
            endereco    TEXT    NOT NULL,
            fornecedor  TEXT,
            data_receb  TEXT    DEFAULT (date('now')),
            ativo       INTEGER DEFAULT 1
        )""")
        con.execute("""
        CREATE TABLE IF NOT EXISTS movimentos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            lote_id     INTEGER REFERENCES lotes(id),
            tipo        TEXT,   -- ENTRADA | SAIDA | AJUSTE
            quantidade  REAL,
            usuario     TEXT,
            obs         TEXT,
            data_mov    TEXT    DEFAULT (datetime('now'))
        )""")
        con.commit()

@contextmanager
def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()

init_db()

# ── modelos ────────────────────────────────────────────────────────
class LoteIn(BaseModel):
    sku:       str
    descricao: Optional[str] = ""
    lote:      str
    validade:  str
    quantidade: float
    unidade:   Optional[str] = "UN"
    endereco:  str
    fornecedor: Optional[str] = ""

class MovimentoIn(BaseModel):
    tipo:      str
    quantidade: float
    usuario:   Optional[str] = "sistema"
    obs:       Optional[str] = ""

class LoteUpdate(BaseModel):
    descricao:  Optional[str] = None
    validade:   Optional[str] = None
    quantidade: Optional[float] = None
    endereco:   Optional[str] = None
    fornecedor: Optional[str] = None

# ── helpers ────────────────────────────────────────────────────────
def dias_ate_vencer(validade: str) -> int:
    try:
        v = datetime.strptime(validade, "%Y-%m-%d").date()
        return (v - date.today()).days
    except:
        return 999

def row_to_dict(row):
    d = dict(row)
    d["dias_validade"] = dias_ate_vencer(d.get("validade",""))
    d["status"] = (
        "vencido"   if d["dias_validade"] < 0  else
        "critico"   if d["dias_validade"] <= 7  else
        "atencao"   if d["dias_validade"] <= 30 else
        "ok"
    )
    return d

# ── rotas ──────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def root():
    return FileResponse("templates/index.html")

# Lotes
@app.get("/api/lotes")
def listar_lotes(sku: str = "", endereco: str = "", status: str = ""):
    with get_db() as con:
        q = "SELECT * FROM lotes WHERE ativo=1"
        params = []
        if sku:
            q += " AND (sku LIKE ? OR descricao LIKE ?)"
            params += [f"%{sku}%", f"%{sku}%"]
        if endereco:
            q += " AND endereco LIKE ?"
            params.append(f"%{endereco}%")
        q += " ORDER BY validade ASC"
        rows = con.execute(q, params).fetchall()
    dados = [row_to_dict(r) for r in rows]
    if status:
        dados = [d for d in dados if d["status"] == status]
    return dados

@app.post("/api/lotes", status_code=201)
def criar_lote(lote: LoteIn):
    with get_db() as con:
        cur = con.execute("""
            INSERT INTO lotes (sku,descricao,lote,validade,quantidade,unidade,endereco,fornecedor)
            VALUES (?,?,?,?,?,?,?,?)
        """, (lote.sku.upper(), lote.descricao, lote.lote.upper(),
              lote.validade, lote.quantidade, lote.unidade,
              lote.endereco.upper(), lote.fornecedor))
        lote_id = cur.lastrowid
        con.execute("""
            INSERT INTO movimentos (lote_id,tipo,quantidade,usuario,obs)
            VALUES (?,?,?,?,?)
        """, (lote_id, "ENTRADA", lote.quantidade, "recebimento", f"Recebimento inicial - {lote.fornecedor}"))
        con.commit()
        row = con.execute("SELECT * FROM lotes WHERE id=?", (lote_id,)).fetchone()
    return row_to_dict(row)

@app.patch("/api/lotes/{lote_id}")
def atualizar_lote(lote_id: int, upd: LoteUpdate):
    with get_db() as con:
        row = con.execute("SELECT * FROM lotes WHERE id=? AND ativo=1", (lote_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Lote não encontrado")
        fields, vals = [], []
        for k, v in upd.dict(exclude_none=True).items():
            fields.append(f"{k}=?")
            vals.append(v.upper() if k == "endereco" else v)
        if fields:
            con.execute(f"UPDATE lotes SET {','.join(fields)} WHERE id=?", vals + [lote_id])
            con.commit()
        row = con.execute("SELECT * FROM lotes WHERE id=?", (lote_id,)).fetchone()
    return row_to_dict(row)

@app.delete("/api/lotes/{lote_id}")
def remover_lote(lote_id: int):
    with get_db() as con:
        con.execute("UPDATE lotes SET ativo=0 WHERE id=?", (lote_id,))
        con.commit()
    return {"ok": True}

@app.post("/api/lotes/{lote_id}/movimentos")
def registrar_movimento(lote_id: int, mov: MovimentoIn):
    with get_db() as con:
        row = con.execute("SELECT * FROM lotes WHERE id=? AND ativo=1", (lote_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Lote não encontrado")
        nova_qty = row["quantidade"]
        if mov.tipo == "SAIDA":
            if mov.quantidade > row["quantidade"]:
                raise HTTPException(400, f"Quantidade insuficiente. Disponível: {row['quantidade']}")
            nova_qty -= mov.quantidade
        elif mov.tipo == "ENTRADA":
            nova_qty += mov.quantidade
        elif mov.tipo == "AJUSTE":
            nova_qty = mov.quantidade
        con.execute("UPDATE lotes SET quantidade=? WHERE id=?", (nova_qty, lote_id))
        con.execute("""
            INSERT INTO movimentos (lote_id,tipo,quantidade,usuario,obs)
            VALUES (?,?,?,?,?)
        """, (lote_id, mov.tipo, mov.quantidade, mov.usuario, mov.obs))
        con.commit()
        row = con.execute("SELECT * FROM lotes WHERE id=?", (lote_id,)).fetchone()
    return row_to_dict(row)

# FEFO
@app.get("/api/fefo")
def consultar_fefo(sku: str, quantidade: float = 0):
    with get_db() as con:
        rows = con.execute("""
            SELECT * FROM lotes
            WHERE sku=? AND ativo=1 AND quantidade>0
            ORDER BY validade ASC
        """, (sku.upper(),)).fetchall()
    if not rows:
        raise HTTPException(404, "Nenhum lote disponível para este SKU")
    dados = [row_to_dict(r) for r in rows]
    restante = quantidade
    for d in dados:
        if restante > 0:
            d["separar"] = min(d["quantidade"], restante)
            restante -= d["separar"]
        else:
            d["separar"] = 0
    return {
        "sku": sku.upper(),
        "descricao": dados[0].get("descricao",""),
        "total_disponivel": sum(d["quantidade"] for d in dados),
        "quantidade_solicitada": quantidade,
        "cobertura_ok": restante <= 0,
        "falta": max(0, restante),
        "lotes": dados
    }

# SKUs únicos
@app.get("/api/skus")
def listar_skus():
    with get_db() as con:
        rows = con.execute("""
            SELECT DISTINCT sku, descricao, unidade,
                   SUM(quantidade) as total,
                   MIN(validade) as proxima_validade,
                   COUNT(*) as num_lotes
            FROM lotes WHERE ativo=1 GROUP BY sku ORDER BY sku
        """).fetchall()
    return [dict(r) for r in rows]

# Métricas dashboard
@app.get("/api/metricas")
def metricas():
    with get_db() as con:
        total = con.execute("SELECT COUNT(*) FROM lotes WHERE ativo=1").fetchone()[0]
        ends  = con.execute("SELECT COUNT(DISTINCT endereco) FROM lotes WHERE ativo=1").fetchone()[0]
        skus  = con.execute("SELECT COUNT(DISTINCT sku) FROM lotes WHERE ativo=1").fetchone()[0]
        rows  = con.execute("SELECT validade FROM lotes WHERE ativo=1 AND quantidade>0").fetchall()
    vencidos = sum(1 for r in rows if dias_ate_vencer(r[0]) < 0)
    atencao  = sum(1 for r in rows if 0 <= dias_ate_vencer(r[0]) <= 30)
    return {"total_lotes": total, "total_enderecos": ends,
            "total_skus": skus, "vencidos": vencidos, "atencao": atencao}

# Movimentos
@app.get("/api/movimentos")
def listar_movimentos(lote_id: Optional[int] = None, limit: int = 50):
    with get_db() as con:
        if lote_id:
            rows = con.execute("""
                SELECT m.*, l.sku, l.lote as num_lote, l.endereco
                FROM movimentos m JOIN lotes l ON m.lote_id=l.id
                WHERE m.lote_id=? ORDER BY m.data_mov DESC LIMIT ?
            """, (lote_id, limit)).fetchall()
        else:
            rows = con.execute("""
                SELECT m.*, l.sku, l.lote as num_lote, l.endereco
                FROM movimentos m JOIN lotes l ON m.lote_id=l.id
                ORDER BY m.data_mov DESC LIMIT ?
            """, (limit,)).fetchall()
    return [dict(r) for r in rows]

# Importar CSV
@app.post("/api/importar")
async def importar_csv(payload: dict):
    linhas = payload.get("linhas", [])
    ok, erros = 0, []
    with get_db() as con:
        for i, l in enumerate(linhas, 1):
            try:
                sku = l.get("sku","").strip().upper()
                lote = l.get("lote","").strip().upper()
                val = l.get("validade","").strip()
                end = l.get("endereco","").strip().upper()
                qty = float(l.get("quantidade", 0))
                if not all([sku, lote, val, end]) or qty <= 0:
                    erros.append(f"Linha {i}: dados incompletos")
                    continue
                cur = con.execute("""
                    INSERT INTO lotes (sku,descricao,lote,validade,quantidade,unidade,endereco,fornecedor)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (sku, l.get("descricao",""), lote, val, qty,
                      l.get("unidade","UN"), end, l.get("fornecedor","")))
                con.execute("INSERT INTO movimentos (lote_id,tipo,quantidade,usuario) VALUES (?,?,?,?)",
                            (cur.lastrowid, "ENTRADA", qty, "importacao_csv"))
                ok += 1
            except Exception as e:
                erros.append(f"Linha {i}: {str(e)}")
        con.commit()
    return {"importados": ok, "erros": erros}

# Export CSV
@app.get("/api/exportar")
def exportar():
    with get_db() as con:
        rows = con.execute("SELECT * FROM lotes WHERE ativo=1 ORDER BY validade").fetchall()
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["id","sku","descricao","lote","validade","quantidade","unidade","endereco","fornecedor","data_receb"])
    for r in rows:
        w.writerow([r["id"],r["sku"],r["descricao"],r["lote"],r["validade"],
                    r["quantidade"],r["unidade"],r["endereco"],r["fornecedor"],r["data_receb"]])
    from fastapi.responses import StreamingResponse
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=fefo_estoque.csv"})

app.mount("/static", StaticFiles(directory="static"), name="static")
