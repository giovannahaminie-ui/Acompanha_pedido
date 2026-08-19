"""
Banco local (SQLite) - guarda o que NÃO existe no Sapiens:
  - perfil (G / B / U) de cada usuário neste sistema

A autenticação (usuário/senha) continua vindo do Oracle/Sapiens
(ver db/oracle_db.py). Aqui só relacionamos usuário -> perfil.

Apenas a lógica de níveis de acesso (perfil) é local, para não depender do Sapiens.

"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "acompanha_pedido.sqlite3"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Cria as tabelas se ainda não existirem. Chamar uma vez ao subir o app."""
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios_perfil (
            usuario TEXT PRIMARY KEY,   -- login do Sapiens, ex: 'cesar.souza'
            nome    TEXT,               -- nome de exibição
            perfil  TEXT                -- 'G', 'B', 'U' ou NULL (sem perfil)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS historico_acoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo_acao TEXT NOT NULL,    -- 'pedido_criado', 'oc_gerada', 'entrega', etc
            codemp INTEGER,             -- empresa da solicitacao
            codfil INTEGER,             -- filial da solicitacao
            numsol INTEGER,             -- numero da solicitacao
            numped INTEGER,             -- numero do pedido
            numocp INTEGER,             -- numero da ordem de compra
            usuario TEXT,               -- login do usuario que realizou
            data_hora DATETIME DEFAULT CURRENT_TIMESTAMP,
            detalhes TEXT               -- detalhes adicionais em JSON
        )
        """
    )
    # Migração: bancos criados antes da adição de codemp/codfil na tabela
    colunas_existentes = {row["name"] for row in conn.execute("PRAGMA table_info(historico_acoes)").fetchall()}
    if "codemp" not in colunas_existentes:
        conn.execute("ALTER TABLE historico_acoes ADD COLUMN codemp INTEGER")
    if "codfil" not in colunas_existentes:
        conn.execute("ALTER TABLE historico_acoes ADD COLUMN codfil INTEGER")
    conn.commit()
    conn.close()


def get_perfil(usuario: str):
    """Retorna 'G' / 'B' / 'U' ou None se o usuário não tem perfil atribuído."""
    conn = get_conn()
    row = conn.execute(
        "SELECT perfil FROM usuarios_perfil WHERE usuario = ?", (usuario,)
    ).fetchone()
    conn.close()
    return row["perfil"] if row and row["perfil"] else None

def listar_usuarios_com_perfil(usuarios_sapiens):
    """
    Combina a lista de usuários ativos do Sapiens (usuarios_sapiens, vinda de
    oracle_db.listar_usuarios_ativos: [{"usuario":.., "nome":..}, ...]) com o
    perfil já atribuído localmente, se houver - assim a gerência vê e classifica
    todo mundo, mesmo quem nunca acessou o sistema ainda.
    
    """
    conn = get_conn()
    perfis = {
        r["usuario"]: r["perfil"]
        for r in conn.execute("SELECT usuario, perfil FROM usuarios_perfil").fetchall()
    }
    conn.close()
    return [
        {"usuario": u["usuario"], "nome": u["nome"], "perfil": perfis.get(u["usuario"])}
        for u in usuarios_sapiens
    ]

def upsert_usuario(usuario: str, nome: str = None):
    """Garante que o usuário existe na tabela local (sem perfil, se for novo)."""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO usuarios_perfil (usuario, nome, perfil)
        VALUES (?, ?, NULL)
        ON CONFLICT(usuario) DO UPDATE SET nome = excluded.nome
            WHERE excluded.nome IS NOT NULL
        """,
        (usuario, nome),
    )
    conn.commit()
    conn.close()

def salvar_perfil(usuario: str, perfil: str, nome: str = None):
    """
    perfil deve ser 'G', 'B', 'U' ou '' (string vazia = remover perfil).
    Cria o registro do usuário se ele ainda não tiver logado no sistema
    (ex: gerência classificando alguém do Sapiens antes do primeiro acesso).
    """
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO usuarios_perfil (usuario, nome, perfil)
        VALUES (?, ?, ?)
        ON CONFLICT(usuario) DO UPDATE SET perfil = excluded.perfil
        """,
        (usuario, nome, perfil or None),
    )
    conn.commit()
    conn.close()


# ===== HISTÓRICO DE AÇÕES =====

def registrar_acao(tipo_acao: str, usuario: str, codemp: int = None, codfil: int = None, numsol: int = None, numped: int = None, numocp: int = None, detalhes: str = None):
    """Registra uma ação no histórico."""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO historico_acoes (tipo_acao, codemp, codfil, numsol, numped, numocp, usuario, data_hora, detalhes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (tipo_acao, codemp, codfil, numsol, numped, numocp, usuario, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), detalhes),
    )
    conn.commit()
    conn.close()


def listar_historico_por_solicitacao(codemp: int, codfil: int, numsol: int, limite: int = 50):
    """Lista histórico de uma solicitação específica."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, tipo_acao, codemp, codfil, numsol, numped, numocp, usuario, data_hora, detalhes
        FROM historico_acoes
        WHERE codemp = ? AND codfil = ? AND numsol = ?
        ORDER BY data_hora DESC
        LIMIT ?
        """,
        (codemp, codfil, numsol, limite),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def listar_historico_por_pedido(numped: int, limite: int = 50):
    """Lista histórico de um pedido específico."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, tipo_acao, codemp, codfil, numsol, numped, numocp, usuario, data_hora, detalhes
        FROM historico_acoes
        WHERE numped = ?
        ORDER BY data_hora DESC
        LIMIT ?
        """,
        (numped, limite),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def listar_historico_geral(limite: int = 100):
    """Lista histórico geral de todas as ações."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, tipo_acao, codemp, codfil, numsol, numped, numocp, usuario, data_hora, detalhes
        FROM historico_acoes
        ORDER BY data_hora DESC
        LIMIT ?
        """,
        (limite,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def listar_historico_usuario(usuario: str, limite: int = 50):
    """Lista histórico de um usuário específico."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, tipo_acao, codemp, codfil, numsol, numped, numocp, usuario, data_hora, detalhes
        FROM historico_acoes
        WHERE usuario = ?
        ORDER BY data_hora DESC
        LIMIT ?
        """,
        (usuario, limite),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
