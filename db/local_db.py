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

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS itens_inserir_pendentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codemp INTEGER NOT NULL,
            codfil INTEGER NOT NULL,
            numsol INTEGER NOT NULL,
            codpro TEXT NOT NULL,
            descricao TEXT,
            qtd REAL NOT NULL,
            preco REAL NOT NULL,
            codtab TEXT,
            usuario TEXT,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    colunas_pendentes = {row["name"] for row in conn.execute("PRAGMA table_info(itens_inserir_pendentes)").fetchall()}
    if "is_alteracao" not in colunas_pendentes:
        conn.execute("ALTER TABLE itens_inserir_pendentes ADD COLUMN is_alteracao INTEGER DEFAULT 0")
    if "seqite_existente" not in colunas_pendentes:
        conn.execute("ALTER TABLE itens_inserir_pendentes ADD COLUMN seqite_existente INTEGER")
    if "seqipd_existente" not in colunas_pendentes:
        conn.execute("ALTER TABLE itens_inserir_pendentes ADD COLUMN seqipd_existente INTEGER")

    # De-para crachá -> código de usuário do Sapiens. O código de barras do
    # crachá é aleatório (não tem relação com o codusu), então a única forma
    # de identificar quem passou o crachá é essa tabela, alimentada uma vez
    # por pessoa na tela /admin/crachas.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cracha_usuario (
            codigo_cracha TEXT PRIMARY KEY,   -- o que o leitor lê, ex: QmiT#wC6iXdG
            codusu        TEXT NOT NULL,      -- código de usuário do Sapiens
            nome          TEXT,               -- nome vindo do Sapiens (conferência)
            criado_em     DATETIME DEFAULT CURRENT_TIMESTAMP,
            criado_por    TEXT                -- codusu de quem cadastrou
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS
    itens_conferencia_pendentes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codemp INTEGER NOT NULL,
            codfil INTEGER NOT NULL,
            numsol INTEGER NOT NULL,
            codbar TEXT NOT NULL,
            qtd REAL NOT NULL,
            usuario TEXT,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
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

def listar_itens_pendentes(codemp, codfil, numsol):
    conn = get_conn()
    linhas = conn.execute(
        "SELECT * FROM itens_inserir_pendentes WHERE codemp=? AND codfil=? AND numsol=? ORDER BY id",
        (codemp, codfil, numsol),
    ).fetchall()
    conn.close()
    return [dict(l) for l in linhas]

def adicionar_item_pendente(codemp, codfil, numsol, codpro, descricao, qtd, preco, codtab, usuario,
                             is_alteracao=False, seqite_existente=None, seqipd_existente=None):
    conn = get_conn()
    conn.execute(
        """INSERT INTO itens_inserir_pendentes
           (codemp, codfil, numsol, codpro, descricao, qtd, preco, codtab, usuario,
            is_alteracao, seqite_existente, seqipd_existente)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (codemp, codfil, numsol, codpro, descricao, qtd, preco, codtab, usuario,
         1 if is_alteracao else 0, seqite_existente, seqipd_existente),
    )
    conn.commit()
    conn.close()

def remover_item_pendente(id_pendente):
    conn = get_conn()
    conn.execute("DELETE FROM itens_inserir_pendentes WHERE id=?", (id_pendente,))
    conn.commit()
    conn.close()

def listar_itens_conferencia_pendentes(codemp, codfil, numsol):
    conn = get_conn()
    linhas = conn.execute(
        "SELECT * FROM itens_conferencia_pendentes "
        "WHERE codemp = ? AND codfil = ? AND numsol = ? "
        "ORDER BY id",
        (codemp, codfil, numsol),
    ).fetchall()
    conn.close()
    return [dict(l) for l in linhas]

def adicionar_item_conferencia_pendentes(codemp, codfil, numsol, codbar, qtd, usuario):
    conn = get_conn()
    conn.execute(
        """INSERT INTO itens_conferencia_pendentes(codemp, codfil, numsol, codbar, qtd, usuario)
           VALUES (?, ?, ?, ?, ?, ?)""",
           (codemp, codfil, numsol, codbar, qtd, usuario),
    )
    conn.commit()
    conn.close()

def remover_item_conferencia_pendente(id_pendente):
    conn = get_conn()
    conn.execute("DELETE FROM itens_conferencia_pendentes WHERE id=?",
    (id_pendente,))
    conn.commit()
    conn.close()


# ===== DE-PARA CRACHÁ -> CODUSU =====

def get_codusu_por_cracha(codigo_cracha: str):
    """Retorna o codusu (str) vinculado a esse código de crachá, ou None."""
    if not codigo_cracha:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT codusu FROM cracha_usuario WHERE codigo_cracha = ?",
        (codigo_cracha,),
    ).fetchone()
    conn.close()
    return row["codusu"] if row else None


def salvar_cracha(codigo_cracha: str, codusu: str, nome: str = None, criado_por: str = None):
    """Cadastra (ou re-vincula) um crachá a um codusu do Sapiens."""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO cracha_usuario (codigo_cracha, codusu, nome, criado_por)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(codigo_cracha) DO UPDATE SET
            codusu     = excluded.codusu,
            nome       = excluded.nome,
            criado_por = excluded.criado_por,
            criado_em  = CURRENT_TIMESTAMP
        """,
        (codigo_cracha, codusu, nome, criado_por),
    )
    conn.commit()
    conn.close()


def listar_crachas():
    """Lista os crachás cadastrados (mais recentes primeiro), já com o
    perfil (G/B/U) atual da pessoa, se houver."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT c.codigo_cracha, c.codusu, c.nome, c.criado_em, c.criado_por,
               p.perfil AS perfil
        FROM cracha_usuario c
        LEFT JOIN usuarios_perfil p ON p.usuario = c.codusu
        ORDER BY c.criado_em DESC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def remover_cracha(codigo_cracha: str):
    conn = get_conn()
    conn.execute("DELETE FROM cracha_usuario WHERE codigo_cracha = ?", (codigo_cracha,))
    conn.commit()
    conn.close()
