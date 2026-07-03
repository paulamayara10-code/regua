# -*- coding: utf-8 -*-
"""
FIRST MEDICAL SERVICE
CRM de Cobrança
Versão inicial - upload diário de inadimplência Protheus

Funcionalidades principais:
- Upload diário do relatório "Títulos a receber vencidos".
- Histórico permanente em SQLite.
- Identificação automática de títulos novos, títulos mantidos em aberto e títulos pagos.
- Régua de cobrança configurável.
- Fila diária de ações.
- Registro de histórico por título/cliente.
- Campos manuais para vendedor e gerente do título.

Como rodar:
streamlit run app_crm_cobranca_first.py
"""

from __future__ import annotations

import sqlite3
import re
import html
import shutil
import base64
import json
import os
import hashlib
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
from datetime import date, datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

APP_NAME = "FIRST MEDICAL SERVICE"
APP_TITLE = "CRM de Cobrança"
APP_VERSION = "v4.1"
DATA_DIR = Path("dados")
BACKUP_DIR = DATA_DIR / "backup"
DB_PATH = DATA_DIR / "crm_cobranca_first.db"
LEGACY_DB_PATH = Path("crm_cobranca_first.db")

REQUIRED_COLUMNS = [
    "Filial", "Prefixo", "No. Titulo", "Parcela", "Tipo", "Cliente", "Loja",
    "Nome Cliente", "DT Emissao", "Vencto real", "Vlr.Titulo", "Saldo a receber"
]

DEFAULT_REGUA = [
    (1, "Email inicial", "Enviar e-mail de cobrança ao financeiro do cliente", "Financeiro", 1),
    (2, "Ligação", "Ligar para confirmar recebimento e previsão de pagamento", "Financeiro", 2),
    (3, "WhatsApp / reforço", "Enviar reforço por WhatsApp ou canal direto do cliente", "Financeiro", 3),
    (4, "Acionar vendedor", "Acionar vendedor responsável para apoio na cobrança", "Comercial", 4),
    (5, "Acionar gerente", "Acionar gerente comercial responsável", "Gerência Comercial", 5),
    (7, "Notificação formal", "Enviar notificação formal de cobrança", "Financeiro", 6),
    (10, "Diretoria comercial", "Escalar para diretoria/gestão comercial", "Diretoria", 7),
    (15, "Bloqueio / atenção", "Avaliar bloqueio comercial e restrição de novos pedidos", "Financeiro", 8),
    (30, "Jurídico", "Avaliar encaminhamento jurídico", "Jurídico", 9),
]

ACTION_OPTIONS = [
    "Email enviado",
    "Ligação realizada",
    "WhatsApp enviado",
    "Vendedor acionado",
    "Gerente acionado",
    "Notificação enviada",
    "Promessa de pagamento",
    "Cliente solicitou retorno",
    "Em conferência pelo cliente",
    "Encaminhado ao jurídico",
    "Pagamento identificado manualmente",
    "Agendar retorno",
    "Outro",
]

STATUS_ATIVO = "Em cobrança"
STATUS_PAGO = "Pago"
STATUS_PROMESSA = "Aguardando promessa"


# -----------------------------------------------------------------------------
# Configuração visual
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="CRM de Cobrança - First",
    page_icon="💼",
    layout="wide",
)

st.markdown(
    """
    <style>
        :root {
            --first-navy: #0B2341;
            --first-blue: #1267A8;
            --first-sky: #EAF5FF;
            --first-bg: #F4F7FB;
            --first-border: #DCE7F3;
            --first-text: #101828;
            --first-muted: #667085;
            --first-green: #12B76A;
            --first-yellow: #F79009;
            --first-red: #D92D20;
        }
        .main, [data-testid="stAppViewContainer"] {background: radial-gradient(circle at top left, #eef7ff 0, #f7f9fc 35%, #f4f7fb 100%);}
        .block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1480px;}
        [data-testid="stSidebar"] {background: linear-gradient(180deg, #0B2341 0%, #123E67 100%);}
        [data-testid="stSidebar"] * {color: #FFFFFF !important;}
        [data-testid="stSidebar"] div[data-testid="stRadio"] label {font-weight: 700;}
        [data-testid="stSidebar"] .stButton button {border-radius: 14px; border: 1px solid rgba(255,255,255,.25); background: rgba(255,255,255,.08); color: #fff;}
        .first-header {
            background:
              linear-gradient(135deg, rgba(11,35,65,.98) 0%, rgba(18,103,168,.96) 62%, rgba(58,166,255,.92) 100%);
            color: white; padding: 26px 30px; border-radius: 26px; margin-bottom: 20px;
            box-shadow: 0 18px 45px rgba(15,39,66,0.20); position: relative; overflow: hidden;
        }
        .first-header:after {content:""; position:absolute; right:-70px; top:-90px; width:260px; height:260px; border-radius:50%; background:rgba(255,255,255,.12);}        
        .first-header h1 {margin: 0; font-size: 34px; font-weight: 900; letter-spacing: -.03em;}
        .first-header p {margin: 7px 0 0 0; opacity: .94; font-weight: 600;}
        .first-chip {display:inline-flex; align-items:center; gap:8px; background: rgba(255,255,255,.15); border: 1px solid rgba(255,255,255,.22); border-radius: 999px; padding: 7px 12px; margin-top: 14px; font-size: 13px; font-weight: 750;}
        .section-title {font-size: 20px; font-weight: 850; color: #0B2341; margin: 18px 0 10px 0; letter-spacing: -.01em;}
        .metric-card {
            background: rgba(255,255,255,.94); border-radius: 22px; padding: 18px 19px; border: 1px solid var(--first-border);
            box-shadow: 0 10px 28px rgba(15,39,66,0.075); min-height: 112px;
            width: 100%; overflow: visible; box-sizing: border-box; border-left: 5px solid #1267A8;
        }
        .metric-card:hover {transform: translateY(-1px); transition: .15s ease; box-shadow: 0 14px 36px rgba(15,39,66,0.10);}        
        .metric-label {font-size: 11.5px; color: var(--first-muted); font-weight: 850; text-transform: uppercase; letter-spacing: .05em; line-height: 1.25;}
        .metric-value {font-size: clamp(21px, 2.15vw, 31px); color: var(--first-text); font-weight: 900; margin-top: 8px; line-height: 1.12; white-space: normal; overflow-wrap: anywhere; word-break: normal;}
        .metric-value.long-text {font-size: clamp(18px, 1.65vw, 26px);}
        .metric-help {font-size: 12.5px; color: #7B8798; margin-top: 6px; line-height: 1.28; white-space: normal; overflow-wrap: anywhere;}
        div[data-testid="stMetric"] {background: rgba(255,255,255,.94); border-radius: 20px; padding: 15px 16px; border: 1px solid var(--first-border); box-shadow: 0 9px 26px rgba(15,39,66,0.065); min-height: 104px; overflow: visible;}
        div[data-testid="stMetric"] label {white-space: normal !important; overflow-wrap: anywhere !important; color: var(--first-muted) !important; font-weight: 800 !important;}
        div[data-testid="stMetricValue"] {font-size: clamp(18px, 2vw, 28px) !important; white-space: normal !important; overflow: visible !important; text-overflow: unset !important; line-height: 1.15 !important; color: var(--first-text) !important; font-weight: 900 !important;}
        div[data-testid="stMetricValue"] > div {white-space: normal !important; overflow: visible !important; text-overflow: unset !important;}
        .section-card {
            background: rgba(255,255,255,.95); border-radius: 22px; padding: 19px; border: 1px solid var(--first-border);
            box-shadow: 0 10px 28px rgba(15,39,66,0.07); margin-bottom: 16px;
        }
        .action-card {background:#fff; border:1px solid var(--first-border); border-radius:18px; padding:15px 16px; box-shadow: 0 8px 20px rgba(15,39,66,.06); border-left: 5px solid #1267A8;}
        .action-title {font-size: 13px; color: #667085; font-weight: 850; text-transform: uppercase; letter-spacing: .04em;}
        .action-value {font-size: 24px; color:#0B2341; font-weight: 900; margin-top: 4px;}
        .small-muted {color:#667085; font-size:13px;}
        .first-alert-ok {background:#ECFDF3; border:1px solid #ABEFC6; color:#067647; border-radius:16px; padding:12px 14px; font-weight:700;}
        .first-alert-warn {background:#FFFAEB; border:1px solid #FEDF89; color:#B54708; border-radius:16px; padding:12px 14px; font-weight:700;}
        .first-alert-danger {background:#FEF3F2; border:1px solid #FECDCA; color:#B42318; border-radius:16px; padding:12px 14px; font-weight:700;}
        div[data-testid="stDataFrame"] {background:white; border-radius: 18px; overflow: hidden;}
        .stButton button, .stDownloadButton button {border-radius: 14px !important; font-weight: 800 !important; min-height: 42px;}
        .stTabs [data-baseweb="tab-list"] {gap: 8px;}
        .stTabs [data-baseweb="tab"] {border-radius: 999px; background: #FFFFFF; border: 1px solid var(--first-border); padding: 8px 16px;}
        .stTabs [aria-selected="true"] {background: #EAF5FF !important; color: #0B2341 !important; font-weight: 850;}

        .compact-header {padding: 22px 28px !important; margin-bottom: 18px !important;}
        .compact-header h1 {font-size: 32px !important;}
        [data-testid="stSidebar"] input, [data-testid="stSidebar"] textarea {color: #0B2341 !important; background: #FFFFFF !important;}
        [data-testid="stSidebar"] [data-baseweb="input"] * {color: #0B2341 !important;}
        [data-testid="stSidebar"] label, [data-testid="stSidebar"] p {color: #FFFFFF !important;}
        .sidebar-spacer {height: 22px;}
        .metric-card {min-height: 150px !important; display:flex; flex-direction:column; justify-content:flex-start;}
        .metric-value {font-size: clamp(18px, 1.65vw, 28px) !important; word-break: keep-all !important;}
        .metric-help {min-height: 32px;}
        .footer-first {margin-top: 28px; padding: 18px 8px; color: #667085; text-align:center; font-size: 13px;}
        .footer-first b {color:#0B2341;}
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------------------------------------------------------
# Armazenamento e backups
# -----------------------------------------------------------------------------
def ensure_storage_basic() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)



# -----------------------------------------------------------------------------
# Persistência externa no GitHub (opcional, recomendada para Streamlit Cloud)
# -----------------------------------------------------------------------------
def _secret_value(*names: str, default: str = "") -> str:
    """Busca configuração em st.secrets ou variáveis de ambiente, sem quebrar o app."""
    for name in names:
        try:
            val = st.secrets.get(name, "")
            if val:
                return str(val)
        except Exception:
            pass
        val = os.environ.get(name, "")
        if val:
            return str(val)
    return default


def github_config() -> Dict[str, str]:
    """Configuração do cofre de dados no GitHub.

    Secrets esperados no Streamlit:
    GITHUB_TOKEN = token com permissão Contents: Read and write
    GITHUB_REPO = "usuario/repositorio"
    GITHUB_BRANCH = "main"  (opcional)
    GITHUB_DB_PATH = "dados/crm_cobranca_first.db" (opcional)
    """
    token = _secret_value("GITHUB_TOKEN", "GH_TOKEN")
    repo = _secret_value("GITHUB_REPO", "GH_REPO")
    branch = _secret_value("GITHUB_BRANCH", "GH_BRANCH", default="main")
    path = _secret_value("GITHUB_DB_PATH", "GH_DB_PATH", default="dados/crm_cobranca_first.db")
    enabled = bool(token and repo and path)
    return {"enabled": enabled, "token": token, "repo": repo, "branch": branch, "path": path}


def _github_api_url(cfg: Dict[str, str]) -> str:
    return f"https://api.github.com/repos/{cfg['repo']}/contents/{cfg['path']}"


def _github_request(url: str, token: str, method: str = "GET", data: Optional[dict] = None) -> dict:
    payload = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "crm-cobranca-first",
    }
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=payload, headers=headers, method=method)
    with urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


def github_get_db() -> Tuple[Optional[bytes], Optional[str], str]:
    """Baixa o banco remoto. Retorna (bytes, sha, mensagem)."""
    cfg = github_config()
    if not cfg["enabled"]:
        return None, None, "Cofre GitHub não configurado."
    url = _github_api_url(cfg) + f"?ref={cfg['branch']}"
    try:
        info = _github_request(url, cfg["token"], "GET")
        content = base64.b64decode(info.get("content", "")) if info.get("content") else None
        return content, info.get("sha"), "Banco remoto encontrado."
    except HTTPError as e:
        if e.code == 404:
            return None, None, "Banco remoto ainda não existe. Será criado no primeiro salvamento."
        return None, None, f"Erro GitHub {e.code}: não foi possível ler o banco remoto."
    except Exception as e:
        return None, None, f"Erro ao acessar GitHub: {e}"


def download_db_from_github_if_needed() -> None:
    """Em ambiente Streamlit, restaura o banco remoto se o arquivo local não existir."""
    ensure_storage_basic()
    if DB_PATH.exists():
        return
    data, sha, msg = github_get_db()
    if data:
        DB_PATH.write_bytes(data)
        try:
            st.session_state["github_last_sha"] = sha or ""
            st.session_state["github_last_sync"] = datetime.now().isoformat(timespec="seconds")
            st.session_state["github_sync_msg"] = "Banco restaurado do GitHub."
        except Exception:
            pass


def _db_sha256() -> str:
    if not DB_PATH.exists():
        return ""
    return hashlib.sha256(DB_PATH.read_bytes()).hexdigest()


def upload_db_to_github(reason: str = "sincronizacao") -> Tuple[bool, str]:
    """Envia o banco atual para o GitHub. Não apaga histórico; versiona no commit do GitHub."""
    cfg = github_config()
    if not cfg["enabled"]:
        return False, "Cofre GitHub não configurado."
    if not DB_PATH.exists():
        return False, "Banco local não encontrado."

    # Validação antes do envio para não subir arquivo corrompido.
    try:
        chk_conn = sqlite3.connect(DB_PATH)
        chk = chk_conn.execute("PRAGMA integrity_check").fetchone()[0]
        chk_conn.close()
        if chk != "ok":
            return False, f"Banco local inválido: {chk}. Sincronização cancelada."
    except Exception as e:
        return False, f"Não foi possível validar o banco local: {e}"

    local_hash = _db_sha256()
    if st.session_state.get("github_last_hash") == local_hash:
        return True, "Sem alterações para sincronizar."

    data, current_sha, _ = github_get_db()
    b64 = base64.b64encode(DB_PATH.read_bytes()).decode("ascii")
    body = {
        "message": f"backup CRM cobranca - {reason} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "content": b64,
        "branch": cfg["branch"],
    }
    if current_sha:
        body["sha"] = current_sha

    try:
        resp = _github_request(_github_api_url(cfg), cfg["token"], "PUT", body)
        st.session_state["github_last_hash"] = local_hash
        st.session_state["github_last_sha"] = resp.get("content", {}).get("sha", "")
        st.session_state["github_last_sync"] = datetime.now().isoformat(timespec="seconds")
        st.session_state["github_sync_msg"] = "Banco salvo no GitHub."
        return True, "Banco salvo no GitHub."
    except Exception as e:
        st.session_state["github_sync_msg"] = f"Falha ao salvar no GitHub: {e}"
        return False, f"Falha ao salvar no GitHub: {e}"


def github_status() -> Dict[str, str]:
    cfg = github_config()
    if not cfg["enabled"]:
        return {"status": "não configurado", "repo": "", "path": "", "last_sync": ""}
    return {
        "status": "configurado",
        "repo": cfg["repo"],
        "path": cfg["path"],
        "last_sync": st.session_state.get("github_last_sync", ""),
    }


def ensure_storage() -> None:
    ensure_storage_basic()
    download_db_from_github_if_needed()
    # Migração automática do banco antigo, caso exista na raiz do app.
    if LEGACY_DB_PATH.exists() and not DB_PATH.exists():
        shutil.copy2(LEGACY_DB_PATH, DB_PATH)


def backup_db(motivo: str = "manual") -> Optional[Path]:
    ensure_storage()
    if not DB_PATH.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_motivo = "".join(ch if ch.isalnum() else "_" for ch in str(motivo))[:30] or "backup"
    destino = BACKUP_DIR / f"crm_cobranca_{safe_motivo}_{stamp}.db"
    shutil.copy2(DB_PATH, destino)
    return destino


def export_backup_zip() -> bytes:
    ensure_storage()
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        if DB_PATH.exists():
            z.write(DB_PATH, arcname="dados/crm_cobranca_first.db")
        for bkp in sorted(BACKUP_DIR.glob("*.db"))[-10:]:
            z.write(bkp, arcname=f"dados/backup/{bkp.name}")
        # manifesto simples para conferência
        manifesto = f"Exportado em {datetime.now().isoformat(timespec='seconds')}\nBanco: {DB_PATH}\n"
        z.writestr("manifesto.txt", manifesto)
    return output.getvalue()




def restore_backup_file(uploaded_file) -> str:
    """Restaura o banco a partir de um pacote ZIP exportado pelo app ou de um .db direto."""
    ensure_storage()
    if uploaded_file is None:
        raise ValueError("Nenhum arquivo selecionado.")
    name = str(getattr(uploaded_file, "name", "backup"))
    data = uploaded_file.read()
    # Sempre preserva o banco atual antes de substituir.
    backup_db("antes_restaurar")

    if name.lower().endswith(".zip"):
        with zipfile.ZipFile(BytesIO(data)) as z:
            candidates = [n for n in z.namelist() if n.endswith("crm_cobranca_first.db")]
            if not candidates:
                raise ValueError("O ZIP não contém o arquivo crm_cobranca_first.db.")
            db_bytes = z.read(candidates[0])
    elif name.lower().endswith(".db"):
        db_bytes = data
    else:
        raise ValueError("Envie um backup .zip gerado pelo app ou o arquivo .db do CRM.")

    # Valida integridade antes de substituir definitivamente.
    tmp = DATA_DIR / "_restore_test.db"
    tmp.write_bytes(db_bytes)
    test_conn = sqlite3.connect(tmp)
    try:
        chk = test_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if chk != "ok":
            raise ValueError(f"Banco inválido: {chk}")
    finally:
        test_conn.close()
    shutil.copy2(tmp, DB_PATH)
    tmp.unlink(missing_ok=True)
    return name

def db_health() -> Dict[str, object]:
    ensure_storage()
    if not DB_PATH.exists():
        return {"ok": False, "clientes": 0, "titulos": 0, "historico": 0, "ultimo_backup": ""}
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA integrity_check")
        ok = cur.fetchone()[0] == "ok"
        def count_table(name):
            try:
                cur.execute(f"SELECT COUNT(*) FROM {name}")
                return cur.fetchone()[0]
            except Exception:
                return 0
        backups = sorted(BACKUP_DIR.glob("*.db"))
        return {
            "ok": ok,
            "clientes": count_table("clientes"),
            "titulos": count_table("titulos"),
            "historico": count_table("historico_acoes"),
            "ultimo_backup": backups[-1].name if backups else "",
        }
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# Banco de dados
# -----------------------------------------------------------------------------

def ultimo_backup_info() -> Tuple[Optional[Path], Optional[int]]:
    """Retorna o backup mais recente e a idade em dias."""
    ensure_storage()
    backups = sorted(BACKUP_DIR.glob("*.db"), key=lambda x: x.stat().st_mtime if x.exists() else 0)
    if not backups:
        return None, None
    ultimo = backups[-1]
    idade = (datetime.now() - datetime.fromtimestamp(ultimo.stat().st_mtime)).days
    return ultimo, idade


def backup_status_html() -> str:
    ultimo, idade = ultimo_backup_info()
    if ultimo is None:
        return '<div class="first-alert-danger">Backup: nenhum backup local encontrado.</div>'
    if idade is not None and idade >= 2:
        return f'<div class="first-alert-warn">Backup: último backup há {idade} dia(s).</div>'
    return f'<div class="first-alert-ok">Backup: atualizado • {html.escape(ultimo.name)}</div>'


def fila_to_export(df: pd.DataFrame) -> pd.DataFrame:
    """Prepara a fila de clientes para exportação."""
    if df.empty:
        return df
    out = df.copy()
    out["Valor total"] = out["saldo_total"].apply(br_money)
    out["Vencimento mais antigo"] = pd.to_datetime(out["menor_vencimento"], errors="coerce").dt.strftime("%d/%m/%Y")
    keep = [
        "nome_cliente", "tipo_cliente", "cobrador", "qtd_titulos", "Valor total",
        "Vencimento mais antigo", "maior_dias_atraso", "dia_regua", "acao_do_dia",
        "vendedor", "gerente", "observacoes"
    ]
    keep = [c for c in keep if c in out.columns]
    return out[keep].rename(columns={
        "nome_cliente": "Cliente", "tipo_cliente": "Tipo de cliente", "cobrador": "Cobrador",
        "qtd_titulos": "Títulos", "maior_dias_atraso": "Maior atraso",
        "dia_regua": "Dia régua", "acao_do_dia": "Ação do dia",
        "vendedor": "Vendedor", "gerente": "Gerente", "observacoes": "Observações"
    })

def get_conn() -> sqlite3.Connection:
    ensure_storage()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    # Segurança: antes de qualquer migração de estrutura, preserva o banco atual.
    ensure_storage()
    if DB_PATH.exists():
        backup_db("antes_migracao_v4")
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS titulos (
            titulo_id TEXT PRIMARY KEY,
            filial TEXT,
            prefixo TEXT,
            numero_titulo TEXT,
            parcela TEXT,
            tipo TEXT,
            cliente_codigo TEXT,
            loja TEXT,
            nome_cliente TEXT,
            dt_emissao TEXT,
            vencimento TEXT,
            valor_titulo REAL,
            saldo_original REAL,
            saldo_atual REAL,
            multa REAL DEFAULT 0,
            juros REAL DEFAULT 0,
            vendedor TEXT DEFAULT '',
            gerente TEXT DEFAULT '',
            status TEXT DEFAULT 'Em cobrança',
            primeira_aparicao TEXT,
            ultima_aparicao TEXT,
            data_baixa TEXT,
            ciclo_cobranca INTEGER DEFAULT 1,
            promessa_pagamento TEXT,
            observacao_atual TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clientes (
            cliente_id TEXT PRIMARY KEY,
            cliente_codigo TEXT,
            loja TEXT,
            nome_cliente TEXT,
            vendedor TEXT DEFAULT '',
            gerente TEXT DEFAULT '',
            tipo_cliente TEXT DEFAULT 'Não especial',
            cobrador TEXT DEFAULT '',
            observacao TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS historico_acoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo_id TEXT,
            data_acao TEXT,
            tipo_acao TEXT,
            responsavel TEXT,
            observacao TEXT,
            promessa_pagamento TEXT,
            created_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_referencia TEXT,
            arquivo TEXT,
            qtd_linhas INTEGER,
            novos INTEGER,
            atualizados INTEGER,
            pagos INTEGER,
            valor_aberto REAL,
            created_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS regua_cobranca (
            dia INTEGER PRIMARY KEY,
            acao TEXT,
            descricao TEXT,
            responsavel_padrao TEXT,
            prioridade INTEGER
        )
        """
    )



    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS agenda_retorno (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id TEXT,
            cliente_codigo TEXT,
            loja TEXT,
            nome_cliente TEXT,
            data_retorno TEXT,
            motivo TEXT,
            responsavel TEXT,
            status TEXT DEFAULT 'Pendente',
            data_conclusao TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS config (
            chave TEXT PRIMARY KEY,
            valor TEXT DEFAULT '',
            updated_at TEXT
        )
        """
    )

    def ensure_column(table: str, column: str, definition: str) -> None:
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    ensure_column("clientes", "tipo_cliente", "TEXT DEFAULT 'Não especial'")
    ensure_column("clientes", "cobrador", "TEXT DEFAULT ''")
    ensure_column("clientes", "razao_social", "TEXT DEFAULT ''")
    ensure_column("clientes", "cnpj", "TEXT DEFAULT ''")
    ensure_column("clientes", "contato", "TEXT DEFAULT ''")
    ensure_column("titulos", "razao_social", "TEXT DEFAULT ''")
    ensure_column("titulos", "cnpj", "TEXT DEFAULT ''")
    ensure_column("titulos", "contato", "TEXT DEFAULT ''")
    ensure_column("titulos", "origem_vendedor", "TEXT DEFAULT ''")
    ensure_column("titulos", "origem_gerente", "TEXT DEFAULT ''")
    ensure_column("uploads", "base_bi_cruzados", "INTEGER DEFAULT 0")
    ensure_column("uploads", "base_bi_nao_localizados", "INTEGER DEFAULT 0")
    ensure_column("uploads", "base_bi_status", "TEXT DEFAULT ''")

    cur.execute("SELECT COUNT(*) AS total FROM regua_cobranca")
    if cur.fetchone()["total"] == 0:
        cur.executemany(
            "INSERT INTO regua_cobranca (dia, acao, descricao, responsavel_padrao, prioridade) VALUES (?, ?, ?, ?, ?)",
            DEFAULT_REGUA,
        )

    conn.commit()
    conn.close()


# -----------------------------------------------------------------------------
# Utilidades
# -----------------------------------------------------------------------------
def br_money(value: float | int | None) -> str:
    value = float(value or 0)
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def br_money_short(value: float | int | None) -> str:
    value = float(value or 0)
    abs_value = abs(value)
    sign = "-" if value < 0 else ""
    if abs_value >= 1_000_000:
        txt = f"{sign}R$ {abs_value / 1_000_000:.1f} mi"
    elif abs_value >= 1_000:
        txt = f"{sign}R$ {abs_value / 1_000:.1f} mil"
    else:
        txt = f"{sign}R$ {abs_value:,.2f}"
    return txt.replace(",", "X").replace(".", ",").replace("X", ".")


def to_date_str(value) -> Optional[str]:
    if pd.isna(value) or value == "":
        return None
    try:
        # Quando o Excel é lido sem openpyxl, datas podem chegar como número serial.
        if isinstance(value, (int, float)) and value > 20000:
            return pd.to_datetime(value, unit="D", origin="1899-12-30").date().isoformat()
        return pd.to_datetime(value, dayfirst=True).date().isoformat()
    except Exception:
        return None


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except Exception:
        return None


def normalize_text(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text




def clean_history_text(value) -> str:
    """Remove ruídos vindos de planilhas antigas de cobrança."""
    txt = normalize_text(value)
    if not txt:
        return ""
    # Remove marcadores importados por engano de colunas de decisão/status e datas soltas.
    txt = re.sub(r"\bDecis[aã]o/status:\s*", "", txt, flags=re.IGNORECASE)
    txt = re.sub(r"\bDecis[aã]o\s*/\s*status\s*[:;-]?\s*", "", txt, flags=re.IGNORECASE)
    txt = re.sub(r"\b(?:19|20)\d{2}-\d{2}-\d{2}(?:\s+00:00:00)?\b", "", txt)
    txt = re.sub(r"\b(?:nan|none|nat)\b", "", txt, flags=re.IGNORECASE)
    # Remove repetições e espaços duplicados.
    txt = re.sub(r"\s+", " ", txt).strip(" -;|•")
    # Evita frases vazias após limpeza.
    if txt.lower() in {"cliente", "status", "decisao", "decisão"}:
        return ""
    return txt


def make_titulo_id(row: pd.Series) -> str:
    parts = [
        normalize_text(row.get("Filial")),
        normalize_text(row.get("Prefixo")),
        normalize_text(row.get("No. Titulo")),
        normalize_text(row.get("Parcela")),
        normalize_text(row.get("Tipo")),
        normalize_text(row.get("Cliente")),
        normalize_text(row.get("Loja")),
    ]
    return "|".join(parts).upper()


def calcular_dias_atraso(vencimento: Optional[str], ref: date) -> int:
    venc = parse_iso_date(vencimento)
    if not venc:
        return 0
    return max((ref - venc).days, 0)


def calcular_ciclo(primeira: Optional[str], ref: date) -> int:
    pri = parse_iso_date(primeira)
    if not pri:
        return 1
    return max((ref - pri).days + 1, 1)


def _xlsx_fallback_to_dataframe(file_bytes: bytes) -> pd.DataFrame:
    """Leitor simples de XLSX sem openpyxl.

    Foi incluído para evitar que o app pare no Streamlit Cloud quando o ambiente
    ainda não instalou o pacote openpyxl. Lê a primeira aba do arquivo exportado
    pelo Protheus, preservando textos, números e datas seriais do Excel.
    """
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    def col_to_idx(cell_ref: str) -> int:
        letters = "".join(ch for ch in cell_ref if ch.isalpha())
        idx = 0
        for ch in letters:
            idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
        return idx - 1

    with zipfile.ZipFile(BytesIO(file_bytes)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", ns):
                texts = [t.text or "" for t in si.findall(".//a:t", ns)]
                shared.append("".join(texts))

        # Primeira planilha visível do arquivo. Para o relatório Protheus, normalmente é sheet1.xml.
        sheet_name = "xl/worksheets/sheet1.xml"
        if sheet_name not in z.namelist():
            sheets = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
            if not sheets:
                raise ValueError("Não encontrei nenhuma aba no arquivo XLSX.")
            sheet_name = sorted(sheets)[0]

        root = ET.fromstring(z.read(sheet_name))
        rows = []
        max_cols = 0
        for row in root.findall(".//a:sheetData/a:row", ns):
            values = []
            for cell in row.findall("a:c", ns):
                idx = col_to_idx(cell.attrib.get("r", "A1"))
                while len(values) <= idx:
                    values.append(None)
                cell_type = cell.attrib.get("t")
                v = cell.find("a:v", ns)
                is_node = cell.find("a:is", ns)
                value = None
                if cell_type == "s" and v is not None:
                    try:
                        value = shared[int(v.text)]
                    except Exception:
                        value = v.text
                elif cell_type == "inlineStr" and is_node is not None:
                    value = "".join(t.text or "" for t in is_node.findall(".//a:t", ns))
                elif v is not None:
                    raw = v.text
                    try:
                        num = float(raw)
                        value = int(num) if num.is_integer() else num
                    except Exception:
                        value = raw
                values[idx] = value
            if any(v not in (None, "") for v in values):
                max_cols = max(max_cols, len(values))
                rows.append(values)

    if not rows:
        raise ValueError("A planilha está vazia.")

    rows = [r + [None] * (max_cols - len(r)) for r in rows]
    header_idx = None
    for i, row in enumerate(rows[:20]):
        normalized = [str(x).strip() if x is not None else "" for x in row]
        if "Filial" in normalized and "No. Titulo" in normalized:
            header_idx = i
            break
    if header_idx is None:
        header_idx = 0

    header = [str(x).strip() if x is not None else f"Coluna_{i+1}" for i, x in enumerate(rows[header_idx])]
    data = rows[header_idx + 1:]
    df = pd.DataFrame(data, columns=header)
    df = df.dropna(how="all")
    return df


def read_excel_upload(file) -> pd.DataFrame:
    file_bytes = file.read() if hasattr(file, "read") else bytes(file)
    try:
        df = pd.read_excel(BytesIO(file_bytes))
    except Exception as exc:
        # Fallback para ambientes onde o openpyxl não foi instalado/atualizado ainda.
        if "openpyxl" not in str(exc).lower() and "excel" not in str(exc).lower():
            raise
        df = _xlsx_fallback_to_dataframe(file_bytes)

    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas não encontradas no arquivo: {', '.join(missing)}")

    df = df.copy()
    df["titulo_id"] = df.apply(make_titulo_id, axis=1)
    df["dt_emissao_str"] = df["DT Emissao"].apply(to_date_str)
    df["vencimento_str"] = df["Vencto real"].apply(to_date_str)

    for col in ["Vlr.Titulo", "Saldo a receber", "Multa", "Juros"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df = df.drop_duplicates(subset=["titulo_id"], keep="last")
    return df


def read_github_base(raw_url: str) -> pd.DataFrame:
    if not raw_url.strip():
        raise ValueError("Informe a URL raw do arquivo no GitHub.")
    with urlopen(raw_url.strip(), timeout=30) as response:
        data = response.read()
    return read_excel_upload(data)






def get_config(chave: str, default: str = "") -> str:
    conn = get_conn()
    try:
        row = conn.execute("SELECT valor FROM config WHERE chave = ?", (chave,)).fetchone()
        return str(row["valor"] or "") if row else default
    finally:
        conn.close()


def set_config(chave: str, valor: str) -> None:
    conn = get_conn()
    try:
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO config (chave, valor, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, updated_at = excluded.updated_at
            """,
            (chave, str(valor or "").strip(), now),
        )
        conn.commit()
    finally:
        conn.close()


def read_excel_any(file_or_bytes) -> pd.DataFrame:
    file_bytes = file_or_bytes.read() if hasattr(file_or_bytes, "read") else bytes(file_or_bytes)
    try:
        df = pd.read_excel(BytesIO(file_bytes))
    except Exception:
        try:
            df = pd.read_csv(BytesIO(file_bytes), sep=None, engine="python")
        except Exception:
            df = _xlsx_fallback_to_dataframe(file_bytes)
    df.columns = [str(c).strip() for c in df.columns]
    return df.dropna(how="all")


def normalize_col_key(value) -> str:
    txt = normalize_text(value).lower()
    txt = re.sub(r"[áàãâä]", "a", txt)
    txt = re.sub(r"[éèêë]", "e", txt)
    txt = re.sub(r"[íìîï]", "i", txt)
    txt = re.sub(r"[óòõôö]", "o", txt)
    txt = re.sub(r"[úùûü]", "u", txt)
    txt = re.sub(r"ç", "c", txt)
    return re.sub(r"[^a-z0-9]+", "", txt)


def find_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    lookup = {normalize_col_key(c): c for c in df.columns}
    for cand in candidates:
        key = normalize_col_key(cand)
        if key in lookup:
            return lookup[key]
    # busca aproximada: o candidato contido no nome da coluna
    for cand in candidates:
        key = normalize_col_key(cand)
        for col_key, col in lookup.items():
            if key and (key in col_key or col_key in key):
                return col
    return None


def _digits(value) -> str:
    return re.sub(r"\D+", "", normalize_text(value))


def normalize_note_key(value) -> str:
    """Normaliza NF/título para cruzamento seguro.

    Trata 00016843, 16843, 16843.0, NF 16843 e 003-000016843-001 como 16843.
    """
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    txt = normalize_text(value).upper().strip()
    if not txt:
        return ""
    if re.fullmatch(r"\d+(?:[,.]0+)?", txt):
        txt = re.sub(r"[,.]0+$", "", txt)
        return (txt.lstrip("0") or "0")
    nums = re.findall(r"\d+", txt)
    if not nums:
        return re.sub(r"[^A-Z0-9]+", "", txt)
    candidate = max(nums, key=len)
    return candidate.lstrip("0") or "0"


def build_faturamento_maps(df_base: pd.DataFrame) -> tuple[dict, dict, dict, dict]:
    """Cria mapas para enriquecer vendedor/gerente a partir da BASE BI.

    Prioridade no CRM: 1) Nota Fiscal/Título; 2) Cliente+loja; 3) Código; 4) Nome.
    """
    if df_base.empty:
        return {}, {}, {}, {}

    col_nota = find_col(df_base, [
        "Nota Fiscal", "NF", "N.F.", "Nº NF", "No NF", "Número NF", "Numero NF",
        "Nota", "Documento", "No. Titulo", "Nº Título", "Titulo", "Título"
    ])
    col_cliente = find_col(df_base, ["CLIENTE", "Cliente", "Cod Cliente", "Código Cliente", "Cod. Cliente", "A1_COD", "Codigo"])
    col_loja = find_col(df_base, ["Loja", "A1_LOJA"])
    col_nome = find_col(df_base, ["NOME DO CLIENTE", "Nome Cliente", "Cliente Nome", "Nome", "Nome Fantasia", "A1_NOME"])
    col_razao = find_col(df_base, ["Razão Social", "Razao Social", "NOME DO CLIENTE", "Nome Cliente", "A1_NREDUZ"])
    col_cnpj = find_col(df_base, ["CNPJ", "CPF/CNPJ", "CNPJ/CPF", "A1_CGC", "CGC"])
    col_contato = find_col(df_base, ["Contato", "Responsável", "Responsavel", "Contato Financeiro", "Email", "E-mail", "Telefone"])
    col_vendedor = find_col(df_base, ["VENDEDOR", "Vendedor", "Nome Vendedor", "Representante", "Consultor", "Comercial"])
    col_gerente = find_col(df_base, ["GERENTE", "Gerente", "Gerente Comercial", "Supervisor", "Coordenador"])

    by_nota, by_cliente_loja, by_cliente, by_nome = {}, {}, {}, {}
    for _, r in df_base.iterrows():
        info = {
            "vendedor": normalize_text(r.get(col_vendedor, "")) if col_vendedor else "",
            "gerente": normalize_text(r.get(col_gerente, "")) if col_gerente else "",
            "razao_social": normalize_text(r.get(col_razao, "")) if col_razao else "",
            "cnpj": normalize_text(r.get(col_cnpj, "")) if col_cnpj else "",
            "contato": normalize_text(r.get(col_contato, "")) if col_contato else "",
            "origem": "BASE BI",
        }
        if not (info.get("vendedor") or info.get("gerente") or info.get("razao_social")):
            continue

        nota_key = normalize_note_key(r.get(col_nota, "")) if col_nota else ""
        if nota_key and nota_key not in by_nota:
            by_nota[nota_key] = info

        cliente = normalize_text(r.get(col_cliente, "")) if col_cliente else ""
        loja = normalize_text(r.get(col_loja, "")) if col_loja else ""
        nome = normalize_text(r.get(col_nome, "")) if col_nome else ""
        if cliente and loja and f"{cliente}|{loja}".upper() not in by_cliente_loja:
            by_cliente_loja[f"{cliente}|{loja}".upper()] = info
        if cliente and cliente.upper() not in by_cliente:
            by_cliente[cliente.upper()] = info
        if nome and normalize_col_key(nome) not in by_nome:
            by_nome[normalize_col_key(nome)] = info
        cnpj = _digits(info.get("cnpj"))
        if cnpj and f"CNPJ:{cnpj}" not in by_nome:
            by_nome[f"CNPJ:{cnpj}"] = info
    return by_nota, by_cliente_loja, by_cliente, by_nome


def get_faturamento_info_for(row, maps: tuple) -> dict:
    if not maps:
        return {}
    if len(maps) == 4:
        by_nota, by_cliente_loja, by_cliente, by_nome = maps
    else:
        by_cliente_loja, by_cliente, by_nome = maps
        by_nota = {}
    nota_key = normalize_note_key(row.get("No. Titulo"))
    cliente = normalize_text(row.get("Cliente"))
    loja = normalize_text(row.get("Loja"))
    nome = normalize_text(row.get("Nome Cliente"))
    return (
        by_nota.get(nota_key)
        or by_cliente_loja.get(f"{cliente}|{loja}".upper())
        or by_cliente.get(cliente.upper())
        or by_nome.get(normalize_col_key(nome))
        or {}
    )


def load_faturamento_maps_from_github() -> tuple[tuple[dict, dict, dict, dict], str]:
    url = get_config("base_faturamento_github", "")
    if not url.strip():
        return ({}, {}, {}, {}), "BASE BI não configurada"
    with urlopen(url.strip(), timeout=35) as response:
        data = response.read()
    df_base = read_excel_any(data)
    maps = build_faturamento_maps(df_base)
    notas = len(maps[0]) if maps else 0
    return maps, f"{len(df_base)} linha(s) lida(s) • {notas} nota(s) mapeada(s)"


def parse_legacy_prf_numero(value) -> tuple[str, str, str]:
    """Extrai prefixo, número e parcela de campos como AFI-013998 ou 003-000016843-001."""
    txt = normalize_text(value).upper()
    if not txt:
        return "", "", ""
    parts = [x for x in re.split(r"[-\s]+", txt) if x]
    nums = re.findall(r"\d+", txt)
    prefixo = parts[0] if parts else ""
    numero = ""
    parcela = ""
    if len(nums) >= 3 and len(nums[-1]) <= 3:
        numero = nums[-2]
        parcela = nums[-1]
    elif nums:
        numero = nums[-1]
    return prefixo, numero, parcela


def parse_legacy_cliente(value) -> tuple[str, str, str]:
    """Lê campos no padrão Codigo-Lj-Nome do Cliente."""
    txt = normalize_text(value)
    m = re.match(r"^\s*(\d+)\s*-\s*([\w\d]+)\s*-\s*(.+)$", txt)
    if m:
        return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    return "", "", txt


def read_legacy_history_upload(file) -> pd.DataFrame:
    """Lê a planilha antiga de tomada de decisão e transforma em histórico por bloco de cliente.

    A planilha antiga costuma quebrar o texto do histórico em várias linhas do mesmo cliente.
    Por isso o app consolida o texto do bloco e aplica o histórico completo aos títulos/Notas
    encontrados naquele cliente.
    """
    file_bytes = file.read() if hasattr(file, "read") else bytes(file)
    try:
        raw = pd.read_excel(BytesIO(file_bytes))
    except Exception:
        raw = _xlsx_fallback_to_dataframe(file_bytes)

    raw.columns = [str(c).strip() for c in raw.columns]
    if raw.empty:
        raise ValueError("A planilha de histórico está vazia.")

    code_col = next((c for c in raw.columns if "Codigo" in c or "Código" in c), raw.columns[0])
    prf_col = next((c for c in raw.columns if "Prf" in c or "Numero" in c or "Número" in c), raw.columns[1] if len(raw.columns) > 1 else raw.columns[0])
    hist_col = next((c for c in raw.columns if "HIST" in c.upper()), None)
    if hist_col is None:
        raise ValueError("Não encontrei a coluna HISTÓRICO na planilha.")

    # Importamos somente a coluna HISTÓRICO.
    # As demais colunas da planilha antiga costumam trazer datas/status e geravam texto confuso.
    extra_cols = []

    blocks = []
    current = None

    def flush():
        nonlocal current
        if not current:
            return
        hist_lines = [h for h in current.get("hist_lines", []) if h]
        note_keys = sorted(set([k for k in current.get("note_keys", []) if k]))
        if hist_lines and note_keys:
            hist = " ".join(hist_lines)
            hist = clean_history_text(hist)
            if not hist:
                current = None
                return
            blocks.append({
                "cliente_codigo": current.get("cliente_codigo", ""),
                "loja": current.get("loja", ""),
                "nome_cliente": current.get("nome_cliente", ""),
                "notas": ", ".join(note_keys),
                "historico_legado": hist,
                "qtd_notas_planilha": len(note_keys),
            })
        current = None

    for _, row in raw.iterrows():
        code_val = normalize_text(row.get(code_col))
        prf_val = normalize_text(row.get(prf_col))
        hist_val = normalize_text(row.get(hist_col))

        # Ignora cabeçalhos repetidos e linhas totalmente vazias.
        if not code_val and not prf_val and not hist_val:
            flush()
            continue
        if "Codigo" in code_val and ("Nome" in code_val or "Cliente" in code_val):
            flush()
            continue

        # Linhas totalizadoras não possuem número do título; elas encerram o bloco.
        if not prf_val:
            flush()
            continue

        cliente_codigo, loja, nome_cliente = parse_legacy_cliente(code_val)
        _, numero, parcela = parse_legacy_prf_numero(prf_val)
        note_key = normalize_note_key(numero or prf_val)
        cid = make_cliente_id(cliente_codigo, loja, nome_cliente)

        if current is None or current.get("cliente_id") != cid:
            flush()
            current = {
                "cliente_id": cid,
                "cliente_codigo": cliente_codigo,
                "loja": loja,
                "nome_cliente": nome_cliente,
                "note_keys": [],
                "hist_lines": [],
            }

        if note_key:
            current["note_keys"].append(note_key)

        if hist_val:
            hist_limpo = clean_history_text(hist_val)
            if hist_limpo:
                current["hist_lines"].append(hist_limpo)

        for c in extra_cols:
            extra = normalize_text(row.get(c))
            if extra and not re.fullmatch(r"[\d.,]+", extra) and extra.upper() not in {"NAN", "NONE"}:
                # Evita repetir colunas que são claramente dados financeiros/datas.
                if extra.upper() not in hist_val.upper():
                    current["hist_lines"].append(f"Decisão/status: {extra}")

    flush()
    out = pd.DataFrame(blocks)
    if out.empty:
        raise ValueError("Não encontrei histórico aproveitável na planilha enviada.")
    return out


def import_legacy_history(df_legacy: pd.DataFrame, data_ref: date, responsavel: str = "Importação legado", atualizar_observacao: bool = True) -> dict:
    """Importa histórico legado casando por número da nota/título."""
    backup_db("antes_historico_legado")
    conn = get_conn()
    try:
        cur = conn.cursor()
        now = datetime.now().isoformat(timespec="seconds")
        data_ref_str = data_ref.isoformat()
        tit = pd.read_sql_query("SELECT titulo_id, cliente_codigo, loja, nome_cliente, numero_titulo, observacao_atual FROM titulos", conn)
        if tit.empty:
            raise ValueError("Ainda não existe base de títulos no CRM. Faça primeiro o upload diário do Protheus.")
        tit["nota_key"] = tit["numero_titulo"].apply(normalize_note_key)
        tit["cliente_codigo_norm"] = tit["cliente_codigo"].apply(normalize_text)

        inseridos = 0
        titulos_afetados = set()
        sem_match = []

        for _, rec in df_legacy.iterrows():
            notas = [n.strip() for n in str(rec.get("notas", "")).split(",") if n.strip()]
            cliente_codigo = normalize_text(rec.get("cliente_codigo"))
            historico = clean_history_text(rec.get("historico_legado"))
            nome_cliente = normalize_text(rec.get("nome_cliente"))
            if not notas or not historico:
                continue

            mask = tit["nota_key"].isin(notas)
            if cliente_codigo:
                mask_cliente = tit["cliente_codigo_norm"].eq(cliente_codigo)
                matched = tit[mask & mask_cliente].copy()
                if matched.empty:
                    matched = tit[mask].copy()
            else:
                matched = tit[mask].copy()

            if matched.empty:
                sem_match.append(f"{nome_cliente or cliente_codigo}: {', '.join(notas)}")
                continue

            for _, t in matched.iterrows():
                tid = str(t["titulo_id"])
                obs = f"Histórico legado importado: {historico}"
                exists = cur.execute(
                    """
                    SELECT 1 FROM historico_acoes
                     WHERE titulo_id = ? AND tipo_acao = ? AND observacao = ?
                     LIMIT 1
                    """,
                    (tid, "Histórico legado", obs),
                ).fetchone()
                if exists:
                    continue
                cur.execute(
                    """
                    INSERT INTO historico_acoes (titulo_id, data_acao, tipo_acao, responsavel, observacao, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (tid, data_ref_str, "Histórico legado", responsavel, obs, now),
                )
                if atualizar_observacao and not normalize_text(t.get("observacao_atual")):
                    cur.execute(
                        "UPDATE titulos SET observacao_atual = ?, updated_at = ? WHERE titulo_id = ?",
                        (historico[:1500], now, tid),
                    )
                inseridos += 1
                titulos_afetados.add(tid)

        conn.commit()
        return {
            "historicos_inseridos": inseridos,
            "titulos_afetados": len(titulos_afetados),
            "blocos_lidos": len(df_legacy),
            "sem_match": sem_match[:50],
            "sem_match_total": len(sem_match),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# Consultas e regras
# -----------------------------------------------------------------------------
def load_regua() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM regua_cobranca ORDER BY dia", conn)
    conn.close()
    return df


def get_action_for_day(ciclo: int, status: str, promessa: Optional[str], ref: date) -> Dict[str, str]:
    if status == STATUS_PAGO:
        return {"acao": "Título pago", "descricao": "Sem ação de cobrança", "responsavel_padrao": "", "prioridade": 99}

    promessa_dt = parse_iso_date(promessa)
    if promessa_dt and promessa_dt >= ref:
        return {
            "acao": "Aguardar promessa",
            "descricao": f"Cliente prometeu pagamento para {promessa_dt.strftime('%d/%m/%Y')}",
            "responsavel_padrao": "Financeiro",
            "prioridade": 3,
        }

    regua = load_regua()
    if regua.empty:
        return {"acao": "Cobrar", "descricao": "Sem régua cadastrada", "responsavel_padrao": "Financeiro", "prioridade": 5}

    applicable = regua[regua["dia"] <= int(ciclo)]
    if applicable.empty:
        row = regua.iloc[0]
    else:
        row = applicable.iloc[-1]

    return {
        "acao": str(row["acao"]),
        "descricao": str(row["descricao"]),
        "responsavel_padrao": str(row["responsavel_padrao"]),
        "prioridade": int(row["prioridade"]),
    }


def process_upload(df: pd.DataFrame, data_ref: date, arquivo_nome: str) -> Tuple[int, int, int, float, int, int, str]:
    backup_db("antes_upload")
    conn = get_conn()
    try:
        cur = conn.cursor()
        now = datetime.now().isoformat(timespec="seconds")
        data_ref_str = data_ref.isoformat()
        current_ids = set(df["titulo_id"].astype(str).tolist())
        cadastro_map = get_cliente_cadastro_map(conn)
        try:
            faturamento_maps, faturamento_status = load_faturamento_maps_from_github()
        except Exception as exc:
            faturamento_maps, faturamento_status = ({}, {}, {}), f"Erro ao ler base de faturamento: {exc}"

        existing = pd.read_sql_query("SELECT titulo_id, status, primeira_aparicao, ultima_aparicao FROM titulos", conn)
        existing_ids = set(existing["titulo_id"].astype(str).tolist()) if not existing.empty else set()
        active_existing_ids = set(existing.loc[existing["status"] != STATUS_PAGO, "titulo_id"].astype(str).tolist()) if not existing.empty else set()

        novos = 0
        atualizados = 0
        base_bi_cruzados = 0
        base_bi_nao_localizados = 0

        for _, row in df.iterrows():
            tid = str(row["titulo_id"])
            cliente_codigo = normalize_text(row.get("Cliente"))
            loja = normalize_text(row.get("Loja"))
            nome_cliente = normalize_text(row.get("Nome Cliente"))
            cid = make_cliente_id(cliente_codigo, loja, nome_cliente)
            cad = cadastro_map.get(cid, {})
            auto_info = get_faturamento_info_for(row, faturamento_maps)
            if auto_info and (auto_info.get("vendedor") or auto_info.get("gerente")):
                base_bi_cruzados += 1
            else:
                base_bi_nao_localizados += 1
            vendedor_cad = str(cad.get("vendedor", "") or auto_info.get("vendedor", "") or "")
            gerente_cad = str(cad.get("gerente", "") or auto_info.get("gerente", "") or "")
            obs_cad = str(cad.get("observacao", "") or "")
            razao_cad = str(cad.get("razao_social", "") or auto_info.get("razao_social", "") or "")
            cnpj_cad = str(cad.get("cnpj", "") or auto_info.get("cnpj", "") or "")
            contato_cad = str(cad.get("contato", "") or auto_info.get("contato", "") or "")
            upsert_cliente_cadastro(conn, cliente_codigo, loja, nome_cliente, vendedor=vendedor_cad, gerente=gerente_cad, razao_social=razao_cad, cnpj=cnpj_cad, contato=contato_cad)

            if tid in existing_ids:
                cur.execute("SELECT primeira_aparicao, vendedor, gerente, observacao_atual, razao_social, cnpj, contato FROM titulos WHERE titulo_id = ?", (tid,))
                old_row = cur.fetchone()
                first = old_row["primeira_aparicao"]
                ciclo = calcular_ciclo(first, data_ref)
                vendedor_final = vendedor_cad or str(old_row["vendedor"] or "")
                gerente_final = gerente_cad or str(old_row["gerente"] or "")
                obs_final = obs_cad or str(old_row["observacao_atual"] or "")
                razao_final = razao_cad or str(old_row["razao_social"] or "")
                cnpj_final = cnpj_cad or str(old_row["cnpj"] or "")
                contato_final = contato_cad or str(old_row["contato"] or "")
                cur.execute(
                    """
                    UPDATE titulos
                       SET filial = ?, prefixo = ?, numero_titulo = ?, parcela = ?, tipo = ?,
                           cliente_codigo = ?, loja = ?, nome_cliente = ?, dt_emissao = ?, vencimento = ?,
                           valor_titulo = ?, saldo_atual = ?, multa = ?, juros = ?, vendedor = ?, gerente = ?, observacao_atual = ?, razao_social = ?, cnpj = ?, contato = ?,
                           status = CASE WHEN status = 'Pago' THEN 'Em cobrança' ELSE status END,
                           ultima_aparicao = ?, data_baixa = NULL, ciclo_cobranca = ?, updated_at = ?
                     WHERE titulo_id = ?
                    """,
                    (
                        normalize_text(row.get("Filial")), normalize_text(row.get("Prefixo")), normalize_text(row.get("No. Titulo")),
                        normalize_text(row.get("Parcela")), normalize_text(row.get("Tipo")), cliente_codigo, loja,
                        nome_cliente, row.get("dt_emissao_str"), row.get("vencimento_str"),
                        float(row.get("Vlr.Titulo", 0)), float(row.get("Saldo a receber", 0)), float(row.get("Multa", 0)), float(row.get("Juros", 0)),
                        vendedor_final, gerente_final, obs_final, razao_final, cnpj_final, contato_final,
                        data_ref_str, ciclo, now, tid,
                    ),
                )
                atualizados += 1
            else:
                cur.execute(
                    """
                    INSERT INTO titulos (
                        titulo_id, filial, prefixo, numero_titulo, parcela, tipo, cliente_codigo, loja,
                        nome_cliente, dt_emissao, vencimento, valor_titulo, saldo_original, saldo_atual,
                        multa, juros, vendedor, gerente, observacao_atual, razao_social, cnpj, contato, status, primeira_aparicao, ultima_aparicao, ciclo_cobranca, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tid, normalize_text(row.get("Filial")), normalize_text(row.get("Prefixo")), normalize_text(row.get("No. Titulo")),
                        normalize_text(row.get("Parcela")), normalize_text(row.get("Tipo")), cliente_codigo, loja,
                        nome_cliente, row.get("dt_emissao_str"), row.get("vencimento_str"),
                        float(row.get("Vlr.Titulo", 0)), float(row.get("Saldo a receber", 0)), float(row.get("Saldo a receber", 0)),
                        float(row.get("Multa", 0)), float(row.get("Juros", 0)), vendedor_cad, gerente_cad, obs_cad, razao_cad, cnpj_cad, contato_cad, STATUS_ATIVO, data_ref_str, data_ref_str, 1, now, now,
                    ),
                )
                cur.execute(
                    "INSERT INTO historico_acoes (titulo_id, data_acao, tipo_acao, responsavel, observacao, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (tid, data_ref_str, "Entrada na régua", "Sistema", "Título incluído no CRM financeiro.", now),
                )
                novos += 1

        paid_ids = sorted(active_existing_ids - current_ids)
        for tid in paid_ids:
            cur.execute(
                "UPDATE titulos SET status = ?, data_baixa = ?, updated_at = ? WHERE titulo_id = ?",
                (STATUS_PAGO, data_ref_str, now, tid),
            )
            cur.execute(
                "INSERT INTO historico_acoes (titulo_id, data_acao, tipo_acao, responsavel, observacao, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (tid, data_ref_str, "Baixa automática", "Sistema", "Título saiu do relatório diário.", now),
            )

        valor_aberto = float(df["Saldo a receber"].sum())
        cur.execute(
            """
            INSERT INTO uploads (data_referencia, arquivo, qtd_linhas, novos, atualizados, pagos, valor_aberto, base_bi_cruzados, base_bi_nao_localizados, base_bi_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (data_ref_str, arquivo_nome, len(df), novos, atualizados, len(paid_ids), valor_aberto, base_bi_cruzados, base_bi_nao_localizados, faturamento_status, now),
        )
        conn.commit()
        return novos, atualizados, len(paid_ids), valor_aberto, base_bi_cruzados, base_bi_nao_localizados, faturamento_status
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def load_titulos(status_filter: Optional[str] = None) -> pd.DataFrame:
    conn = get_conn()
    query = "SELECT * FROM titulos"
    params = []
    if status_filter:
        query += " WHERE status = ?"
        params.append(status_filter)
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def load_historico(titulo_id: Optional[str] = None) -> pd.DataFrame:
    conn = get_conn()
    if titulo_id:
        df = pd.read_sql_query("SELECT * FROM historico_acoes WHERE titulo_id = ? ORDER BY data_acao DESC, id DESC", conn, params=[titulo_id])
    else:
        df = pd.read_sql_query("SELECT * FROM historico_acoes ORDER BY data_acao DESC, id DESC LIMIT 500", conn)
    conn.close()
    return df



def update_cliente_meta(cliente_codigo: str, loja: str, nome_cliente: str, tipo_cliente: str, cobrador: str) -> None:
    """Salva tipo de cliente e responsável da cobrança no cadastro do cliente."""
    backup_db("antes_cliente_meta")
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    cid = make_cliente_id(cliente_codigo, loja, nome_cliente)
    upsert_cliente_cadastro(conn, cliente_codigo, loja, nome_cliente, tipo_cliente=tipo_cliente, cobrador=cobrador)
    conn.execute(
        "UPDATE clientes SET tipo_cliente = ?, cobrador = ?, updated_at = ? WHERE cliente_id = ?",
        (tipo_cliente or "Não especial", cobrador.strip(), now, cid),
    )
    conn.commit()
    conn.close()


def add_agenda_retorno(cliente_codigo: str, loja: str, nome_cliente: str, data_retorno: date, motivo: str, responsavel: str) -> str:
    """Inclui ou atualiza o único lembrete pendente do cliente.

    Evita duplicidade quando o usuário clica em salvar mais de uma vez ou troca a data do retorno.
    Regra prática: um cliente deve ter apenas uma agenda pendente ativa; se já existir, atualiza a data.
    """
    backup_db("antes_agenda")
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    cid = make_cliente_id(cliente_codigo, loja, nome_cliente)
    data_iso = data_retorno.isoformat()
    motivo_limpo = (motivo or "Retorno programado").strip()
    responsavel_limpo = (responsavel or "Financeiro").strip()

    existente = conn.execute(
        """
        SELECT id
        FROM agenda_retorno
        WHERE cliente_id = ?
          AND status = 'Pendente'
        ORDER BY id DESC
        LIMIT 1
        """,
        (cid,),
    ).fetchone()

    if existente:
        conn.execute(
            """
            UPDATE agenda_retorno
               SET data_retorno = ?, motivo = ?, responsavel = ?, nome_cliente = ?, cliente_codigo = ?, loja = ?, updated_at = ?
             WHERE id = ?
            """,
            (data_iso, motivo_limpo, responsavel_limpo, nome_cliente, cliente_codigo, loja, now, int(existente[0])),
        )
        resultado = "atualizado"
    else:
        conn.execute(
            """
            INSERT INTO agenda_retorno (cliente_id, cliente_codigo, loja, nome_cliente, data_retorno, motivo, responsavel, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Pendente', ?, ?)
            """,
            (cid, cliente_codigo, loja, nome_cliente, data_iso, motivo_limpo, responsavel_limpo, now, now),
        )
        resultado = "incluído"

    conn.commit()
    conn.close()
    return resultado


def load_agenda(status: str = "Pendente") -> pd.DataFrame:
    conn = get_conn()
    query = "SELECT * FROM agenda_retorno"
    params = []
    if status != "Todos":
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY data_retorno ASC, nome_cliente ASC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def concluir_agenda(agenda_id: int) -> None:
    backup_db("antes_concluir_agenda")
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "UPDATE agenda_retorno SET status = 'Concluído', data_conclusao = ?, updated_at = ? WHERE id = ?",
        (date.today().isoformat(), now, int(agenda_id)),
    )
    conn.commit()
    conn.close()

def update_titulo_fields(titulo_id: str, vendedor: str, gerente: str, observacao: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE titulos SET vendedor = ?, gerente = ?, observacao_atual = ?, updated_at = ? WHERE titulo_id = ?",
        (vendedor.strip(), gerente.strip(), observacao.strip(), datetime.now().isoformat(timespec="seconds"), titulo_id),
    )
    conn.commit()
    conn.close()




def _cliente_where_clause(cliente_codigo: str, loja: str, nome_cliente: str) -> Tuple[str, List[str]]:
    """Filtro seguro para localizar todos os títulos do mesmo cliente."""
    return "cliente_codigo = ? AND loja = ? AND nome_cliente = ?", [cliente_codigo, loja, nome_cliente]


def make_cliente_id(cliente_codigo: str, loja: str, nome_cliente: str) -> str:
    return f"{str(cliente_codigo).strip()}|{str(loja).strip()}|{str(nome_cliente).strip()}".upper()


def load_clientes() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM clientes ORDER BY nome_cliente", conn)
    conn.close()
    return df


def upsert_cliente_cadastro(conn: sqlite3.Connection, cliente_codigo: str, loja: str, nome_cliente: str, vendedor: str = "", gerente: str = "", observacao: str = "", tipo_cliente: str = "", cobrador: str = "", razao_social: str = "", cnpj: str = "", contato: str = "") -> None:
    now = datetime.now().isoformat(timespec="seconds")
    cid = make_cliente_id(cliente_codigo, loja, nome_cliente)
    conn.execute(
        """
        INSERT INTO clientes (cliente_id, cliente_codigo, loja, nome_cliente, vendedor, gerente, tipo_cliente, cobrador, observacao, razao_social, cnpj, contato, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cliente_id) DO UPDATE SET
            nome_cliente = excluded.nome_cliente,
            vendedor = CASE WHEN excluded.vendedor != '' THEN excluded.vendedor ELSE clientes.vendedor END,
            gerente = CASE WHEN excluded.gerente != '' THEN excluded.gerente ELSE clientes.gerente END,
            tipo_cliente = CASE WHEN excluded.tipo_cliente != '' THEN excluded.tipo_cliente ELSE COALESCE(NULLIF(clientes.tipo_cliente, ''), 'Não especial') END,
            cobrador = CASE WHEN excluded.cobrador != '' THEN excluded.cobrador ELSE COALESCE(clientes.cobrador, '') END,
            observacao = CASE WHEN excluded.observacao != '' THEN excluded.observacao ELSE clientes.observacao END,
            razao_social = CASE WHEN excluded.razao_social != '' THEN excluded.razao_social ELSE COALESCE(clientes.razao_social, '') END,
            cnpj = CASE WHEN excluded.cnpj != '' THEN excluded.cnpj ELSE COALESCE(clientes.cnpj, '') END,
            contato = CASE WHEN excluded.contato != '' THEN excluded.contato ELSE COALESCE(clientes.contato, '') END,
            updated_at = excluded.updated_at
        """,
        (cid, cliente_codigo, loja, nome_cliente, vendedor.strip(), gerente.strip(), (tipo_cliente or "").strip(), cobrador.strip(), observacao.strip(), razao_social.strip(), cnpj.strip(), contato.strip(), now, now),
    )


def get_cliente_cadastro_map(conn: sqlite3.Connection) -> Dict[str, Dict[str, str]]:
    df = pd.read_sql_query("SELECT cliente_id, vendedor, gerente, observacao, tipo_cliente, cobrador, razao_social, cnpj, contato FROM clientes", conn)
    if df.empty:
        return {}
    return df.set_index("cliente_id").to_dict(orient="index")


def migrate_clientes_from_titulos() -> int:
    conn = get_conn()
    tit = pd.read_sql_query(
        """
        SELECT cliente_codigo, loja, nome_cliente, vendedor, gerente, observacao_atual
          FROM titulos
         WHERE cliente_codigo IS NOT NULL AND nome_cliente IS NOT NULL
         ORDER BY updated_at DESC
        """,
        conn,
    )
    total = 0
    if not tit.empty:
        for _, r in tit.iterrows():
            cid = make_cliente_id(r.get("cliente_codigo", ""), r.get("loja", ""), r.get("nome_cliente", ""))
            if not cid.strip("|"):
                continue
            upsert_cliente_cadastro(
                conn,
                str(r.get("cliente_codigo", "")),
                str(r.get("loja", "")),
                str(r.get("nome_cliente", "")),
                str(r.get("vendedor", "") or ""),
                str(r.get("gerente", "") or ""),
                str(r.get("observacao_atual", "") or ""),
            )
            total += 1
    conn.commit()
    conn.close()
    return total


def safe_to_excel_bytes(sheets: Dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, df in sheets.items():
            clean_name = str(name)[:31] or "Relatorio"
            df.to_excel(writer, index=False, sheet_name=clean_name)
    return output.getvalue()


def update_cliente_fields(cliente_codigo: str, loja: str, nome_cliente: str, vendedor: str, gerente: str, observacao: str) -> int:
    backup_db("antes_responsaveis")
    conn = get_conn()
    try:
        where, params = _cliente_where_clause(cliente_codigo, loja, nome_cliente)
        now = datetime.now().isoformat(timespec="seconds")
        upsert_cliente_cadastro(conn, cliente_codigo, loja, nome_cliente, vendedor=vendedor, gerente=gerente, observacao=observacao)
        cur = conn.execute(
            f"""
            UPDATE titulos
               SET vendedor = ?, gerente = ?, observacao_atual = ?, updated_at = ?
             WHERE {where} AND status != ?
            """,
            [vendedor.strip(), gerente.strip(), observacao.strip(), now] + params + [STATUS_PAGO],
        )
        conn.commit()
        return cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_action(titulo_id: str, data_acao: date, tipo: str, responsavel: str, observacao: str, promessa: Optional[date]) -> None:
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    promessa_str = promessa.isoformat() if promessa else None
    conn.execute(
        """
        INSERT INTO historico_acoes (titulo_id, data_acao, tipo_acao, responsavel, observacao, promessa_pagamento, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (titulo_id, data_acao.isoformat(), tipo, responsavel.strip(), observacao.strip(), promessa_str, now),
    )
    if promessa_str:
        conn.execute(
            "UPDATE titulos SET promessa_pagamento = ?, status = ?, updated_at = ? WHERE titulo_id = ?",
            (promessa_str, STATUS_PROMESSA, now, titulo_id),
        )
    elif tipo == "Pagamento identificado manualmente":
        conn.execute(
            "UPDATE titulos SET status = ?, data_baixa = ?, updated_at = ? WHERE titulo_id = ?",
            (STATUS_PAGO, data_acao.isoformat(), now, titulo_id),
        )
    conn.commit()
    conn.close()





def save_cliente_all(
    cliente_codigo: str,
    loja: str,
    nome_cliente: str,
    tipo_cliente: str,
    cobrador: str,
    razao_social: str,
    cnpj: str,
    contato: str,
    vendedor: str,
    gerente: str,
    observacao_cliente: str,
    tipo_acao: str,
    responsavel_acao: str,
    data_acao: date,
    observacao_acao: str,
    promessa: Optional[date],
    agendar_retorno: bool,
    data_retorno: Optional[date],
    motivo_retorno: str,
) -> Dict[str, object]:
    """Salva todos os campos do cliente em uma única transação.

    Evita que um campo salvo por último sobrescreva outro campo com valor antigo.
    Também garante que o histórico, a promessa e a agenda sejam gravados juntos ou nada seja salvo.
    """
    backup_db("antes_salvar_cliente_completo")
    conn = get_conn()
    try:
        now = datetime.now().isoformat(timespec="seconds")
        cid = make_cliente_id(cliente_codigo, loja, nome_cliente)
        tipo_cliente = (tipo_cliente or "Não especial").strip() or "Não especial"
        cobrador = (cobrador or "").strip()
        razao_social = (razao_social or "").strip()
        cnpj = (cnpj or "").strip()
        contato = (contato or "").strip()
        vendedor = (vendedor or "").strip()
        gerente = (gerente or "").strip()
        observacao_cliente = (observacao_cliente or "").strip()
        responsavel_acao = (responsavel_acao or cobrador or "Financeiro").strip()
        observacao_acao = clean_history_text(observacao_acao or "")

        # Cadastro do cliente: grava exatamente o que está na tela.
        conn.execute(
            """
            INSERT INTO clientes (cliente_id, cliente_codigo, loja, nome_cliente, vendedor, gerente, tipo_cliente, cobrador, observacao, razao_social, cnpj, contato, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id) DO UPDATE SET
                cliente_codigo = excluded.cliente_codigo,
                loja = excluded.loja,
                nome_cliente = excluded.nome_cliente,
                vendedor = excluded.vendedor,
                gerente = excluded.gerente,
                tipo_cliente = excluded.tipo_cliente,
                cobrador = excluded.cobrador,
                observacao = excluded.observacao,
                razao_social = excluded.razao_social,
                cnpj = excluded.cnpj,
                contato = excluded.contato,
                updated_at = excluded.updated_at
            """,
            (cid, cliente_codigo, loja, nome_cliente, vendedor, gerente, tipo_cliente, cobrador, observacao_cliente, razao_social, cnpj, contato, now, now),
        )

        where, params = _cliente_where_clause(cliente_codigo, loja, nome_cliente)
        cur = conn.execute(
            f"""
            UPDATE titulos
               SET vendedor = ?, gerente = ?, observacao_atual = ?, updated_at = ?
             WHERE {where} AND status != ?
            """,
            [vendedor, gerente, observacao_cliente, razao_social, cnpj, contato, now] + params + [STATUS_PAGO],
        )
        titulos_atualizados = int(cur.rowcount or 0)

        total_acao = 0
        promessa_str = promessa.isoformat() if promessa else None
        if tipo_acao and tipo_acao != "Não registrar ação agora":
            titulos = pd.read_sql_query(
                f"SELECT titulo_id FROM titulos WHERE {where} AND status != ?",
                conn,
                params=params + [STATUS_PAGO],
            )
            ids = titulos["titulo_id"].astype(str).tolist() if not titulos.empty else []
            if ids:
                rows = [
                    (tid, data_acao.isoformat(), tipo_acao, responsavel_acao, observacao_acao, promessa_str, now)
                    for tid in ids
                ]
                conn.executemany(
                    """
                    INSERT INTO historico_acoes (titulo_id, data_acao, tipo_acao, responsavel, observacao, promessa_pagamento, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                total_acao = len(rows)

                if promessa_str:
                    conn.execute(
                        f"UPDATE titulos SET promessa_pagamento = ?, status = ?, updated_at = ? WHERE {where} AND status != ?",
                        [promessa_str, STATUS_PROMESSA, now] + params + [STATUS_PAGO],
                    )
                elif tipo_acao == "Pagamento identificado manualmente":
                    conn.execute(
                        f"UPDATE titulos SET status = ?, data_baixa = ?, updated_at = ? WHERE {where} AND status != ?",
                        [STATUS_PAGO, data_acao.isoformat(), now] + params + [STATUS_PAGO],
                    )

        agenda_status = "não agendada"
        if agendar_retorno and data_retorno:
            data_iso = data_retorno.isoformat()
            motivo_limpo = clean_history_text(motivo_retorno or observacao_acao or tipo_acao or "Retorno programado")
            existente = conn.execute(
                """
                SELECT id
                  FROM agenda_retorno
                 WHERE cliente_id = ?
                   AND status = 'Pendente'
                 ORDER BY id DESC
                 LIMIT 1
                """,
                (cid,),
            ).fetchone()
            if existente:
                conn.execute(
                    """
                    UPDATE agenda_retorno
                       SET data_retorno = ?, motivo = ?, responsavel = ?, nome_cliente = ?, cliente_codigo = ?, loja = ?, updated_at = ?
                     WHERE id = ?
                    """,
                    (data_iso, motivo_limpo, responsavel_acao, nome_cliente, cliente_codigo, loja, now, int(existente[0])),
                )
                agenda_status = "atualizada"
            else:
                conn.execute(
                    """
                    INSERT INTO agenda_retorno (cliente_id, cliente_codigo, loja, nome_cliente, data_retorno, motivo, responsavel, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'Pendente', ?, ?)
                    """,
                    (cid, cliente_codigo, loja, nome_cliente, data_iso, motivo_limpo, responsavel_acao, now, now),
                )
                agenda_status = "incluída"

        conn.commit()
        return {"titulos_atualizados": titulos_atualizados, "acoes_registradas": total_acao, "agenda": agenda_status}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def add_action_cliente(cliente_codigo: str, loja: str, nome_cliente: str, data_acao: date, tipo: str, responsavel: str, observacao: str, promessa: Optional[date]) -> int:
    backup_db("antes_acao_cliente")
    """Registra uma única ação do CRM em todos os títulos abertos do cliente.

    A cobrança é feita uma vez por cliente, mesmo quando existem vários títulos.
    Para preservar rastreabilidade, a ação é gravada em cada título aberto daquele cliente.
    A gravação é transacional: se qualquer etapa falhar, nada é parcialmente salvo.
    """
    conn = get_conn()
    try:
        now = datetime.now().isoformat(timespec="seconds")
        promessa_str = promessa.isoformat() if promessa else None
        where, params = _cliente_where_clause(cliente_codigo, loja, nome_cliente)
        titulos = pd.read_sql_query(
            f"SELECT titulo_id FROM titulos WHERE {where} AND status != ?",
            conn,
            params=params + [STATUS_PAGO],
        )
        if titulos.empty:
            return 0

        rows = [
            (tid, data_acao.isoformat(), tipo, responsavel.strip(), observacao.strip(), promessa_str, now)
            for tid in titulos["titulo_id"].astype(str).tolist()
        ]
        conn.executemany(
            """
            INSERT INTO historico_acoes (titulo_id, data_acao, tipo_acao, responsavel, observacao, promessa_pagamento, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        if promessa_str:
            conn.execute(
                f"UPDATE titulos SET promessa_pagamento = ?, status = ?, updated_at = ? WHERE {where} AND status != ?",
                [promessa_str, STATUS_PROMESSA, now] + params + [STATUS_PAGO],
            )
        elif tipo == "Pagamento identificado manualmente":
            conn.execute(
                f"UPDATE titulos SET status = ?, data_baixa = ?, updated_at = ? WHERE {where} AND status != ?",
                [STATUS_PAGO, data_acao.isoformat(), now] + params + [STATUS_PAGO],
            )
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_regua(df: pd.DataFrame) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM regua_cobranca")
    rows = []
    for _, r in df.iterrows():
        try:
            dia = int(r.get("dia"))
        except Exception:
            continue
        if dia <= 0:
            continue
        rows.append((
            dia,
            str(r.get("acao", "")).strip(),
            str(r.get("descricao", "")).strip(),
            str(r.get("responsavel_padrao", "Financeiro")).strip(),
            int(r.get("prioridade", 5) or 5),
        ))
    cur.executemany(
        "INSERT OR REPLACE INTO regua_cobranca (dia, acao, descricao, responsavel_padrao, prioridade) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def prepare_fila(ref: date) -> pd.DataFrame:
    df = load_titulos()
    if df.empty:
        return df

    open_df = df[df["status"] != STATUS_PAGO].copy()
    if open_df.empty:
        return open_df

    open_df["dias_atraso"] = open_df["vencimento"].apply(lambda x: calcular_dias_atraso(x, ref))
    open_df["ciclo_cobranca"] = open_df["primeira_aparicao"].apply(lambda x: calcular_ciclo(x, ref))

    actions = open_df.apply(
        lambda r: get_action_for_day(int(r["ciclo_cobranca"]), str(r["status"]), r.get("promessa_pagamento"), ref), axis=1
    )
    open_df["acao_do_dia"] = [a["acao"] for a in actions]
    open_df["descricao_acao"] = [a["descricao"] for a in actions]
    open_df["responsavel_padrao"] = [a["responsavel_padrao"] for a in actions]
    open_df["prioridade"] = [a["prioridade"] for a in actions]
    open_df["valor_prioridade"] = open_df["saldo_atual"].fillna(0) * (open_df["dias_atraso"].fillna(0) + 1)

    return open_df.sort_values(["prioridade", "valor_prioridade"], ascending=[True, False])




def _join_unique(values: pd.Series, limite: int = 3) -> str:
    vals = []
    for v in values.fillna("").astype(str):
        v = v.strip()
        if v and v not in vals:
            vals.append(v)
    if len(vals) > limite:
        return ", ".join(vals[:limite]) + "..."
    return ", ".join(vals)


def prepare_fila_clientes(ref: date) -> pd.DataFrame:
    """Agrupa a fila por cliente para que 15 títulos gerem uma única ação."""
    fila = prepare_fila(ref)
    if fila.empty:
        return fila

    conn = get_conn()
    cad_map = get_cliente_cadastro_map(conn)
    conn.close()

    rows = []
    group_cols = ["cliente_codigo", "loja", "nome_cliente"]
    for keys, grp in fila.groupby(group_cols, dropna=False):
        cliente_codigo, loja, nome_cliente = keys
        max_ciclo = int(grp["ciclo_cobranca"].max())
        max_dias = int(grp["dias_atraso"].max())
        min_venc = grp["vencimento"].min()

        promessas_validas = []
        for p in grp.get("promessa_pagamento", pd.Series(dtype=str)).dropna().astype(str):
            dtp = parse_iso_date(p)
            if dtp and dtp >= ref:
                promessas_validas.append(dtp)
        promessa_cliente = min(promessas_validas).isoformat() if promessas_validas else None

        cid = make_cliente_id(cliente_codigo, loja, nome_cliente)
        cad = cad_map.get(cid, {})
        tipo_cliente = str(cad.get("tipo_cliente", "") or "Não especial")
        cobrador = str(cad.get("cobrador", "") or "")
        razao_social = str(cad.get("razao_social", "") or "")
        cnpj = str(cad.get("cnpj", "") or "")
        contato = str(cad.get("contato", "") or "")
        acao = get_action_for_day(max_ciclo, str(grp["status"].iloc[0]), promessa_cliente, ref)
        rows.append({
            "cliente_id": f"{cliente_codigo}|{loja}|{nome_cliente}",
            "cliente_codigo": cliente_codigo,
            "loja": loja,
            "nome_cliente": nome_cliente,
            "qtd_titulos": int(grp["titulo_id"].nunique()),
            "saldo_total": float(grp["saldo_atual"].sum()),
            "menor_vencimento": min_venc,
            "maior_dias_atraso": max_dias,
            "dia_regua": max_ciclo,
            "acao_do_dia": acao["acao"],
            "descricao_acao": acao["descricao"],
            "responsavel_padrao": acao["responsavel_padrao"],
            "prioridade": int(acao["prioridade"]),
            "vendedor": _join_unique(grp["vendedor"]),
            "gerente": _join_unique(grp["gerente"]),
            "tipo_cliente": tipo_cliente,
            "cobrador": cobrador,
            "razao_social": razao_social,
            "cnpj": cnpj,
            "contato": contato,
            "valor_prioridade": float(grp["saldo_atual"].sum()) * (max_dias + 1),
        })
    out = pd.DataFrame(rows)
    return out.sort_values(["prioridade", "valor_prioridade"], ascending=[True, False])




def apply_fila_filters(fila: pd.DataFrame, prefix: str = "fila") -> pd.DataFrame:
    """Aplica filtros salvos em session_state. Usado pela fila e pela tela do cliente."""
    if fila.empty:
        return fila
    filtered = fila.copy()
    cliente_search = str(st.session_state.get(f"{prefix}_cliente", "") or "").strip()
    acao_filter = st.session_state.get(f"{prefix}_acao", "Todas")
    resp_filter = st.session_state.get(f"{prefix}_resp", "Todos")
    gerente_filter = st.session_state.get(f"{prefix}_gerente", "Todos")
    vendedor_filter = st.session_state.get(f"{prefix}_vendedor", "Todos")
    tipo_cliente_filter = st.session_state.get(f"{prefix}_tipo_cliente", "Todos")
    cobrador_filter = st.session_state.get(f"{prefix}_cobrador", "Todos")

    if cliente_search:
        filtered = filtered[filtered["nome_cliente"].str.contains(cliente_search, case=False, na=False)]
    if acao_filter and acao_filter != "Todas":
        filtered = filtered[filtered["acao_do_dia"] == acao_filter]
    if resp_filter == "Sem vendedor ou gerente":
        filtered = filtered[(filtered["vendedor"].fillna("") == "") | (filtered["gerente"].fillna("") == "")]
    elif resp_filter == "Sem vendedor":
        filtered = filtered[filtered["vendedor"].fillna("") == ""]
    elif resp_filter == "Sem gerente":
        filtered = filtered[filtered["gerente"].fillna("") == ""]
    if gerente_filter and gerente_filter != "Todos":
        filtered = filtered[filtered["gerente"].replace("", "Sem gerente") == gerente_filter]
    if vendedor_filter and vendedor_filter != "Todos":
        filtered = filtered[filtered["vendedor"].replace("", "Sem vendedor") == vendedor_filter]
    if tipo_cliente_filter and tipo_cliente_filter != "Todos":
        filtered = filtered[filtered["tipo_cliente"].fillna("Não especial") == tipo_cliente_filter]
    if cobrador_filter and cobrador_filter != "Todos":
        filtered = filtered[filtered["cobrador"].replace("", "Sem cobrador") == cobrador_filter]
    return filtered


def set_fila_filter(page_name: str = "Fila por cliente", **filters) -> None:
    """Define filtros e leva o usuário para a tela de fila/cliente."""
    for k, v in filters.items():
        st.session_state[k] = v
    st.session_state["_pending_nav_page"] = page_name
    st.session_state["cliente_index"] = 0
    st.rerun()


def advance_cliente_index(total_options: int) -> None:
    if total_options <= 0:
        st.session_state["cliente_index"] = 0
    else:
        atual = int(st.session_state.get("cliente_index", 0) or 0)
        st.session_state["cliente_index"] = min(atual + 1, total_options - 1)

def load_titulos_cliente(cliente_codigo: str, loja: str, nome_cliente: str, somente_abertos: bool = True) -> pd.DataFrame:
    conn = get_conn()
    where, params = _cliente_where_clause(cliente_codigo, loja, nome_cliente)
    query = f"SELECT * FROM titulos WHERE {where}"
    if somente_abertos:
        query += " AND status != ?"
        params = params + [STATUS_PAGO]
    df = pd.read_sql_query(query + " ORDER BY vencimento, numero_titulo, parcela", conn, params=params)
    conn.close()
    return df


def metric_card(label: str, value: str, help_text: str = "", long_text: bool = False) -> None:
    value_class = "metric-value long-text" if long_text else "metric-value"
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{html.escape(str(label))}</div>
            <div class="{value_class}">{html.escape(str(value))}</div>
            <div class="metric-help">{html.escape(str(help_text))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
init_db()

st.markdown(
    f"""
    <div class="first-header compact-header">
        <h1>{APP_TITLE}</h1>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Navegação")
    NAV_OPTIONS = ["Dashboard", "Upload diário", "Fila por cliente", "Cliente", "Agenda", "Carteira", "Relatórios", "Histórico", "Régua", "Base de títulos", "Segurança"]
    if "_pending_nav_page" in st.session_state:
        pending_page = st.session_state.pop("_pending_nav_page")
        if pending_page in NAV_OPTIONS:
            st.session_state["nav_page"] = pending_page
    if "nav_page" not in st.session_state or st.session_state["nav_page"] not in NAV_OPTIONS:
        st.session_state["nav_page"] = "Dashboard"
    page = st.radio(
        "Selecione",
        NAV_OPTIONS,
        key="nav_page",
        label_visibility="collapsed",
    )
    data_ref = st.date_input("Data de referência", value=date.today(), format="DD/MM/YYYY")
    st.markdown("<div class='sidebar-spacer'></div>", unsafe_allow_html=True)


if page == "Upload diário":
    st.markdown("### Upload diário do relatório Protheus")
    

    df_upload = None
    fonte_arquivo = None
    with st.expander("Base fixa de faturamento para localizar vendedor/gerente", expanded=False):
        url_atual = get_config("base_faturamento_github", "")
        url_nova = st.text_input("URL raw da base de faturamento no GitHub", value=url_atual, placeholder="Cole aqui o link raw do XLSX/CSV")
        cgit1, cgit2 = st.columns(2)
        if cgit1.button("Salvar base fixa", use_container_width=True):
            set_config("base_faturamento_github", url_nova)
            st.success("Base de faturamento salva. Ela será usada nos próximos uploads para sugerir vendedor, gerente e dados cadastrais.")
        if cgit2.button("Testar leitura", use_container_width=True, disabled=not bool(url_nova.strip())):
            try:
                set_config("base_faturamento_github", url_nova)
                _, status_base = load_faturamento_maps_from_github()
                st.success(f"Base lida com sucesso: {status_base}.")
            except Exception as exc:
                st.error(f"Não consegui ler a base: {exc}")

    uploaded = st.file_uploader("Relatório: Títulos a receber vencidos", type=["xlsx", "xls"])
    if uploaded:
        try:
            df_upload = read_excel_upload(uploaded)
            fonte_arquivo = uploaded.name
            st.session_state["df_upload_atual"] = df_upload
            st.session_state["fonte_upload_atual"] = fonte_arquivo
        except Exception as exc:
            st.error(f"Não consegui processar o arquivo: {exc}")

    if "df_upload_atual" in st.session_state:
        df_upload = st.session_state["df_upload_atual"]
        fonte_arquivo = st.session_state.get("fonte_upload_atual", "Arquivo carregado")
        try:
            st.success(f"Arquivo/base lido com sucesso: {len(df_upload)} títulos encontrados. Fonte: {fonte_arquivo}")

            c1, c2, c3 = st.columns(3)
            c1.metric("Valor em aberto no arquivo", br_money(df_upload["Saldo a receber"].sum()))
            c2.metric("Clientes", df_upload["Cliente"].nunique())
            c3.metric("Títulos", len(df_upload))

            with st.expander("Prévia do arquivo importado", expanded=False):
                preview_cols = ["Filial", "Prefixo", "No. Titulo", "Parcela", "Cliente", "Nome Cliente", "Vencto real", "Saldo a receber"]
                st.dataframe(df_upload[preview_cols], use_container_width=True, hide_index=True)

            st.markdown(backup_status_html(), unsafe_allow_html=True)
            confirmar_update = st.checkbox(
                "Conferi a prévia e autorizo atualizar o CRM com este relatório",
                value=False,
                help="Antes de salvar o novo upload, o sistema cria backup automático do banco atual."
            )
            if st.button("Atualizar CRM com este relatório", type="primary", use_container_width=True, disabled=not confirmar_update):
                novos, atualizados, pagos, valor_aberto, base_bi_cruzados, base_bi_nao_localizados, faturamento_status = process_upload(df_upload, data_ref, str(fonte_arquivo))
                st.success("CRM atualizado com sucesso.")
                a, b, c, d = st.columns(4)
                with a: metric_card("Novos", str(novos), "Entraram na régua")
                with b: metric_card("Mantidos", str(atualizados), "Continuam em aberto")
                with c: metric_card("Pagos", str(pagos), "Saíram do relatório")
                with d: metric_card("Valor aberto", br_money(valor_aberto), "Saldo do arquivo")
                e, f, g = st.columns(3)
                with e: metric_card("BASE BI", str(base_bi_cruzados), "Títulos com vendedor/gerente localizados")
                with f: metric_card("Sem cruzamento", str(base_bi_nao_localizados), "Para revisar manualmente")
                with g: metric_card("Fonte comercial", faturamento_status or "Não configurada", "Cruzamento por número da nota")
                pacote = export_backup_zip()
                st.download_button(
                    "Baixar backup do CRM agora",
                    pacote,
                    file_name=f"crm_financeiro_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                    mime="application/zip",
                    use_container_width=True,
                )
                st.balloons()
        except Exception as exc:
            st.error(f"Não consegui exibir a prévia/processamento: {exc}")

elif page == "Dashboard":
    fila_titulos = prepare_fila(data_ref)
    fila = prepare_fila_clientes(data_ref)
    all_titles = load_titulos()
    open_titles = all_titles[all_titles["status"] != STATUS_PAGO].copy() if not all_titles.empty else pd.DataFrame()
    paid_titles = all_titles[all_titles["status"] == STATUS_PAGO].copy() if not all_titles.empty else pd.DataFrame()

    st.markdown('<div class="section-title">Visão executiva</div>', unsafe_allow_html=True)
    if all_titles.empty:
        st.warning("Ainda não existe histórico. Faça o primeiro upload diário para iniciar o CRM.")
    else:
        total_aberto = float(open_titles["saldo_atual"].sum()) if not open_titles.empty else 0
        clientes_abertos = int(open_titles["cliente_codigo"].nunique()) if not open_titles.empty else 0
        acoes_hoje = int(len(fila[~fila["acao_do_dia"].eq("Aguardar promessa")])) if not fila.empty else 0
        promessas = int(len(fila[fila["acao_do_dia"].eq("Aguardar promessa")])) if not fila.empty else 0
        recebidos = float(paid_titles.loc[paid_titles["data_baixa"] == data_ref.isoformat(), "saldo_original"].sum()) if not paid_titles.empty else 0

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: metric_card("Valor em atraso", br_money_short(total_aberto), "Saldo a receber em aberto")
        with c2: metric_card("Clientes", f"{clientes_abertos}", "Clientes com títulos vencidos")
        with c3: metric_card("Títulos", f"{len(open_titles)}", "Títulos em cobrança")
        with c4: metric_card("Recebidos hoje", br_money_short(recebidos), "Baixas automáticas/manual")
        with c5: metric_card("Ações hoje", f"{acoes_hoje}", f"{promessas} promessas aguardando")

        b1, b2, b3, b4 = st.columns(4)
        if b1.button("Ver ações de hoje", use_container_width=True):
            set_fila_filter("Fila por cliente", fila_acao="Todas", fila_resp="Todos")
        if b2.button("Ver promessas", use_container_width=True):
            set_fila_filter("Fila por cliente", fila_acao="Aguardar promessa", fila_resp="Todos")
        if b3.button("Sem vendedor/gerente", use_container_width=True):
            set_fila_filter("Fila por cliente", fila_resp="Sem vendedor ou gerente")
        if b4.button("Trabalhar próximo cliente", use_container_width=True):
            set_fila_filter("Cliente", cliente_acao="Todas", cliente_resp="Todos")

        st.markdown('<div class="section-title">O que fazer hoje</div>', unsafe_allow_html=True)
        if not fila.empty:
            acoes_resumo = fila.groupby("acao_do_dia", as_index=False).agg(Clientes=("cliente_id", "count"), Valor=("saldo_total", "sum")).sort_values("Valor", ascending=False).head(4)
            ac_cols = st.columns(4)
            for i, (_, row) in enumerate(acoes_resumo.iterrows()):
                with ac_cols[i]:
                    metric_card(str(row["acao_do_dia"]), f"{int(row['Clientes'])} cliente(s)", br_money(row["Valor"]), long_text=True)
        st.markdown('<div class="section-title">Ações prioritárias</div>', unsafe_allow_html=True)
        if fila.empty:
            st.success("Nenhuma ação em aberto.")
        else:
            show = fila.head(20).copy()
            show["Valor total"] = show["saldo_total"].apply(br_money)
            show["Venc. mais antigo"] = pd.to_datetime(show["menor_vencimento"], errors="coerce").dt.strftime("%d/%m/%Y")
            cols = ["nome_cliente", "qtd_titulos", "Valor total", "Venc. mais antigo", "maior_dias_atraso", "dia_regua", "acao_do_dia", "vendedor", "gerente"]
            st.dataframe(
                show[cols].rename(columns={
                    "nome_cliente": "Cliente", "qtd_titulos": "Títulos",
                    "maior_dias_atraso": "Maior atraso", "dia_regua": "Dia régua", "acao_do_dia": "Ação única do cliente",
                    "vendedor": "Vendedor", "gerente": "Gerente",
                }),
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("### Inadimplência por ação")
        if not fila.empty:
            grouped = fila.groupby("acao_do_dia", as_index=False).agg(
                Clientes=("cliente_id", "count"), Titulos=("qtd_titulos", "sum"), Valor=("saldo_total", "sum")
            ).sort_values("Valor", ascending=False)
            grouped["Valor"] = grouped["Valor"].apply(br_money)
            st.dataframe(grouped.rename(columns={"acao_do_dia": "Ação"}), use_container_width=True, hide_index=True)


        st.markdown("### Inadimplência por gerente e vendedor")
        if not fila.empty:
            cger, cvend = st.columns(2)
            with cger:
                g = fila.copy(); g["gerente"] = g["gerente"].replace("", "Sem gerente")
                g = g.groupby("gerente", as_index=False).agg(Clientes=("cliente_id", "count"), Valor=("saldo_total", "sum")).sort_values("Valor", ascending=False)
                g["Valor"] = g["Valor"].apply(br_money)
                st.dataframe(g.rename(columns={"gerente":"Gerente"}), use_container_width=True, hide_index=True)
            with cvend:
                v = fila.copy(); v["vendedor"] = v["vendedor"].replace("", "Sem vendedor")
                v = v.groupby("vendedor", as_index=False).agg(Clientes=("cliente_id", "count"), Valor=("saldo_total", "sum")).sort_values("Valor", ascending=False)
                v["Valor"] = v["Valor"].apply(br_money)
                st.dataframe(v.rename(columns={"vendedor":"Vendedor"}), use_container_width=True, hide_index=True)


elif page == "Fila por cliente":
    st.markdown("### Minha fila de cobrança — cliente único")
    
    fila = prepare_fila_clientes(data_ref)
    if fila.empty:
        st.success("Não há clientes em cobrança.")
    else:
        colf1, colf2, colf3 = st.columns([2, 1.2, 1.4])
        colf1.text_input("Filtrar cliente", placeholder="Digite parte do nome do cliente", key="fila_cliente")
        colf2.selectbox("Ação", ["Todas"] + sorted(fila["acao_do_dia"].dropna().unique().tolist()), key="fila_acao")
        colf3.selectbox("Responsável", ["Todos", "Sem vendedor ou gerente", "Sem vendedor", "Sem gerente"], key="fila_resp")

        colf4, colf5 = st.columns(2)
        gerentes = ["Todos"] + sorted(fila["gerente"].replace("", "Sem gerente").dropna().unique().tolist())
        vendedores = ["Todos"] + sorted(fila["vendedor"].replace("", "Sem vendedor").dropna().unique().tolist())
        colf4.selectbox("Gerente", gerentes, key="fila_gerente")
        colf5.selectbox("Vendedor", vendedores, key="fila_vendedor")
        colf6, colf7 = st.columns(2)
        colf6.selectbox("Tipo de cliente", ["Todos", "Especial", "Não especial"], key="fila_tipo_cliente")
        colf7.selectbox("Cobrador", ["Todos"] + sorted(fila["cobrador"].replace("", "Sem cobrador").dropna().unique().tolist()), key="fila_cobrador")

        filtered = apply_fila_filters(fila, prefix="fila")

        at1, at2, at3 = st.columns(3)
        at1.metric("Clientes filtrados", len(filtered))
        at2.metric("Títulos", int(filtered["qtd_titulos"].sum()) if not filtered.empty else 0)
        at3.metric("Valor", br_money(filtered["saldo_total"].sum()) if not filtered.empty else br_money(0))

        if not filtered.empty:
            try:
                export_fila = fila_to_export(filtered)
                arquivo_fila = safe_to_excel_bytes({"Fila filtrada": export_fila})
                st.download_button(
                    "Exportar fila filtrada",
                    arquivo_fila,
                    file_name=f"fila_cobranca_{data_ref.strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            except Exception:
                csv_fila = fila_to_export(filtered).to_csv(index=False, sep=";", encoding="utf-8-sig")
                st.download_button("Exportar fila filtrada CSV", csv_fila, file_name="fila_cobranca.csv", mime="text/csv", use_container_width=True)

        if st.button("Abrir primeiro cliente desta fila", type="primary", use_container_width=True, disabled=filtered.empty):
            st.session_state["cliente_index"] = 0
            st.session_state["cliente_cliente"] = st.session_state.get("fila_cliente", "")
            st.session_state["cliente_acao"] = st.session_state.get("fila_acao", "Todas")
            st.session_state["cliente_resp"] = st.session_state.get("fila_resp", "Todos")
            st.session_state["cliente_gerente"] = st.session_state.get("fila_gerente", "Todos")
            st.session_state["cliente_vendedor"] = st.session_state.get("fila_vendedor", "Todos")
            st.session_state["_pending_nav_page"] = "Cliente"
            st.rerun()

        filtered["Valor total"] = filtered["saldo_total"].apply(br_money)
        filtered["Venc. mais antigo"] = pd.to_datetime(filtered["menor_vencimento"], errors="coerce").dt.strftime("%d/%m/%Y")
        st.dataframe(
            filtered[["cliente_id", "nome_cliente", "qtd_titulos", "Valor total", "Venc. mais antigo", "maior_dias_atraso", "dia_regua", "acao_do_dia", "vendedor", "gerente"]].rename(columns={
                "cliente_id": "ID cliente", "nome_cliente": "Cliente", "qtd_titulos": "Títulos",
                "maior_dias_atraso": "Maior atraso", "dia_regua": "Dia régua", "acao_do_dia": "Ação única do cliente",
                "vendedor": "Vendedor", "gerente": "Gerente",
            }),
            use_container_width=True,
            hide_index=True,
        )
        st.caption("Use a aba 'Cliente único' para registrar uma única ação para todos os títulos abertos do cliente.")

elif page == "Cliente":
    st.markdown("### Cliente")
    fila_clientes = prepare_fila_clientes(data_ref)
    if fila_clientes.empty:
        st.warning("Não há clientes com títulos abertos. Faça o primeiro upload ou verifique a base.")
    else:
        cfilter1, cfilter2, cfilter3 = st.columns([2, 1.2, 1.4])
        cfilter1.text_input("Filtrar cliente", placeholder="Digite parte do nome", key="cliente_cliente")
        cfilter2.selectbox("Ação", ["Todas"] + sorted(fila_clientes["acao_do_dia"].dropna().unique().tolist()), key="cliente_acao")
        cfilter3.selectbox("Responsável", ["Todos", "Sem vendedor ou gerente", "Sem vendedor", "Sem gerente"], key="cliente_resp")
        cfilter4, cfilter5 = st.columns(2)
        cfilter4.selectbox("Gerente", ["Todos"] + sorted(fila_clientes["gerente"].replace("", "Sem gerente").dropna().unique().tolist()), key="cliente_gerente")
        cfilter5.selectbox("Vendedor", ["Todos"] + sorted(fila_clientes["vendedor"].replace("", "Sem vendedor").dropna().unique().tolist()), key="cliente_vendedor")
        cfilter6, cfilter7 = st.columns(2)
        cfilter6.selectbox("Tipo de cliente", ["Todos", "Especial", "Não especial"], key="cliente_tipo_cliente")
        cfilter7.selectbox("Cobrador", ["Todos"] + sorted(fila_clientes["cobrador"].replace("", "Sem cobrador").dropna().unique().tolist()), key="cliente_cobrador")

        options = apply_fila_filters(fila_clientes, prefix="cliente")
        # Segurança extra: garante que cada cliente apareça uma única vez no seletor.
        options = options.drop_duplicates(subset=["cliente_codigo", "loja", "nome_cliente"], keep="first").reset_index(drop=True)
        if options.empty:
            st.warning("Nenhum cliente encontrado com os filtros atuais.")
            st.stop()

        total_options = len(options)
        if "cliente_index" not in st.session_state:
            st.session_state["cliente_index"] = 0
        st.session_state["cliente_index"] = min(int(st.session_state.get("cliente_index", 0) or 0), total_options - 1)

        nav_a, nav_b, nav_c, nav_d = st.columns([1, 1, 1.15, 1.8])
        if nav_a.button("Cliente anterior", use_container_width=True, disabled=st.session_state["cliente_index"] <= 0):
            st.session_state["cliente_index"] = max(st.session_state["cliente_index"] - 1, 0)
            st.rerun()
        if nav_b.button("Próximo cliente", use_container_width=True, disabled=st.session_state["cliente_index"] >= total_options - 1):
            st.session_state["cliente_index"] = min(st.session_state["cliente_index"] + 1, total_options - 1)
            st.rerun()
        pos_desejada = int(nav_c.number_input("Ir para", min_value=1, max_value=total_options, value=int(st.session_state["cliente_index"]) + 1, step=1, label_visibility="visible"))
        if nav_d.button(f"Abrir cliente {pos_desejada}/{total_options}", use_container_width=True):
            st.session_state["cliente_index"] = pos_desejada - 1
            st.rerun()
        st.caption(f"Cliente {st.session_state['cliente_index'] + 1}/{total_options} na fila filtrada")

        options["ordem_fila"] = options.index + 1
        options["label"] = options.apply(
            lambda r: f"{int(r['ordem_fila'])}/{total_options} • {r['nome_cliente']} • {int(r['qtd_titulos'])} título(s) • {br_money(r['saldo_total'])} • {r['acao_do_dia']}", axis=1
        )
        selected_label = st.selectbox(
            "Selecione o cliente para ação única",
            options["label"].tolist(),
            index=int(st.session_state["cliente_index"]),
        )
        selected_pos = int(options.index[options["label"] == selected_label][0])
        st.session_state["cliente_index"] = selected_pos
        selected = options.iloc[selected_pos]

        cliente_codigo = str(selected["cliente_codigo"])
        loja = str(selected["loja"])
        nome_cliente = str(selected["nome_cliente"])
        titulos_cliente = load_titulos_cliente(cliente_codigo, loja, nome_cliente, somente_abertos=True)

        c_cliente, c_saldo = st.columns([2.4, 1.1])
        with c_cliente:
            metric_card("Cliente", nome_cliente, "Ação consolidada por cliente", long_text=True)
        with c_saldo:
            metric_card("Saldo total", br_money(selected["saldo_total"]), "Títulos abertos")

        c_tit, c_atraso, c_acao = st.columns([1, 1, 2])
        with c_tit:
            metric_card("Títulos", int(selected["qtd_titulos"]), "Quantidade em aberto")
        with c_atraso:
            metric_card("Maior atraso", f"{int(selected['maior_dias_atraso'])} dia(s)", "Maior vencimento em aberto")
        with c_acao:
            metric_card("Ação única", selected["acao_do_dia"], "Próxima etapa da régua", long_text=True)

        st.markdown("#### Títulos abertos do cliente")
        tit_show = titulos_cliente.copy()
        if not tit_show.empty:
            tit_show["Valor"] = tit_show["saldo_atual"].apply(br_money)
            tit_show["Vencimento"] = pd.to_datetime(tit_show["vencimento"], errors="coerce").dt.strftime("%d/%m/%Y")
            st.dataframe(
                tit_show[["numero_titulo", "parcela", "tipo", "Valor", "Vencimento", "status", "vendedor", "gerente"]].rename(columns={
                    "numero_titulo": "Título", "parcela": "Parcela", "tipo": "Tipo", "status": "Status", "vendedor": "Vendedor", "gerente": "Gerente",
                }),
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("#### Alterações do cliente")
        tipo_atual = str(selected.get("tipo_cliente", "Não especial") or "Não especial")
        cobrador_atual = str(selected.get("cobrador", "") or "")
        razao_padrao = str(selected.get("razao_social", "") or "")
        cnpj_padrao = str(selected.get("cnpj", "") or "")
        contato_padrao = str(selected.get("contato", "") or "")
        vendedor_padrao = str(selected["vendedor"] or "")
        gerente_padrao = str(selected["gerente"] or "")
        obs_padrao = ""
        if not titulos_cliente.empty:
            obs_padrao = _join_unique(titulos_cliente["observacao_atual"], limite=1)

        # Cada cliente precisa ter chaves próprias nos campos.
        # Sem isso, o Streamlit reaproveita o texto digitado do cliente anterior.
        widget_cliente_key = re.sub(r"[^A-Za-z0-9_]+", "_", f"{cliente_codigo}_{loja}_{nome_cliente}")[:80]

        with st.form(f"form_salvar_tudo_cliente_{widget_cliente_key}"):
            cmeta1, cmeta2 = st.columns(2)
            tipo_cliente = cmeta1.selectbox(
                "Tipo de cliente",
                ["Não especial", "Especial"],
                index=0 if tipo_atual != "Especial" else 1,
                key=f"tipo_cliente_{widget_cliente_key}",
            )
            cobrador = cmeta2.text_input(
                "Responsável pela cobrança",
                value=cobrador_atual,
                placeholder="Ex.: Cobrança Especial / Cobrança Padrão / nome",
                key=f"cobrador_{widget_cliente_key}",
            )

            cad1, cad2 = st.columns(2)
            razao_social = cad1.text_input("Razão social", value=razao_padrao, key=f"razao_social_{widget_cliente_key}")
            cnpj = cad2.text_input("CNPJ", value=cnpj_padrao, key=f"cnpj_{widget_cliente_key}")
            contato = st.text_input("Contato do cliente", value=contato_padrao, placeholder="Nome, telefone ou e-mail do contato financeiro", key=f"contato_{widget_cliente_key}")

            r1, r2 = st.columns(2)
            vendedor = r1.text_input("Vendedor", value=vendedor_padrao, key=f"vendedor_{widget_cliente_key}")
            gerente = r2.text_input("Gerente", value=gerente_padrao, key=f"gerente_{widget_cliente_key}")
            obs_atual = st.text_area("Observação atual do cliente", value=obs_padrao, height=80, key=f"obs_cliente_{widget_cliente_key}")

            st.markdown("##### Ação e agenda")
            a1, a2, a3 = st.columns([1.3, 1, 1])
            opcoes_acao = ["Não registrar ação agora"] + ACTION_OPTIONS
            tipo = a1.selectbox("Ação realizada", opcoes_acao, index=0, key=f"tipo_acao_{widget_cliente_key}")
            responsavel = a2.text_input("Responsável pela ação", value=(cobrador_atual or "Financeiro"), key=f"responsavel_acao_{widget_cliente_key}")
            data_acao = a3.date_input("Data da ação", value=data_ref, format="DD/MM/YYYY", key=f"data_acao_{widget_cliente_key}")

            promessa = None
            p1, p2 = st.columns(2)
            if tipo == "Promessa de pagamento":
                promessa = p1.date_input("Data prometida para pagamento", value=data_ref, format="DD/MM/YYYY", key=f"promessa_{widget_cliente_key}")

            agendar_retorno = p2.checkbox(
                "Agendar nova cobrança/retorno",
                value=tipo in ["Cliente solicitou retorno", "Agendar retorno"],
                key=f"agendar_retorno_{widget_cliente_key}",
            )
            ag1, ag2 = st.columns([1, 2])
            retorno = ag1.date_input("Data do próximo contato", value=data_ref, format="DD/MM/YYYY", key=f"retorno_{widget_cliente_key}")
            motivo_retorno = ag2.text_input("Motivo do retorno", value="Cobrar novamente", key=f"motivo_retorno_{widget_cliente_key}")

            observacao = st.text_area(
                "Observação da ação",
                height=100,
                placeholder="Ex.: cliente informou que pagará após liberação interna...",
                key=f"obs_acao_{widget_cliente_key}",
            )
            salvar_tudo = st.form_submit_button("Salvar todas as alterações", type="primary", use_container_width=True)

            if salvar_tudo:
                resultado = save_cliente_all(
                    cliente_codigo=cliente_codigo,
                    loja=loja,
                    nome_cliente=nome_cliente,
                    tipo_cliente=tipo_cliente,
                    cobrador=cobrador,
                    razao_social=razao_social,
                    cnpj=cnpj,
                    contato=contato,
                    vendedor=vendedor,
                    gerente=gerente,
                    observacao_cliente=obs_atual,
                    tipo_acao=tipo,
                    responsavel_acao=responsavel,
                    data_acao=data_acao,
                    observacao_acao=observacao,
                    promessa=promessa,
                    agendar_retorno=bool(agendar_retorno),
                    data_retorno=retorno if agendar_retorno else None,
                    motivo_retorno=motivo_retorno,
                )
                mensagens = [f"Dados salvos em {resultado['titulos_atualizados']} título(s) aberto(s)."]
                if int(resultado.get("acoes_registradas", 0)):
                    mensagens.append(f"Ação registrada para {resultado['acoes_registradas']} título(s).")
                if resultado.get("agenda") == "atualizada":
                    mensagens.append(f"Agenda de {retorno.strftime('%d/%m/%Y')} atualizada, sem duplicar.")
                elif resultado.get("agenda") == "incluída":
                    mensagens.append(f"Retorno agendado para {retorno.strftime('%d/%m/%Y')}.")

                st.success(" ".join(mensagens) + " Cliente mantido na tela.")
                st.session_state["cliente_index"] = selected_pos
                st.rerun()

        st.markdown("#### Histórico do cliente")
        if titulos_cliente.empty:
            st.caption("Nenhum título aberto para buscar histórico.")
        else:
            ids = titulos_cliente["titulo_id"].astype(str).tolist()
            conn = get_conn()
            placeholders = ",".join(["?"] * len(ids))
            hist = pd.read_sql_query(
                f"SELECT * FROM historico_acoes WHERE titulo_id IN ({placeholders}) ORDER BY data_acao DESC, id DESC",
                conn,
                params=ids,
            )
            conn.close()
            if hist.empty:
                st.caption("Nenhum histórico registrado para os títulos abertos do cliente.")
            else:
                hist = hist.merge(titulos_cliente[["titulo_id", "numero_titulo", "parcela"]], on="titulo_id", how="left")
                hist["data_acao"] = pd.to_datetime(hist["data_acao"], errors="coerce").dt.strftime("%d/%m/%Y")
                hist["observacao"] = hist["observacao"].apply(clean_history_text)
                st.dataframe(
                    hist[["data_acao", "numero_titulo", "parcela", "tipo_acao", "responsavel", "observacao", "promessa_pagamento"]].rename(columns={
                        "data_acao": "Data", "numero_titulo": "Título", "parcela": "Parcela", "tipo_acao": "Ação", "responsavel": "Responsável", "observacao": "Observação", "promessa_pagamento": "Promessa"
                    }),
                    use_container_width=True,
                    hide_index=True,
                )

        st.markdown("#### Exportar relatório do cliente")
        all_titulos_cliente = load_titulos_cliente(cliente_codigo, loja, nome_cliente, somente_abertos=False)
        hist_export = pd.DataFrame()
        if not all_titulos_cliente.empty:
            ids_all = all_titulos_cliente["titulo_id"].astype(str).tolist()
            conn = get_conn()
            placeholders = ",".join(["?"] * len(ids_all))
            hist_export = pd.read_sql_query(
                f"SELECT * FROM historico_acoes WHERE titulo_id IN ({placeholders}) ORDER BY data_acao DESC, id DESC",
                conn,
                params=ids_all,
            )
            conn.close()
        rel_tit = all_titulos_cliente.copy()
        if not rel_tit.empty:
            rel_tit["tipo_cliente"] = str(selected.get("tipo_cliente", "Não especial") or "Não especial")
            rel_tit["cobrador"] = str(selected.get("cobrador", "") or "")
            rel_tit["razao_social"] = str(selected.get("razao_social", "") or "")
            rel_tit["cnpj"] = str(selected.get("cnpj", "") or "")
            rel_tit["contato"] = str(selected.get("contato", "") or "")
            rel_tit = rel_tit[["nome_cliente", "razao_social", "cnpj", "contato", "tipo_cliente", "cobrador", "numero_titulo", "parcela", "tipo", "vencimento", "valor_titulo", "saldo_atual", "status", "vendedor", "gerente", "primeira_aparicao", "ultima_aparicao", "data_baixa", "observacao_atual"]]
        rel_hist = hist_export.copy()
        if not rel_hist.empty:
            rel_hist = rel_hist.merge(all_titulos_cliente[["titulo_id", "numero_titulo", "parcela", "nome_cliente"]], on="titulo_id", how="left")
        try:
            arquivo_excel = safe_to_excel_bytes({"Titulos": rel_tit, "Historico": rel_hist})
            st.download_button(
                "Baixar relatório do cliente em Excel",
                arquivo_excel,
                file_name=f"relatorio_cliente_{nome_cliente[:40].replace('/', '-')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except Exception as exc:
            st.warning(f"Exportação em Excel indisponível: {exc}")
            csv = rel_tit.to_csv(index=False, sep=";", encoding="utf-8-sig")
            st.download_button("Baixar títulos do cliente em CSV", csv, file_name="relatorio_cliente.csv", mime="text/csv", use_container_width=True)


elif page == "Agenda":
    st.markdown("### Agenda de retorno")
    agenda = load_agenda("Todos")
    if agenda.empty:
        st.info("Nenhum retorno agendado.")
    else:
        hoje = data_ref
        agenda["data_dt"] = pd.to_datetime(agenda["data_retorno"], errors="coerce").dt.date
        pend = agenda[agenda["status"] == "Pendente"].copy()
        vencidos = pend[pend["data_dt"] < hoje]
        hoje_df = pend[pend["data_dt"] == hoje]
        futuros = pend[pend["data_dt"] > hoje]
        a1, a2, a3 = st.columns(3)
        a1.metric("Retornos hoje", len(hoje_df))
        a2.metric("Atrasados", len(vencidos))
        a3.metric("Futuros", len(futuros))

        filtro_status = st.selectbox("Status", ["Pendente", "Concluído", "Todos"])
        filtro_resp_agenda = st.text_input("Filtrar responsável ou cliente", placeholder="Digite parte do nome")
        show = load_agenda(filtro_status)
        if not show.empty:
            show["data_dt"] = pd.to_datetime(show["data_retorno"], errors="coerce").dt.date
            show["Situação"] = show.apply(lambda r: "Atrasado" if r["status"] == "Pendente" and r["data_dt"] < hoje else ("Hoje" if r["status"] == "Pendente" and r["data_dt"] == hoje else ("Futuro" if r["status"] == "Pendente" else "Concluído")), axis=1)
            show["Data retorno"] = pd.to_datetime(show["data_retorno"], errors="coerce").dt.strftime("%d/%m/%Y")
            show["motivo"] = show["motivo"].apply(clean_history_text)
            if filtro_resp_agenda:
                termo_agenda = filtro_resp_agenda.strip().lower()
                show = show[show["nome_cliente"].str.lower().str.contains(termo_agenda, na=False) | show["responsavel"].str.lower().str.contains(termo_agenda, na=False)]
            ordem_situacao = {"Atrasado": 0, "Hoje": 1, "Futuro": 2, "Concluído": 3}
            show["ordem"] = show["Situação"].map(ordem_situacao).fillna(9)
            show = show.sort_values(["ordem", "data_retorno", "nome_cliente"])
            st.dataframe(
                show[["id", "Situação", "Data retorno", "nome_cliente", "responsavel", "motivo", "status"]].rename(columns={
                    "id": "ID", "nome_cliente": "Cliente", "responsavel": "Responsável", "motivo": "Motivo", "status": "Status"
                }),
                use_container_width=True,
                hide_index=True,
            )
            pend_ids = show.loc[show["status"] == "Pendente", "id"].tolist()
            if pend_ids:
                with st.form("concluir_agenda_form"):
                    agenda_id = st.selectbox("Marcar retorno como concluído", pend_ids)
                    concluir = st.form_submit_button("Concluir retorno", type="primary")
                    if concluir:
                        concluir_agenda(int(agenda_id))
                        st.success("Retorno concluído.")
                        st.rerun()

elif page == "Carteira":
    st.markdown("### Carteira comercial")
    fila = prepare_fila_clientes(data_ref)
    if fila.empty:
        st.warning("Não há títulos em cobrança.")
    else:
        tab1, tab2, tab3, tab4 = st.tabs(["Gerente", "Vendedor", "Tipo de cliente", "Cobrador"] )
        with tab1:
            df = fila.copy()
            df["gerente"] = df["gerente"].replace("", "Sem gerente")
            g = df.groupby("gerente", as_index=False).agg(
                Clientes=("cliente_id", "count"),
                Titulos=("qtd_titulos", "sum"),
                Valor=("saldo_total", "sum"),
                Maior_atraso=("maior_dias_atraso", "max"),
            ).sort_values("Valor", ascending=False)
            g_show = g.copy(); g_show["Valor"] = g_show["Valor"].apply(br_money)
            st.dataframe(g_show.rename(columns={"gerente":"Gerente", "Maior_atraso":"Maior atraso"}), use_container_width=True, hide_index=True)
        with tab2:
            df = fila.copy()
            df["vendedor"] = df["vendedor"].replace("", "Sem vendedor")
            v = df.groupby("vendedor", as_index=False).agg(
                Clientes=("cliente_id", "count"),
                Titulos=("qtd_titulos", "sum"),
                Valor=("saldo_total", "sum"),
                Maior_atraso=("maior_dias_atraso", "max"),
            ).sort_values("Valor", ascending=False)
            v_show = v.copy(); v_show["Valor"] = v_show["Valor"].apply(br_money)
            st.dataframe(v_show.rename(columns={"vendedor":"Vendedor", "Maior_atraso":"Maior atraso"}), use_container_width=True, hide_index=True)
        with tab3:
            df = fila.copy()
            df["tipo_cliente"] = df["tipo_cliente"].fillna("Não especial")
            t = df.groupby("tipo_cliente", as_index=False).agg(Clientes=("cliente_id", "count"), Titulos=("qtd_titulos", "sum"), Valor=("saldo_total", "sum"), Maior_atraso=("maior_dias_atraso", "max")).sort_values("Valor", ascending=False)
            t_show = t.copy(); t_show["Valor"] = t_show["Valor"].apply(br_money)
            st.dataframe(t_show.rename(columns={"tipo_cliente":"Tipo de cliente", "Maior_atraso":"Maior atraso"}), use_container_width=True, hide_index=True)
        with tab4:
            df = fila.copy()
            df["cobrador"] = df["cobrador"].replace("", "Sem cobrador")
            c = df.groupby("cobrador", as_index=False).agg(Clientes=("cliente_id", "count"), Titulos=("qtd_titulos", "sum"), Valor=("saldo_total", "sum"), Maior_atraso=("maior_dias_atraso", "max")).sort_values("Valor", ascending=False)
            c_show = c.copy(); c_show["Valor"] = c_show["Valor"].apply(br_money)
            st.dataframe(c_show.rename(columns={"cobrador":"Cobrador", "Maior_atraso":"Maior atraso"}), use_container_width=True, hide_index=True)



elif page == "Relatórios":
    st.markdown("### Relatórios")
    fila = prepare_fila_clientes(data_ref)
    if fila.empty:
        st.warning("Não há títulos em cobrança para gerar relatório.")
    else:
        base = fila.copy()
        base["vendedor"] = base["vendedor"].fillna("").replace("", "Sem vendedor")
        base["gerente"] = base["gerente"].fillna("").replace("", "Sem gerente")
        base["tipo_cliente"] = base["tipo_cliente"].fillna("Não especial").replace("", "Não especial")
        base["cobrador"] = base["cobrador"].fillna("").replace("", "Sem cobrador")

        st.markdown("<div class='section-card'>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        modo_rel = c1.selectbox("Agrupar relatório por", ["Vendedor", "Gerente", "Cliente", "Cobrador", "Tipo de cliente"])
        ordenacao = c2.selectbox("Ordenar por", ["Maior valor", "Maior atraso", "Cliente A-Z"])
        formato = c3.selectbox("Formato", ["Resumo e títulos", "Somente resumo", "Somente títulos"])

        f1, f2, f3 = st.columns(3)
        vendedores_sel = f1.multiselect("Vendedor", sorted(base["vendedor"].dropna().unique().tolist()))
        gerentes_sel = f2.multiselect("Gerente", sorted(base["gerente"].dropna().unique().tolist()))
        tipos_sel = f3.multiselect("Tipo de cliente", sorted(base["tipo_cliente"].dropna().unique().tolist()))

        f4, f5, f6 = st.columns(3)
        cobradores_sel = f4.multiselect("Cobrador", sorted(base["cobrador"].dropna().unique().tolist()))
        acao_sel = f5.multiselect("Ação do dia", sorted(base["acao_do_dia"].dropna().unique().tolist()))
        aging_sel = f6.multiselect("Faixa de atraso", ["0-30", "31-60", "61-90", "91-180", "180+"])
        st.markdown("</div>", unsafe_allow_html=True)

        rel = base.copy()
        if vendedores_sel:
            rel = rel[rel["vendedor"].isin(vendedores_sel)]
        if gerentes_sel:
            rel = rel[rel["gerente"].isin(gerentes_sel)]
        if tipos_sel:
            rel = rel[rel["tipo_cliente"].isin(tipos_sel)]
        if cobradores_sel:
            rel = rel[rel["cobrador"].isin(cobradores_sel)]
        if acao_sel:
            rel = rel[rel["acao_do_dia"].isin(acao_sel)]

        def faixa_atraso(dias: int) -> str:
            try:
                d = int(dias)
            except Exception:
                d = 0
            if d <= 30:
                return "0-30"
            if d <= 60:
                return "31-60"
            if d <= 90:
                return "61-90"
            if d <= 180:
                return "91-180"
            return "180+"

        rel["faixa_atraso"] = rel["maior_dias_atraso"].apply(faixa_atraso)
        if aging_sel:
            rel = rel[rel["faixa_atraso"].isin(aging_sel)]

        if ordenacao == "Maior valor":
            rel = rel.sort_values("saldo_total", ascending=False)
        elif ordenacao == "Maior atraso":
            rel = rel.sort_values("maior_dias_atraso", ascending=False)
        else:
            rel = rel.sort_values("nome_cliente", ascending=True)

        total_valor = float(rel["saldo_total"].sum()) if not rel.empty else 0.0
        colm1, colm2, colm3, colm4 = st.columns(4)
        colm1.metric("Valor filtrado", br_money(total_valor))
        colm2.metric("Clientes", int(rel["cliente_id"].nunique()) if not rel.empty else 0)
        colm3.metric("Títulos", int(rel["qtd_titulos"].sum()) if not rel.empty else 0)
        colm4.metric("Maior atraso", int(rel["maior_dias_atraso"].max()) if not rel.empty else 0)

        grupo_col = {
            "Vendedor": "vendedor",
            "Gerente": "gerente",
            "Cliente": "nome_cliente",
            "Cobrador": "cobrador",
            "Tipo de cliente": "tipo_cliente",
        }[modo_rel]

        resumo = pd.DataFrame()
        if not rel.empty:
            resumo = rel.groupby(grupo_col, as_index=False).agg(
                Clientes=("cliente_id", "nunique"),
                Titulos=("qtd_titulos", "sum"),
                Valor=("saldo_total", "sum"),
                Maior_atraso=("maior_dias_atraso", "max"),
            ).sort_values("Valor", ascending=False)
            resumo_show = resumo.copy()
            resumo_show["Valor"] = resumo_show["Valor"].apply(br_money)
            resumo_show = resumo_show.rename(columns={grupo_col: modo_rel, "Maior_atraso": "Maior atraso"})
        else:
            resumo_show = pd.DataFrame(columns=[modo_rel, "Clientes", "Titulos", "Valor", "Maior atraso"])

        detalhes = rel[[
            "nome_cliente", "saldo_total", "qtd_titulos", "maior_dias_atraso", "faixa_atraso",
            "acao_do_dia", "vendedor", "gerente", "tipo_cliente", "cobrador", "razao_social", "cnpj", "contato", "menor_vencimento"
        ]].copy() if not rel.empty else pd.DataFrame()
        if not detalhes.empty:
            detalhes_export = detalhes.copy()
            detalhes_export["saldo_total"] = detalhes_export["saldo_total"].apply(br_money)
            detalhes_export = detalhes_export.rename(columns={
                "nome_cliente": "Cliente", "saldo_total": "Valor em aberto", "qtd_titulos": "Títulos",
                "maior_dias_atraso": "Maior atraso", "faixa_atraso": "Faixa de atraso", "acao_do_dia": "Ação do dia",
                "vendedor": "Vendedor", "gerente": "Gerente", "tipo_cliente": "Tipo de cliente", "cobrador": "Cobrador", "razao_social": "Razão social", "cnpj": "CNPJ", "contato": "Contato",
                "menor_vencimento": "Menor vencimento"
            })
        else:
            detalhes_export = pd.DataFrame()

        if formato in ["Resumo e títulos", "Somente resumo"]:
            st.markdown("#### Resumo")
            st.dataframe(resumo_show, use_container_width=True, hide_index=True)
        if formato in ["Resumo e títulos", "Somente títulos"]:
            st.markdown("#### Clientes/títulos agrupados")
            st.dataframe(detalhes_export, use_container_width=True, hide_index=True)

        # Exporta também os títulos detalhados dos clientes filtrados.
        titulos_export = pd.DataFrame()
        if not rel.empty:
            frames = []
            for _, r in rel.iterrows():
                tcli = load_titulos_cliente(str(r["cliente_codigo"]), str(r["loja"]), str(r["nome_cliente"]), somente_abertos=True)
                if not tcli.empty:
                    frames.append(tcli)
            if frames:
                titulos_export = pd.concat(frames, ignore_index=True)
                keep_cols = [c for c in [
                    "nome_cliente", "cliente_codigo", "loja", "prefixo", "numero_titulo", "parcela", "tipo", "emissao", "vencimento",
                    "valor_titulo", "saldo_atual", "dias_atraso", "status", "vendedor", "gerente", "observacao_atual"
                ] if c in titulos_export.columns]
                titulos_export = titulos_export[keep_cols]
                titulos_export = titulos_export.rename(columns={
                    "nome_cliente": "Cliente", "cliente_codigo": "Cód. Cliente", "loja": "Loja", "prefixo": "Prefixo",
                    "numero_titulo": "Título", "parcela": "Parcela", "tipo": "Tipo", "emissao": "Emissão", "vencimento": "Vencimento",
                    "valor_titulo": "Valor título", "saldo_atual": "Saldo em aberto", "dias_atraso": "Dias atraso", "status": "Status",
                    "vendedor": "Vendedor", "gerente": "Gerente", "observacao_atual": "Observação"
                })

        sheets = {}
        if formato in ["Resumo e títulos", "Somente resumo"]:
            sheets["Resumo"] = resumo_show
        if formato in ["Resumo e títulos", "Somente títulos"]:
            sheets["Clientes agrupados"] = detalhes_export
        if not titulos_export.empty:
            sheets["Titulos detalhados"] = titulos_export

        if sheets:
            excel_bytes = safe_to_excel_bytes(sheets)
            st.download_button(
                "Exportar relatório em Excel",
                data=excel_bytes,
                file_name=f"relatorio_cobranca_{modo_rel.lower().replace(' ', '_')}_{date.today().isoformat()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

elif page == "Segurança":
    st.markdown("### Segurança dos dados")
    health = db_health()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Banco", "OK" if health.get("ok") else "Não iniciado")
    c2.metric("Títulos", int(health.get("titulos", 0)))
    c3.metric("Histórico", int(health.get("historico", 0)))
    c4.metric("Último backup", health.get("ultimo_backup") or "Sem backup")

    st.markdown(backup_status_html(), unsafe_allow_html=True)

    st.markdown("#### Restaurar backup")
    restore_file = st.file_uploader("Restaurar pacote do CRM (.zip) ou banco (.db)", type=["zip", "db"])
    if st.button("Restaurar backup selecionado", type="primary", use_container_width=True):
        try:
            restored = restore_backup_file(restore_file)
            st.success(f"Backup restaurado com sucesso: {restored}")
            st.rerun()
        except Exception as exc:
            st.error(f"Não consegui restaurar o backup: {exc}")

    st.markdown("#### Backup")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Gerar backup local agora", use_container_width=True):
            destino = backup_db("manual")
            if destino:
                st.success(f"Backup local gerado: {destino.name}")
            else:
                st.warning("Ainda não existe banco para gerar backup.")
    with b2:
        try:
            pacote = export_backup_zip()
            st.download_button(
                "Baixar pacote completo",
                pacote,
                file_name=f"crm_financeiro_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                mime="application/zip",
                use_container_width=True,
            )
        except Exception as exc:
            st.error(f"Não consegui gerar o pacote: {exc}")


elif page == "Histórico":
    st.markdown("### Histórico geral de cobrança")

    with st.expander("Importar histórico legado por número da nota", expanded=False):
        st.caption("Use para trazer observações de planilhas antigas e gravar no histórico dos títulos já existentes no CRM.")
        legacy_file = st.file_uploader("Planilha de histórico de cobrança", type=["xlsx", "xls"], key="legacy_history_upload")
        resp_import = st.text_input("Responsável pela importação", value="Importação legado")
        atualizar_obs = st.checkbox("Preencher observação atual quando estiver vazia", value=True)
        if legacy_file:
            try:
                df_legacy = read_legacy_history_upload(legacy_file)
                df_legacy["historico_legado"] = df_legacy["historico_legado"].apply(clean_history_text)
                st.success(f"Histórico lido: {len(df_legacy)} cliente(s)/bloco(s) encontrados.")
                st.dataframe(
                    df_legacy[["cliente_codigo", "nome_cliente", "notas", "historico_legado"]].rename(columns={
                        "cliente_codigo": "Código", "nome_cliente": "Cliente", "notas": "Notas/Títulos", "historico_legado": "Histórico consolidado"
                    }),
                    use_container_width=True,
                    hide_index=True,
                )
                confirmar_legado = st.checkbox("Conferi a prévia e autorizo importar este histórico", value=False)
                if st.button("Importar histórico legado", type="primary", use_container_width=True, disabled=not confirmar_legado):
                    result = import_legacy_history(df_legacy, data_ref, resp_import, atualizar_obs)
                    st.success(f"Importação concluída: {result['historicos_inseridos']} registro(s) incluído(s) em {result['titulos_afetados']} título(s).")
                    if result["sem_match_total"]:
                        st.warning(f"{result['sem_match_total']} bloco(s) não encontraram nota correspondente no CRM.")
                        with st.expander("Ver não encontrados", expanded=False):
                            st.write(result["sem_match"])
                    st.rerun()
            except Exception as exc:
                st.error(f"Não consegui importar o histórico legado: {exc}")

    hist = load_historico()
    tit = load_titulos()
    if hist.empty:
        st.warning("Ainda não há histórico.")
    else:
        if not tit.empty:
            hist = hist.merge(tit[["titulo_id", "nome_cliente", "numero_titulo", "parcela", "saldo_atual", "status", "vendedor", "gerente"]], on="titulo_id", how="left")
        hist["data_acao"] = pd.to_datetime(hist["data_acao"], errors="coerce").dt.strftime("%d/%m/%Y")
        hist["observacao"] = hist["observacao"].apply(clean_history_text)
        hist["saldo_atual"] = hist["saldo_atual"].apply(br_money)
        st.dataframe(
            hist[["data_acao", "nome_cliente", "numero_titulo", "parcela", "tipo_acao", "responsavel", "observacao", "status", "vendedor", "gerente"]].rename(columns={
                "data_acao": "Data", "nome_cliente": "Cliente", "numero_titulo": "Título", "parcela": "Parcela",
                "tipo_acao": "Ação", "responsavel": "Responsável", "observacao": "Observação", "status": "Status", "vendedor": "Vendedor", "gerente": "Gerente"
            }),
            use_container_width=True,
            hide_index=True,
        )


elif page == "Régua":
    st.markdown("### Régua de cobrança")
    regua = load_regua()
    edited = st.data_editor(
        regua,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "dia": st.column_config.NumberColumn("Dia", min_value=1, step=1),
            "acao": "Ação",
            "descricao": "Descrição",
            "responsavel_padrao": "Responsável padrão",
            "prioridade": st.column_config.NumberColumn("Prioridade", min_value=1, max_value=99, step=1),
        },
    )
    if st.button("Salvar régua", type="primary"):
        save_regua(edited)
        st.success("Régua salva.")
        st.rerun()


elif page == "Base de títulos":
    st.markdown("### Base completa de títulos")
    tit = load_titulos()
    if tit.empty:
        st.warning("Faça o primeiro upload para iniciar a base.")
    else:
        status = st.selectbox("Status", ["Todos", STATUS_ATIVO, STATUS_PROMESSA, STATUS_PAGO])
        df = tit.copy()
        if status != "Todos":
            df = df[df["status"] == status]
        cliente = st.text_input("Buscar cliente")
        if cliente:
            df = df[df["nome_cliente"].str.contains(cliente, case=False, na=False)]
        df["Valor título"] = df["valor_titulo"].apply(br_money)
        df["Saldo atual"] = df["saldo_atual"].apply(br_money)
        df["Vencimento"] = pd.to_datetime(df["vencimento"], errors="coerce").dt.strftime("%d/%m/%Y")
        df["Primeira aparição"] = pd.to_datetime(df["primeira_aparicao"], errors="coerce").dt.strftime("%d/%m/%Y")
        df["Última aparição"] = pd.to_datetime(df["ultima_aparicao"], errors="coerce").dt.strftime("%d/%m/%Y")
        df["Baixa"] = pd.to_datetime(df["data_baixa"], errors="coerce").dt.strftime("%d/%m/%Y")

        st.dataframe(
            df[["titulo_id", "filial", "prefixo", "numero_titulo", "parcela", "cliente_codigo", "nome_cliente", "Vencimento", "Valor título", "Saldo atual", "status", "vendedor", "gerente", "Primeira aparição", "Última aparição", "Baixa"]].rename(columns={
                "titulo_id": "ID interno", "filial": "Filial", "prefixo": "Prefixo", "numero_titulo": "Título", "parcela": "Parcela",
                "cliente_codigo": "Cód. Cliente", "nome_cliente": "Cliente", "status": "Status", "vendedor": "Vendedor", "gerente": "Gerente"
            }),
            use_container_width=True,
            hide_index=True,
        )

        csv = df.to_csv(index=False, sep=";", encoding="utf-8-sig")
        st.download_button("Baixar base filtrada CSV", csv, file_name="base_crm_cobranca.csv", mime="text/csv")



# Sincronização externa: no Streamlit Cloud o disco local pode reiniciar.
# Se o cofre GitHub estiver configurado, o banco atual é enviado após cada alteração/rerun.
try:
    upload_db_to_github("auto")
except Exception:
    pass

st.markdown(
    f"""
    <div class="footer-first">
        CRM de Cobrança &nbsp; | &nbsp; <b>Desenvolvido por Paula Verissimo</b> &nbsp; | &nbsp; {APP_VERSION}
    </div>
    """,
    unsafe_allow_html=True,
)
