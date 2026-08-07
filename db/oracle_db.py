"""
Acesso ao Oracle (Sapiens). Querys estruturadas para o app Acompanha Pedido - Estoque Retífica.
"""

import os
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()  # lê o arquivo .env na raiz do projeto

ORACLE_DSN = os.environ.get("ORACLE_DSN", "")
ORACLE_USER = os.environ.get("ORACLE_USER", "")
ORACLE_PASSWORD = os.environ.get("ORACLE_PASSWORD", "")


def get_connection():
    """
    Abre conexão Oracle em modo thick
    """
    import oracledb
    oracledb.init_oracle_client()  # thick mode
    return oracledb.connect(
        user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=ORACLE_DSN
    )


# ---------------------------------------------------------------------
# Autenticação - identifica o usuário pelo código do Sapiens (não existe
# senha individual cadastrada, só o código/crachá).
# ---------------------------------------------------------------------

SQL_LOGIN = """
                SELECT codusu,
                       MAX(nomusu) KEEP (DENSE_RANK FIRST ORDER BY LENGTH(nomusu) DESC) AS nomusu
                FROM sapiens.E099USU
                WHERE codusu = :usuario
                AND situsu = 'A'
                GROUP BY codusu
"""


def verificar_login(usuario: str):
    """
    Retorna dict com dados básicos do usuário se o código existir e estiver
    ativo no Sapiens, ou None se inválido.
    """
    try:
        codusu = int(usuario)
    except ValueError:
        return None

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_LOGIN, usuario=codusu)
    row = cur.fetchone()
    conn.close()
    return {"usuario": str(row[0]), "nome": row[1]} if row else None


# ---------------------------------------------------------------------
# Lista de usuários ativos do Sapiens (para a aba de administração de
# perfis - a gerência pode classificar o perfil de qualquer um, mesmo
# quem nunca acessou o sistema ainda).
# ---------------------------------------------------------------------
SQL_USUARIOS_ATIVOS = """
                SELECT codusu,
                       MAX(nomusu) KEEP (DENSE_RANK FIRST ORDER BY LENGTH(nomusu) DESC) AS nomusu
                FROM sapiens.E099USU
                WHERE situsu = 'A'
                GROUP BY codusu
                ORDER BY 2
"""


def listar_usuarios_ativos():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_USUARIOS_ATIVOS)
    usuarios = [{"usuario": str(codusu), "nome": nome} for codusu, nome in cur.fetchall()]
    conn.close()
    return usuarios


# ---------------------------------------------------------------------
# Select das solicitações a serem exibidas na tela
# ---------------------------------------------------------------------
SQL_SOLICITACOES = """
                SELECT s.USU_CODEMP,
                        s.USU_CODFIL,
                        s.USU_NUMSOL,
                        s.USU_NUMPED,
                        s.USU_SITSOL,
                        s.USU_DATSOL,
                        s.USU_HORSOL,
                        s.USU_USUSOL,
                        s.USU_DATSEP,
                        s.USU_HORSEP,
                        s.USU_USUSEP,
                        s.USU_OBSSOL,
                        s.USU_DATCON,
                        s.USU_HORCON,
                        s.USU_USUCON,
                        s.USU_DATENT,
                        s.USU_HORENT,
                        s.USU_USUENT,
                        s.USU_OBSCON,
                        p.USU_FILEXE,
                        n.USU_DESNEG,
                        t.USU_DESTSV,
                        e.USU_DESETP,
                        p.USU_DATETP,
                        p.OBSPED,
                        (SELECT MAX(nomusu) KEEP (DENSE_RANK FIRST ORDER BY LENGTH(nomusu) DESC)
                            FROM sapiens.E099USU nu WHERE nu.codusu = s.usu_ususol) AS nome_solicitante,
                        (SELECT MAX(nomusu) KEEP (DENSE_RANK FIRST ORDER BY LENGTH(nomusu) DESC)
                            FROM sapiens.E099USU nu WHERE nu.codusu = s.usu_ususep) AS nome_separador,
                        (SELECT MAX(nomusu) KEEP (DENSE_RANK FIRST ORDER BY LENGTH(nomusu) DESC)
                            FROM sapiens.E099USU nu WHERE nu.codusu = s.usu_usucon) AS nome_retirado
                    FROM sapiens.usu_t120sdg s
                    JOIN sapiens.E120PED p ON p.codemp=s.usu_codemp
                    AND p.codfil= s.usu_codfil
                    AND p.numped= s.usu_numped
                    LEFT JOIN sapiens.usu_tunineg n ON p.usu_codneg= n.usu_codneg
                    LEFT JOIN sapiens.usu_ttipser t ON p.usu_codtsv= t.usu_codtsv
                    LEFT JOIN sapiens.usu_tetppro e ON p.usu_etpped= e.usu_codetp
                    WHERE s.usu_sitsol NOT IN (3,6,9)
                    AND s.usu_datsol >= sysdate-180
"""
# ORDER BY não fica aqui: get_solicitacoes() completa esta query com mais
# "AND ..." dependendo dos filtros escolhidos, e isso teria que vir depois
# do ORDER BY, o que é inválido em SQL. O ORDER BY é acrescentado só no
# final, depois de todos os filtros (ver get_solicitacoes).

def get_tipos_servico():
    """Lista (código, descrição) de usu_ttipser - para o filtro da tela de seleção."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT usu_codtsv, usu_destsv FROM sapiens.usu_ttipser ORDER BY usu_destsv")
    tipos = cur.fetchall()
    conn.close()
    return tipos

def get_etapas():
    """Lista (código, descrição) de usu_tetppro - para o filtro da tela de seleção."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT usu_codetp, usu_desetp FROM sapiens.usu_tetppro ORDER BY usu_desetp")
    etapas = cur.fetchall()
    conn.close()
    return etapas

def get_solicitacoes(empresa=None, filial=None, tipo_servico=None, etapa=None):
    """
    Retorna as solicitações já separadas por etapa (solicitado / em
    separação / atendido), prontas para o painel.
    """
    conn = get_connection()
    cur = conn.cursor()
    sql = SQL_SOLICITACOES
    binds = {}
    if empresa:
        sql += " and s.usu_codemp = :empresa"
        binds["empresa"] = int(empresa)
    if filial:
        sql += " and p.usu_filexe = :filial"
        binds["filial"] = filial
    if tipo_servico:
        sql += " and t.usu_codtsv = :tipo_servico"
        binds["tipo_servico"] = tipo_servico
    if etapa:
        sql += " and e.usu_codetp = :etapa"
        binds["etapa"] = int(etapa)

    sql += " ORDER BY s.usu_datsol"

    cur.execute(sql, **binds)
    cols = [c[0].lower() for c in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
    return _classificar_por_etapa(rows)

def _fmt_hora(valor):
    """
    Os campos USU_HORSOL/HORSEP/HORCON/HORENT guardam a hora como minutos
    desde a meia-noite (ex: 828 = 13:48, não 08:28 convertendo
    como HHMM, ~38% dos registros reais). 0/None = sem horário registrado ainda.
    """
    if not valor:
        return ""
    valor = int(valor)
    return f"{valor // 60:02d}:{valor % 60:02d}"


def _classificar_por_etapa(rows):
    """
    usu_sitsol: situação da solicitação.
      1, 2            -> Aberto / Aberto Parcial
      5               -> Em separação
      4               -> Atendido
    """
    solicitados, em_separacao, atendidos = [], [], []
    for r in rows:
        item = {
            "codemp": r["usu_codemp"], "codfil": r["usu_codfil"],
            "numped": r["usu_numped"], "numsol": r["usu_numsol"],
            "data_hora": f'{r["usu_datsol"]:%d/%m} {_fmt_hora(r["usu_horsol"])}'.strip(),
            "solicitante": r["nome_solicitante"] or r["usu_ususol"],
            "separador": r["nome_separador"] or r["usu_ususep"],
            "retirado_por": r["nome_retirado"] or r["usu_usucon"],
        }
        situacao = r["usu_sitsol"]
        if situacao in (1, 2):
            solicitados.append(item)
        elif situacao == 5:
            em_separacao.append(item)
        else:
            atendidos.append(item)
    return {"solicitados": solicitados, "em_separacao": em_separacao, "atendidos": atendidos}


# ---------------------------------------------------------------------
# Select dos itens de uma solicitação (para a segunda tela / detalhe)
# ---------------------------------------------------------------------
SQL_ITENS_SOLICITACAO = """
                SELECT i.usu_codpro,
                       a.usu_codpro2,
                       a.despro,
                       i.usu_despec,
                       a.codmar,
                       e.codend,
                       i.usu_qtdsol,
                       i.usu_qtdabe,
                       i.usu_qtdate,
                       i.usu_qtdcan,
                       i.usu_sitite,
                       i.usu_indamo,
                       i.usu_qtdmov
                FROM sapiens.usu_t120sit i
                JOIN sapiens.e120ped p ON p.codemp=i.usu_codemp
                AND p.codfil=i.usu_codfil
                AND p.numped=i.usu_numped
                JOIN sapiens.e210est e ON e.codemp=i.usu_codemp
                AND e.codpro=i.usu_codpro
                AND e.coddep = CASE WHEN p.codemp=1 AND p.usu_filexe='L' THEN '1'
                WHEN p.codemp=1 AND p.usu_filexe='P' THEN '3'
                WHEN p.codemp=1 AND p.usu_filexe='C' THEN '5' WHEN p.codemp in (5,12) THEN '1' END
                JOIN sapiens.e075pro a ON a.codemp=i.usu_codemp
                AND a.codpro=i.usu_codpro
                WHERE i.usu_codemp=:empsol
                AND i.usu_codfil=:filsol
                AND i.usu_numsol=:numsol
"""

# Select de saldo de estoque - duas variações (empresas 1/2/12 e a 5)
SQL_SALDO_ESTOQUE_PADRAO = """
            SELECT CASE WHEN e.codemp=2 AND e.coddep='1' THEN 'RTL LD'
                WHEN e.codemp=2 AND e.coddep='2' THEN 'RTL PP'
                WHEN e.codemp=1 AND e.coddep='1' THEN 'RET LD'
                WHEN e.codemp=1 AND e.coddep='3' THEN 'RET PP'
                WHEN e.codemp=1 AND e.coddep='5' THEN 'CRAF'
                WHEN e.codemp=12 AND e.coddep='1' THEN 'CAR' end as coddep,
                (e.qtdest-e.qtdres-e.qtdrae) AS sldest
            FROM sapiens.E210est e,sapiens.E075pro p
                WHERE e.codemp in (1,2,12) AND coddep in ('1','2','3','5')
                AND e.codpro=p.codpro
                AND e.codemp=p.codemp
                AND CASE WHEN p.codemp in (1,12) THEN p.codpro
                WHEN p.codemp=2 THEN p.usu_codpro2 END =:codproint
                AND NOT (e.coddep ='2'
                AND e.codemp in (1,12))
                AND NOT (e.coddep='3' and e.codemp=2)
"""

SQL_SALDO_ESTOQUE_TRANSMISSOES = """
select case when e.codemp=2 and e.coddep='1' then 'RTL LD'
            when e.codemp=2 and e.coddep='2' then 'RTL PP'
            when e.codemp=5 and e.coddep='1' then 'TRANS' end as coddep,
(e.qtdest-e.qtdres-e.qtdrae) as sldest from sapiens.E210est e,sapiens.E075pro p
where e.codemp in (2,5) AND coddep in ('1','2')
and e.codpro=p.codpro and e.codemp=p.codemp and case when p.codemp=2 then p.codpro when p.codemp=5 then p.usu_codpro2 end =:codprofab
and not (e.coddep='2' and e.codemp=5)
"""


SQL_CLIENTE_PEDIDO = """
                SELECT c.nomcli, c.cidcli, c.sigufs
                FROM sapiens.e120ped p
                JOIN sapiens.e085cli c ON c.codcli = p.codcli
                WHERE p.codemp = :codemp
                AND p.codfil = :codfil
                AND p.numped = :numped
"""


def get_solicitacao_cabecalho(codemp, codfil, numsol):
    """
    Cabeçalho básico da solicitação (numped, solicitante, separador, etc) -
    usado na segunda tela e na tela de "assumir solicitação".
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_SOLICITACOES + " and s.usu_codemp=:codemp and s.usu_codfil=:codfil and s.usu_numsol=:numsol",
                codemp=codemp, codfil=codfil, numsol=numsol)
    cols = [c[0].lower() for c in cur.description]
    cab_row = cur.fetchone()
    cab = dict(zip(cols, cab_row)) if cab_row else {}

    # Cliente/cidade vêm de uma consulta separada (E120PED.CODCLI -> E085CLI) -
    # usu_tunineg/USU_DESNEG (usado antes) é a Unidade de Negócio, não o cliente.
    cliente, cidade = "", ""
    if cab.get("usu_numped"):
        cur.execute(SQL_CLIENTE_PEDIDO, codemp=codemp, codfil=codfil, numped=cab["usu_numped"])
        cliente_row = cur.fetchone()
        if cliente_row:
            nomcli, cidcli, sigufs = cliente_row
            cliente = nomcli or ""
            cidade = f"{sigufs} - {cidcli}" if sigufs and cidcli else (cidcli or "")
    conn.close()

    return {
        "numped": cab.get("usu_numped"), "codfil": codfil, "numsol": numsol,
        "data_hora": f'{cab.get("usu_datsol"):%d/%m/%Y} {_fmt_hora(cab.get("usu_horsol"))}'.strip() if cab.get("usu_datsol") else "",
        "cliente": cliente,
        "cidade": cidade,
        "solicitante": cab.get("nome_solicitante") or cab.get("usu_ususol", ""),
        "separador": cab.get("nome_separador") or cab.get("usu_ususep", ""),
        "observacao": (cab.get("usu_obssol") or "").strip(),
        "memorando": (cab.get("usu_obscon") or "").strip(),
        "observacao_pedido": (cab.get("obsped") or "").strip(),
    }


def get_solicitacao_detalhe(codemp, codfil, numsol):
    """Cabeçalho + itens + saldo de estoque, para a segunda tela."""
    solicitacao = get_solicitacao_cabecalho(codemp, codfil, numsol)

    conn = get_connection()
    cur = conn.cursor()

    # itens da solicitação
    cur.execute(SQL_ITENS_SOLICITACAO, empsol=codemp, filsol=codfil, numsol=numsol)
    item_cols = [c[0].lower() for c in cur.description]
    itens_raw = [dict(zip(item_cols, row)) for row in cur.fetchall()]

    itens = []
    for row in itens_raw:
        codpro1 = row["usu_codpro"]
        codpro2 = row["usu_codpro2"]

        # código "interno" varia conforme a empresa (ver README, seção 1)
        if codemp in (1, 12):
            codproint, codprofab = codpro1, codpro2
        else:  # codemp == 2 (RTL)
            codproint, codprofab = codpro2, codpro1

        if codemp == 5:
            cur.execute(SQL_SALDO_ESTOQUE_TRANSMISSOES, codprofab=codprofab)
        else:
            cur.execute(SQL_SALDO_ESTOQUE_PADRAO, codproint=codproint)
        saldos = [{"deposito": dep, "saldo": int(sld)} for dep, sld in cur.fetchall()]

        itens.append({
            "codpro1": codpro1, "codpro2": codpro2,
            "descricao": row["despro"], "descricao_item": row["usu_despec"],
            "marca": row["codmar"], "endereco": row["codend"],
            "qtd_solic": row["usu_qtdsol"], "saldos": saldos,
        })

    conn.close()

    return {"solicitacao": solicitacao, "itens": itens}


# ---------------------------------------------------------------------
# Update quando a boqueta pega a solicitação (Solicitado -> Em separação)
# ---------------------------------------------------------------------
SQL_ASSUMIR_SOLICITACAO = """
                UPDATE sapiens.usu_t120sdg
                    SET usu_sitsol=5,
                    usu_datsep=:dataatual,
                    usu_horsep=:horaatual,
                    usu_ususep=:usucracha
                WHERE usu_codemp=:empsol
                AND usu_codfil=:filsol
                AND usu_numsol=:numsol
"""


def assumir_solicitacao(codemp, codfil, numsol, usuario_separador):
    conn = get_connection()
    cur = conn.cursor()
    agora = datetime.now()
    cur.execute(
        SQL_ASSUMIR_SOLICITACAO,
        dataatual=agora, horaatual=agora.strftime("%H:%M"),
        usucracha=usuario_separador, empsol=codemp, filsol=codfil, numsol=numsol,
    )
    conn.commit()
    conn.close()
    return True
