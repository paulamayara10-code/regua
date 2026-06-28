# -*- coding: utf-8 -*-
"""
FIRST MEDICAL SERVICE
CRM Financeiro de Cobrança
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
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

APP_NAME = "FIRST MEDICAL SERVICE"
APP_TITLE = "CRM Financeiro de Cobrança"
APP_VERSION = "v1.0 - Régua e histórico de inadimplência"
DB_PATH = Path("crm_cobranca_first.db")

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
    "Outro",
]

STATUS_ATIVO = "Em cobrança"
STATUS_PAGO = "Pago"
STATUS_PROMESSA = "Aguardando promessa"


# -----------------------------------------------------------------------------
# Configuração visual
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="CRM Financeiro - First",
    page_icon="💼",
    layout="wide",
)

st.markdown(
    """
    <style>
        .main {background-color: #f7f9fc;}
        .block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
        .first-header {
            background: linear-gradient(135deg, #0f2742 0%, #174d7c 55%, #1b6fae 100%);
            color: white; padding: 24px 28px; border-radius: 20px; margin-bottom: 18px;
            box-shadow: 0 10px 30px rgba(15,39,66,0.18);
        }
        .first-header h1 {margin: 0; font-size: 30px; font-weight: 800;}
        .first-header p {margin: 6px 0 0 0; opacity: .92;}
        .metric-card {
            background: white; border-radius: 18px; padding: 18px 20px; border: 1px solid #e7edf5;
            box-shadow: 0 6px 20px rgba(15,39,66,0.06); min-height: 112px;
        }
        .metric-label {font-size: 13px; color: #667085; font-weight: 700; text-transform: uppercase; letter-spacing: .04em;}
        .metric-value {font-size: 26px; color: #101828; font-weight: 850; margin-top: 8px;}
        .metric-help {font-size: 12px; color: #98a2b3; margin-top: 5px;}
        .section-card {
            background: white; border-radius: 18px; padding: 18px; border: 1px solid #e7edf5;
            box-shadow: 0 6px 20px rgba(15,39,66,0.06); margin-bottom: 16px;
        }
        .small-muted {color:#667085; font-size:13px;}
        div[data-testid="stDataFrame"] {background:white;}
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------------------------------------------------------
# Banco de dados
# -----------------------------------------------------------------------------
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
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


def to_date_str(value) -> Optional[str]:
    if pd.isna(value) or value == "":
        return None
    try:
        return pd.to_datetime(value).date().isoformat()
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


def read_excel_upload(file) -> pd.DataFrame:
    df = pd.read_excel(file)
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


def process_upload(df: pd.DataFrame, data_ref: date, arquivo_nome: str) -> Tuple[int, int, int, float]:
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")
    data_ref_str = data_ref.isoformat()

    current_ids = set(df["titulo_id"].astype(str).tolist())

    existing = pd.read_sql_query("SELECT titulo_id, status, primeira_aparicao, ultima_aparicao FROM titulos", conn)
    existing_ids = set(existing["titulo_id"].astype(str).tolist()) if not existing.empty else set()
    active_existing_ids = set(existing.loc[existing["status"] != STATUS_PAGO, "titulo_id"].astype(str).tolist()) if not existing.empty else set()

    novos = 0
    atualizados = 0

    for _, row in df.iterrows():
        tid = str(row["titulo_id"])
        ciclo = 1
        if tid in existing_ids:
            cur.execute("SELECT primeira_aparicao FROM titulos WHERE titulo_id = ?", (tid,))
            first = cur.fetchone()["primeira_aparicao"]
            ciclo = calcular_ciclo(first, data_ref)
            cur.execute(
                """
                UPDATE titulos
                   SET filial = ?, prefixo = ?, numero_titulo = ?, parcela = ?, tipo = ?,
                       cliente_codigo = ?, loja = ?, nome_cliente = ?, dt_emissao = ?, vencimento = ?,
                       valor_titulo = ?, saldo_atual = ?, multa = ?, juros = ?,
                       status = CASE WHEN status = 'Pago' THEN 'Em cobrança' ELSE status END,
                       ultima_aparicao = ?, data_baixa = NULL, ciclo_cobranca = ?, updated_at = ?
                 WHERE titulo_id = ?
                """,
                (
                    normalize_text(row.get("Filial")), normalize_text(row.get("Prefixo")), normalize_text(row.get("No. Titulo")),
                    normalize_text(row.get("Parcela")), normalize_text(row.get("Tipo")), normalize_text(row.get("Cliente")), normalize_text(row.get("Loja")),
                    normalize_text(row.get("Nome Cliente")), row.get("dt_emissao_str"), row.get("vencimento_str"),
                    float(row.get("Vlr.Titulo", 0)), float(row.get("Saldo a receber", 0)), float(row.get("Multa", 0)), float(row.get("Juros", 0)),
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
                    multa, juros, status, primeira_aparicao, ultima_aparicao, ciclo_cobranca, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid, normalize_text(row.get("Filial")), normalize_text(row.get("Prefixo")), normalize_text(row.get("No. Titulo")),
                    normalize_text(row.get("Parcela")), normalize_text(row.get("Tipo")), normalize_text(row.get("Cliente")), normalize_text(row.get("Loja")),
                    normalize_text(row.get("Nome Cliente")), row.get("dt_emissao_str"), row.get("vencimento_str"),
                    float(row.get("Vlr.Titulo", 0)), float(row.get("Saldo a receber", 0)), float(row.get("Saldo a receber", 0)),
                    float(row.get("Multa", 0)), float(row.get("Juros", 0)), STATUS_ATIVO, data_ref_str, data_ref_str, 1, now, now,
                ),
            )
            cur.execute(
                "INSERT INTO historico_acoes (titulo_id, data_acao, tipo_acao, responsavel, observacao, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (tid, data_ref_str, "Entrada na régua", "Sistema", "Título apareceu no relatório de vencidos.", now),
            )
            novos += 1

    # Títulos ativos que não apareceram no relatório do dia são considerados pagos/baixados.
    paid_ids = sorted(active_existing_ids - current_ids)
    for tid in paid_ids:
        cur.execute(
            "UPDATE titulos SET status = ?, data_baixa = ?, updated_at = ? WHERE titulo_id = ?",
            (STATUS_PAGO, data_ref_str, now, tid),
        )
        cur.execute(
            "INSERT INTO historico_acoes (titulo_id, data_acao, tipo_acao, responsavel, observacao, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (tid, data_ref_str, "Baixa automática", "Sistema", "Título não reapresentado no relatório diário; marcado como pago.", now),
        )

    valor_aberto = float(df["Saldo a receber"].sum())
    cur.execute(
        """
        INSERT INTO uploads (data_referencia, arquivo, qtd_linhas, novos, atualizados, pagos, valor_aberto, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (data_ref_str, arquivo_nome, len(df), novos, atualizados, len(paid_ids), valor_aberto, now),
    )

    conn.commit()
    conn.close()
    return novos, atualizados, len(paid_ids), valor_aberto


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


def update_titulo_fields(titulo_id: str, vendedor: str, gerente: str, observacao: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE titulos SET vendedor = ?, gerente = ?, observacao_atual = ?, updated_at = ? WHERE titulo_id = ?",
        (vendedor.strip(), gerente.strip(), observacao.strip(), datetime.now().isoformat(timespec="seconds"), titulo_id),
    )
    conn.commit()
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


def metric_card(label: str, value: str, help_text: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-help">{help_text}</div>
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
    <div class="first-header">
        <h1>{APP_TITLE}</h1>
        <p>{APP_NAME} • {APP_VERSION}</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Navegação")
    page = st.radio(
        "Selecione",
        ["Dashboard", "Upload diário", "Fila de cobrança", "Cliente / título", "Histórico", "Régua", "Base de títulos"],
        label_visibility="collapsed",
    )
    data_ref = st.date_input("Data de referência", value=date.today(), format="DD/MM/YYYY")
    st.caption("A data de referência é usada para processar o relatório e calcular a ação do dia.")


if page == "Upload diário":
    st.markdown("### Upload diário do relatório Protheus")
    st.info("Envie o relatório de títulos vencidos. O sistema atualiza o histórico, identifica novos títulos e marca como pagos os títulos que não forem reapresentados.")

    uploaded = st.file_uploader("Relatório: Títulos a receber vencidos", type=["xlsx", "xls"])
    if uploaded:
        try:
            df_upload = read_excel_upload(uploaded)
            st.success(f"Arquivo lido com sucesso: {len(df_upload)} títulos encontrados.")

            c1, c2, c3 = st.columns(3)
            c1.metric("Valor em aberto no arquivo", br_money(df_upload["Saldo a receber"].sum()))
            c2.metric("Clientes", df_upload["Cliente"].nunique())
            c3.metric("Títulos", len(df_upload))

            with st.expander("Prévia do arquivo importado", expanded=False):
                preview_cols = ["Filial", "Prefixo", "No. Titulo", "Parcela", "Cliente", "Nome Cliente", "Vencto real", "Saldo a receber"]
                st.dataframe(df_upload[preview_cols], use_container_width=True, hide_index=True)

            if st.button("Atualizar CRM com este relatório", type="primary", use_container_width=True):
                novos, atualizados, pagos, valor_aberto = process_upload(df_upload, data_ref, uploaded.name)
                st.success("Histórico atualizado com sucesso.")
                a, b, c, d = st.columns(4)
                a.metric("Novos", novos)
                b.metric("Atualizados", atualizados)
                c.metric("Pagos identificados", pagos)
                d.metric("Valor aberto", br_money(valor_aberto))
                st.balloons()
        except Exception as exc:
            st.error(f"Não consegui processar o arquivo: {exc}")


elif page == "Dashboard":
    fila = prepare_fila(data_ref)
    all_titles = load_titulos()
    open_titles = all_titles[all_titles["status"] != STATUS_PAGO].copy() if not all_titles.empty else pd.DataFrame()
    paid_titles = all_titles[all_titles["status"] == STATUS_PAGO].copy() if not all_titles.empty else pd.DataFrame()

    st.markdown("### Visão executiva")
    if all_titles.empty:
        st.warning("Ainda não existe histórico. Faça o primeiro upload diário para iniciar o CRM.")
    else:
        total_aberto = float(open_titles["saldo_atual"].sum()) if not open_titles.empty else 0
        clientes_abertos = int(open_titles["cliente_codigo"].nunique()) if not open_titles.empty else 0
        acoes_hoje = int(len(fila[~fila["acao_do_dia"].eq("Aguardar promessa")])) if not fila.empty else 0
        promessas = int(len(fila[fila["acao_do_dia"].eq("Aguardar promessa")])) if not fila.empty else 0
        recebidos = float(paid_titles.loc[paid_titles["data_baixa"] == data_ref.isoformat(), "saldo_original"].sum()) if not paid_titles.empty else 0

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: metric_card("Valor em atraso", br_money(total_aberto), "Saldo a receber em aberto")
        with c2: metric_card("Clientes", f"{clientes_abertos}", "Clientes com títulos vencidos")
        with c3: metric_card("Títulos", f"{len(open_titles)}", "Títulos em cobrança")
        with c4: metric_card("Recebidos hoje", br_money(recebidos), "Baixas automáticas/manual")
        with c5: metric_card("Ações hoje", f"{acoes_hoje}", f"{promessas} promessas aguardando")

        st.markdown("### Ações prioritárias")
        if fila.empty:
            st.success("Nenhuma ação em aberto.")
        else:
            show = fila.head(20).copy()
            show["Valor"] = show["saldo_atual"].apply(br_money)
            show["Vencimento"] = pd.to_datetime(show["vencimento"], errors="coerce").dt.strftime("%d/%m/%Y")
            cols = ["nome_cliente", "numero_titulo", "parcela", "Valor", "Vencimento", "dias_atraso", "ciclo_cobranca", "acao_do_dia", "vendedor", "gerente"]
            st.dataframe(
                show[cols].rename(columns={
                    "nome_cliente": "Cliente", "numero_titulo": "Título", "parcela": "Parcela",
                    "dias_atraso": "Dias atraso", "ciclo_cobranca": "Dia régua", "acao_do_dia": "Ação do dia",
                    "vendedor": "Vendedor", "gerente": "Gerente",
                }),
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("### Inadimplência por ação")
        if not fila.empty:
            grouped = fila.groupby("acao_do_dia", as_index=False).agg(
                Titulos=("titulo_id", "count"), Valor=("saldo_atual", "sum")
            ).sort_values("Valor", ascending=False)
            grouped["Valor"] = grouped["Valor"].apply(br_money)
            st.dataframe(grouped.rename(columns={"acao_do_dia": "Ação"}), use_container_width=True, hide_index=True)


elif page == "Fila de cobrança":
    st.markdown("### Minha fila de cobrança")
    fila = prepare_fila(data_ref)
    if fila.empty:
        st.success("Não há títulos em cobrança.")
    else:
        colf1, colf2, colf3 = st.columns([2, 1, 1])
        cliente_search = colf1.text_input("Filtrar cliente", placeholder="Digite parte do nome do cliente")
        acao_filter = colf2.selectbox("Ação", ["Todas"] + sorted(fila["acao_do_dia"].dropna().unique().tolist()))
        apenas_sem_resp = colf3.checkbox("Sem vendedor/gerente")

        filtered = fila.copy()
        if cliente_search:
            filtered = filtered[filtered["nome_cliente"].str.contains(cliente_search, case=False, na=False)]
        if acao_filter != "Todas":
            filtered = filtered[filtered["acao_do_dia"] == acao_filter]
        if apenas_sem_resp:
            filtered = filtered[(filtered["vendedor"].fillna("") == "") | (filtered["gerente"].fillna("") == "")]

        filtered["Valor"] = filtered["saldo_atual"].apply(br_money)
        filtered["Vencimento"] = pd.to_datetime(filtered["vencimento"], errors="coerce").dt.strftime("%d/%m/%Y")
        st.dataframe(
            filtered[["titulo_id", "nome_cliente", "numero_titulo", "parcela", "Valor", "Vencimento", "dias_atraso", "ciclo_cobranca", "acao_do_dia", "vendedor", "gerente"]].rename(columns={
                "titulo_id": "ID interno", "nome_cliente": "Cliente", "numero_titulo": "Título", "parcela": "Parcela",
                "dias_atraso": "Dias atraso", "ciclo_cobranca": "Dia régua", "acao_do_dia": "Ação do dia",
                "vendedor": "Vendedor", "gerente": "Gerente",
            }),
            use_container_width=True,
            hide_index=True,
        )
        st.caption("Copie o ID interno do título para registrar ação na aba 'Cliente / título'.")


elif page == "Cliente / título":
    st.markdown("### Atendimento do título")
    titulos = load_titulos()
    if titulos.empty:
        st.warning("Faça o primeiro upload para consultar títulos.")
    else:
        options = titulos.copy()
        options["label"] = options.apply(
            lambda r: f"{r['nome_cliente']} • Título {r['numero_titulo']} • Parcela {r['parcela'] or '-'} • {br_money(r['saldo_atual'])} • {r['status']}", axis=1
        )
        selected_label = st.selectbox("Selecione o título", options["label"].tolist())
        selected = options.loc[options["label"] == selected_label].iloc[0]
        tid = selected["titulo_id"]

        ref = data_ref
        dias_atraso = calcular_dias_atraso(selected["vencimento"], ref)
        ciclo = calcular_ciclo(selected["primeira_aparicao"], ref)
        acao = get_action_for_day(ciclo, selected["status"], selected["promessa_pagamento"], ref)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cliente", selected["nome_cliente"])
        c2.metric("Saldo", br_money(selected["saldo_atual"]))
        c3.metric("Dias em atraso", dias_atraso)
        c4.metric("Ação do dia", acao["acao"])

        st.markdown("#### Responsáveis do título")
        with st.form("form_responsaveis"):
            r1, r2 = st.columns(2)
            vendedor = r1.text_input("Vendedor", value=str(selected["vendedor"] or ""))
            gerente = r2.text_input("Gerente", value=str(selected["gerente"] or ""))
            obs_atual = st.text_area("Observação atual do título", value=str(selected["observacao_atual"] or ""), height=90)
            salvar_resp = st.form_submit_button("Salvar responsáveis/observação", type="primary")
            if salvar_resp:
                update_titulo_fields(tid, vendedor, gerente, obs_atual)
                st.success("Responsáveis atualizados.")
                st.rerun()

        st.markdown("#### Registrar ação")
        with st.form("form_acao"):
            a1, a2, a3 = st.columns([1.2, 1, 1])
            tipo = a1.selectbox("Ação realizada", ACTION_OPTIONS)
            responsavel = a2.text_input("Responsável pela ação", value="Financeiro")
            data_acao = a3.date_input("Data da ação", value=data_ref, format="DD/MM/YYYY")
            promessa = None
            if tipo == "Promessa de pagamento":
                promessa = st.date_input("Data prometida para pagamento", value=data_ref, format="DD/MM/YYYY")
            observacao = st.text_area("Observação da ação", height=100, placeholder="Ex.: cliente informou que pagará após liberação interna...")
            salvar_acao = st.form_submit_button("Registrar no histórico", type="primary")
            if salvar_acao:
                add_action(tid, data_acao, tipo, responsavel, observacao, promessa)
                st.success("Ação registrada no histórico.")
                st.rerun()

        st.markdown("#### Histórico do título")
        hist = load_historico(tid)
        if hist.empty:
            st.caption("Nenhum histórico registrado.")
        else:
            hist_show = hist.copy()
            hist_show["data_acao"] = pd.to_datetime(hist_show["data_acao"], errors="coerce").dt.strftime("%d/%m/%Y")
            st.dataframe(
                hist_show[["data_acao", "tipo_acao", "responsavel", "observacao", "promessa_pagamento"]].rename(columns={
                    "data_acao": "Data", "tipo_acao": "Ação", "responsavel": "Responsável", "observacao": "Observação", "promessa_pagamento": "Promessa"
                }),
                use_container_width=True,
                hide_index=True,
            )


elif page == "Histórico":
    st.markdown("### Histórico geral de cobrança")
    hist = load_historico()
    tit = load_titulos()
    if hist.empty:
        st.warning("Ainda não há histórico.")
    else:
        if not tit.empty:
            hist = hist.merge(tit[["titulo_id", "nome_cliente", "numero_titulo", "parcela", "saldo_atual", "status", "vendedor", "gerente"]], on="titulo_id", how="left")
        hist["data_acao"] = pd.to_datetime(hist["data_acao"], errors="coerce").dt.strftime("%d/%m/%Y")
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
    st.caption("Você pode alterar os dias, ações e responsáveis. O sistema sempre usa a maior regra cujo dia seja menor ou igual ao dia atual da cobrança.")
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
