"""
Banco local (SQLite) - guarda o que NÃO existe no Sapiens:
  - perfil (G / B / U) de cada usuário neste sistema

A autenticação (usuário/senha) continua vindo do Oracle/Sapiens
(ver db/oracle_db.py). Aqui só relacionamos usuário -> perfil.

"""

import sqlite3
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
        CREATE TABLE IF NOT EXISTS comentarios_item (
            codemp      INTEGER,
            codfil      INTEGER,
            numsol      INTEGER,
            codpro      TEXT,
            comentario  TEXT,
            usuario     TEXT,   -- quem escreveu o comentário
            data        TEXT,   -- data/hora do último comentário
            PRIMARY KEY (codemp, codfil, numsol, codpro)
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


def get_comentario(codemp: int, codfil: int, numsol: int, codpro: str):
    """Retorna dict {comentario, usuario, data} do item, ou None se não houver."""
    conn = get_conn()
    row = conn.execute(
        """
        SELECT comentario, usuario, data FROM comentarios_item
        WHERE codemp=? AND codfil=? AND numsol=? AND codpro=?
        """,
        (codemp, codfil, numsol, str(codpro)),
    ).fetchone()
    conn.close()
    return dict(row) if row and row["comentario"] else None


def get_comentarios_solicitacao(codemp: int, codfil: int, numsol: int):
    """Retorna {codpro: comentario} de todos os itens comentados dessa solicitação -
    usado pra saber, na listagem, quais itens já têm comentário."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT codpro, comentario FROM comentarios_item WHERE codemp=? AND codfil=? AND numsol=?",
        (codemp, codfil, numsol),
    ).fetchall()
    conn.close()
    return {r["codpro"]: r["comentario"] for r in rows if r["comentario"]}


def salvar_comentario(codemp: int, codfil: int, numsol: int, codpro: str, comentario: str, usuario: str):
    """Guarda localmente (não existe campo pra isso no T120SIT do Sapiens ainda)."""
    from datetime import datetime
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO comentarios_item (codemp, codfil, numsol, codpro, comentario, usuario, data)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(codemp, codfil, numsol, codpro) DO UPDATE SET
            comentario = excluded.comentario, usuario = excluded.usuario, data = excluded.data
        """,
        (codemp, codfil, numsol, str(codpro), comentario.strip(), usuario, datetime.now().strftime("%d/%m/%Y %H:%M")),
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
