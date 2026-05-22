from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional
import os, csv, io
from datetime import date, datetime
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL:
    import psycopg
    from psycopg.rows import dict_row
    def get_conn():
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        return psycopg.connect(url, row_factory=dict_row)
    PH = "%s"
else:
    import sqlite3
    def get_conn():
        con = sqlite3.connect("fefo.db")
        con.row_factory = sqlite3.Row
        return con
    PH = "?"

@contextmanager
def get_db():
    con = get_conn()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def init_db():
    with get_db() as con:
        cur = con.cursor()
        if DATABASE_URL:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS lotes (
                id          SERIAL PRIMARY KEY,
                sku         TEXT    NOT NULL,
                descricao   TEXT,
                lote        TEXT    NOT NULL,
                validade    TEXT    NOT NULL,
                quantidade  NUMERIC NOT NULL,
                unidade     TEXT    DEFAULT 'UN',
                endereco    TEXT    NOT NULL,
                fornecedor  TEXT,
                data_receb  TEXT    DEFAULT (CURRENT_DATE::text),
                ativo       INTEGER DEFAULT 1
            )""")
            cur.execute("""
            CREATE TABLE IF NOT EXISTS movimentos (
                id          SERIAL PRIMARY KEY,
                lote_id     INTEGER REFERENCES lotes(id),
                tipo        TEXT,
                quantidade  NUMERIC,
                usuario     TEXT,
                obs         TEXT,
                data_mov    TEXT DEFAULT (NOW()::text)
            )""")
        else:
            cur.execute("""
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
            cur.execute("""
            CREATE TABLE IF NOT EXISTS movimentos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                lote_id     INTEGER REFERENCES lotes(id),
                tipo        TEXT,
                quantidade  REAL,
                usuario     TEXT,
                obs         TEXT,
                data_mov    TEXT DEFAULT (datetime('now'))
            )""")

app = FastAPI(title="FEFO WMS Controller")
init_db()

class LoteIn(BaseModel):
    sku:        str
    descricao:  Optional[str] = ""
    lote:       str
    validade:   str
    quantidade: float
    unidade:    Optional[str] = "UN"
    endereco:   str
    fornecedor: Optional[str] = ""

class MovimentoIn(BaseModel):
    tipo:       str
    quantidade: float
    usuario:    Optional[str] = "sistema"
    obs:        Optional[str] = ""

class LoteUpdate(BaseModel):
    descricao:  Optional[str] = None
    validade:   Optional[str] = None
    quantidade: Optional[float] = None
    endereco:   Optional[str] = None
    fornecedor: Optional[str] = None

def dias_ate_vencer(validade: str) -> int:
    try:
        v = datetime.strptime(str(validade)[:10], "%Y-%m-%d").date()
        return (v - date.today()).days
    except:
        return 999

def row_to_dict(row) -> dict:
    d = dict(row)
    d["dias_validade"] = dias_ate_vencer(d.get("validade",""))
    d["status"] = (
        "vencido"  if d["dias_validade"] < 0  else
        "critico"  if d["dias_validade"] <= 7  else
        "atencao"  if d["dias_validade"] <= 30 else
        "ok"
    )
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = str(v)
    return d

def normalizar_data(val: str) -> str:
    val = str(val).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except:
            pass
    raise ValueError(f"Data inválida: {val}")

def like_op():
    return "ILIKE" if DATABASE_URL else "LIKE"

@app.get("/", response_class=HTMLResponse)
def root():
    return FileResponse("templates/index.html")

@app.get("/api/lotes")
def listar_lotes(sku: str = "", endereco: str = "", status: str = ""):
    with get_db() as con:
        cur = con.cursor()
        q = "SELECT * FROM lotes WHERE ativo=1"
        params = []
        if sku:
            q += f" AND (sku {like_op()} {PH} OR descricao {like_op()} {PH})"
            params += [f"%{sku}%", f"%{sku}%"]
        if endereco:
            q += f" AND endereco {like_op()} {PH}"
            params.append(f"%{endereco}%")
        q += " ORDER BY validade ASC"
        cur.execute(q, params)
        dados = [row_to_dict(r) for r in cur.fetchall()]
    if status:
        dados = [d for d in dados if d["status"] == status]
    return dados

@app.post("/api/lotes", status_code=201)
def criar_lote(lote: LoteIn):
    with get_db() as con:
        cur = con.cursor()
        if DATABASE_URL:
            cur.execute(f"""
                INSERT INTO lotes (sku,descricao,lote,validade,quantidade,unidade,endereco,fornecedor)
                VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH}) RETURNING id
            """, (lote.sku.upper(), lote.descricao, lote.lote.upper(),
                  lote.validade, lote.quantidade, lote.unidade,
                  lote.endereco.upper(), lote.fornecedor))
            lote_id = cur.fetchone()["id"]
        else:
            cur.execute(f"""
                INSERT INTO lotes (sku,descricao,lote,validade,quantidade,unidade,endereco,fornecedor)
                VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})
            """, (lote.sku.upper(), lote.descricao, lote.lote.upper(),
                  lote.validade, lote.quantidade, lote.unidade,
                  lote.endereco.upper(), lote.fornecedor))
            lote_id = cur.lastrowid
        cur.execute(f"INSERT INTO movimentos (lote_id,tipo,quantidade,usuario,obs) VALUES ({PH},{PH},{PH},{PH},{PH})",
                    (lote_id, "ENTRADA", lote.quantidade, "recebimento", f"Recebimento - {lote.fornecedor}"))
        cur.execute(f"SELECT * FROM lotes WHERE id={PH}", (lote_id,))
        return row_to_dict(cur.fetchone())

@app.patch("/api/lotes/{lote_id}")
def atualizar_lote(lote_id: int, upd: LoteUpdate):
    with get_db() as con:
        cur = con.cursor()
        fields, vals = [], []
        for k, v in upd.dict(exclude_none=True).items():
            fields.append(f"{k}={PH}")
            vals.append(v.upper() if k == "endereco" else v)
        if fields:
            cur.execute(f"UPDATE lotes SET {','.join(fields)} WHERE id={PH}", vals + [lote_id])
        cur.execute(f"SELECT * FROM lotes WHERE id={PH}", (lote_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Lote não encontrado")
        return row_to_dict(row)

@app.delete("/api/lotes/{lote_id}")
def remover_lote(lote_id: int):
    with get_db() as con:
        con.cursor().execute(f"UPDATE lotes SET ativo=0 WHERE id={PH}", (lote_id,))
    return {"ok": True}

@app.post("/api/lotes/{lote_id}/movimentos")
def registrar_movimento(lote_id: int, mov: MovimentoIn):
    with get_db() as con:
        cur = con.cursor()
        cur.execute(f"SELECT * FROM lotes WHERE id={PH} AND ativo=1", (lote_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Lote não encontrado")
        nova_qty = float(row["quantidade"])
        if mov.tipo == "SAIDA":
            if mov.quantidade > nova_qty:
                raise HTTPException(400, f"Insuficiente. Disponível: {nova_qty}")
            nova_qty -= mov.quantidade
        elif mov.tipo == "ENTRADA":
            nova_qty += mov.quantidade
        elif mov.tipo == "AJUSTE":
            nova_qty = mov.quantidade
        cur.execute(f"UPDATE lotes SET quantidade={PH} WHERE id={PH}", (nova_qty, lote_id))
        cur.execute(f"INSERT INTO movimentos (lote_id,tipo,quantidade,usuario,obs) VALUES ({PH},{PH},{PH},{PH},{PH})",
                    (lote_id, mov.tipo, mov.quantidade, mov.usuario, mov.obs))
        cur.execute(f"SELECT * FROM lotes WHERE id={PH}", (lote_id,))
        return row_to_dict(cur.fetchone())

@app.get("/api/fefo")
def consultar_fefo(sku: str, quantidade: float = 0):
    with get_db() as con:
        cur = con.cursor()
        cur.execute(f"SELECT * FROM lotes WHERE sku {like_op()} {PH} AND ativo=1 AND quantidade>0 ORDER BY validade ASC",
                    (sku.upper(),))
        dados = [row_to_dict(r) for r in cur.fetchall()]
    if not dados:
        raise HTTPException(404, "Nenhum lote disponível")
    restante = quantidade
    for d in dados:
        if restante > 0:
            d["separar"] = min(float(d["quantidade"]), restante)
            restante -= d["separar"]
        else:
            d["separar"] = 0
    return {"sku": sku.upper(), "descricao": dados[0].get("descricao",""),
            "total_disponivel": sum(float(d["quantidade"]) for d in dados),
            "quantidade_solicitada": quantidade, "cobertura_ok": restante <= 0,
            "falta": max(0, restante), "lotes": dados}

@app.get("/api/skus/{sku_code}")
def buscar_sku(sku_code: str):
    with get_db() as con:
        cur = con.cursor()
        cur.execute(f"SELECT sku,descricao,unidade,fornecedor FROM lotes WHERE sku {like_op()} {PH} AND ativo=1 ORDER BY id DESC LIMIT 1",
                    (sku_code.upper(),))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "SKU não encontrado")
    return dict(row)

@app.get("/api/skus")
def listar_skus():
    with get_db() as con:
        cur = con.cursor()
        cur.execute("SELECT sku,descricao,unidade,SUM(quantidade) as total,MIN(validade) as proxima_validade,COUNT(*) as num_lotes FROM lotes WHERE ativo=1 GROUP BY sku,descricao,unidade ORDER BY sku")
        return [dict(r) for r in cur.fetchall()]

@app.get("/api/metricas")
def metricas():
    with get_db() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) as n FROM lotes WHERE ativo=1"); total = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(DISTINCT endereco) as n FROM lotes WHERE ativo=1"); ends = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(DISTINCT sku) as n FROM lotes WHERE ativo=1"); skus = cur.fetchone()["n"]
        cur.execute("SELECT validade FROM lotes WHERE ativo=1 AND quantidade>0")
        rows = cur.fetchall()
    vencidos = sum(1 for r in rows if dias_ate_vencer(dict(r)["validade"]) < 0)
    atencao  = sum(1 for r in rows if 0 <= dias_ate_vencer(dict(r)["validade"]) <= 30)
    return {"total_lotes": total, "total_enderecos": ends, "total_skus": skus,
            "vencidos": vencidos, "atencao": atencao}

@app.get("/api/movimentos")
def listar_movimentos(lote_id: Optional[int] = None, limit: int = 50):
    with get_db() as con:
        cur = con.cursor()
        if lote_id:
            cur.execute(f"SELECT m.*,l.sku,l.lote as num_lote,l.endereco FROM movimentos m JOIN lotes l ON m.lote_id=l.id WHERE m.lote_id={PH} ORDER BY m.data_mov DESC LIMIT {PH}", (lote_id, limit))
        else:
            cur.execute(f"SELECT m.*,l.sku,l.lote as num_lote,l.endereco FROM movimentos m JOIN lotes l ON m.lote_id=l.id ORDER BY m.data_mov DESC LIMIT {PH}", (limit,))
        return [dict(r) for r in cur.fetchall()]

@app.post("/api/importar")
async def importar_csv(payload: dict):
    linhas = payload.get("linhas", [])
    ok, erros = 0, []
    with get_db() as con:
        cur = con.cursor()
        for i, l in enumerate(linhas, 1):
            try:
                sku  = l.get("sku","").strip().upper()
                lote = l.get("lote","").strip().upper()
                val  = normalizar_data(l.get("validade",""))
                end  = l.get("endereco","").strip().upper() or "SEM-ENDERECO"
                qty  = float(str(l.get("quantidade","0")).strip().replace(",",".") or 0)
                if not all([sku, lote, val]) or qty <= 0:
                    erros.append(f"Linha {i}: incompleto"); continue
                if DATABASE_URL:
                    cur.execute(f"INSERT INTO lotes (sku,descricao,lote,validade,quantidade,unidade,endereco,fornecedor) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH}) RETURNING id",
                                (sku, l.get("descricao",""), lote, val, qty, l.get("unidade","UN") or "UN", end, l.get("fornecedor","")))
                    lid = cur.fetchone()["id"]
                else:
                    cur.execute(f"INSERT INTO lotes (sku,descricao,lote,validade,quantidade,unidade,endereco,fornecedor) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})",
                                (sku, l.get("descricao",""), lote, val, qty, l.get("unidade","UN") or "UN", end, l.get("fornecedor","")))
                    lid = cur.lastrowid
                cur.execute(f"INSERT INTO movimentos (lote_id,tipo,quantidade,usuario) VALUES ({PH},{PH},{PH},{PH})", (lid,"ENTRADA",qty,"importacao_csv"))
                ok += 1
            except Exception as e:
                erros.append(f"Linha {i}: {str(e)}")
    return {"importados": ok, "erros": erros}

@app.get("/api/exportar")
def exportar():
    with get_db() as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM lotes WHERE ativo=1 ORDER BY validade")
        rows = cur.fetchall()
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["id","sku","descricao","lote","validade","quantidade","unidade","endereco","fornecedor","data_receb"])
    for r in rows:
        d = dict(r)
        w.writerow([d.get(k,"") for k in ["id","sku","descricao","lote","validade","quantidade","unidade","endereco","fornecedor","data_receb"]])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=fefo_estoque.csv"})

static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
