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


def _fmt_qtd(valor):
    """Quantidades vêm do Oracle como NUMBER (ex: 1.0) - exibir sem casas
    decimais quando o valor for inteiro (1, não 1.0)."""
    if valor is None:
        return 0
    return int(valor) if valor == int(valor) else valor


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
                SELECT i.usu_seqite,
                       i.usu_numped,
                       i.usu_seqipd,
                       i.usu_codpro,
                       a.usu_codpro2,
                       a.despro,
                       i.usu_despec,
                       a.codmar,
                       e.codend,
                       i.usu_qtdsol,
                       i.usu_qtdabe,
                       i.usu_qtdate,
                       i.usu_qtdcan,
                       i.usu_qtdmov,
                       i.usu_qtdmso,
                       i.usu_qtddev,
                       i.usu_sitite,
                       i.usu_indamo
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
                SELECT c.nomcli, c.cidcli, c.sigufs, r.codrep, r.nomrep
                FROM sapiens.e120ped p
                JOIN sapiens.e085cli c ON c.codcli = p.codcli
                LEFT JOIN sapiens.e090rep r ON r.codrep = p.codrep
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

    # Cliente/cidade/representante vêm de uma consulta separada
    # (E120PED.CODCLI -> E085CLI, E120PED.CODREP -> E090REP) - usu_tunineg/
    # USU_DESNEG (usado antes) é a Unidade de Negócio, não o cliente.
    cliente, cidade, representante = "", "", ""
    if cab.get("usu_numped"):
        cur.execute(SQL_CLIENTE_PEDIDO, codemp=codemp, codfil=codfil, numped=cab["usu_numped"])
        cliente_row = cur.fetchone()
        if cliente_row:
            nomcli, cidcli, sigufs, codrep, nomrep = cliente_row
            cliente = nomcli or ""
            cidade = f"{sigufs} - {cidcli}" if sigufs and cidcli else (cidcli or "")
            representante = f"{codrep} - {nomrep}" if codrep and nomrep else ""
    conn.close()

    return {
        "numped": cab.get("usu_numped"), "codfil": codfil, "numsol": numsol,
        "data_hora": f'{cab.get("usu_datsol"):%d/%m/%Y} {_fmt_hora(cab.get("usu_horsol"))}'.strip() if cab.get("usu_datsol") else "",
        "cliente": cliente,
        "cidade": cidade,
        "representante": representante,
        "solicitante": cab.get("nome_solicitante") or cab.get("usu_ususol", ""),
        "separador": cab.get("nome_separador") or cab.get("usu_ususep", ""),
        "observacao": (cab.get("usu_obssol") or "").strip(),
        "memorando": (cab.get("usu_obscon") or "").strip(),
        "observacao_pedido": (cab.get("obsped") or "").strip(),
    }


def _saldos_por_deposito(cur, codemp, codpro1, codpro2):
    """
    Saldo por depósito de um produto - código "interno" varia conforme a
    empresa (ver README, seção 1). Reaproveitado tanto pro item da
    solicitação quanto pros equivalentes (E075EQI).
    
    """
    if codemp in (1, 12):
        codproint, codprofab = codpro1, codpro2
    else:  # codemp == 2 (RTL)
        codproint, codprofab = codpro2, codpro1

    if codemp == 5:
        cur.execute(SQL_SALDO_ESTOQUE_TRANSMISSOES, codprofab=codprofab)
    else:
        cur.execute(SQL_SALDO_ESTOQUE_PADRAO, codproint=codproint)
    return [
        {"deposito": dep, "saldo": int(sld)}
        for dep, sld in cur.fetchall() if sld and int(sld) > 0
    ]


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
        saldos = _saldos_por_deposito(cur, codemp, codpro1, codpro2)

        itens.append({
            "seqite": row["usu_seqite"], "numped": row["usu_numped"], "seqipd": row["usu_seqipd"],
            "codpro1": codpro1, "codpro2": codpro2,
            "descricao": row["despro"], "descricao_item": row["usu_despec"],
            "marca": row["codmar"], "endereco": row["codend"],
            "qtd_solic": _fmt_qtd(row["usu_qtdsol"]),
            "qtd_aberta": _fmt_qtd(row["usu_qtdabe"]),
            "qtd_atendida": _fmt_qtd(row["usu_qtdate"]),
            "qtd_cancelada": _fmt_qtd(row["usu_qtdcan"]),
            "qtd_movimentada": _fmt_qtd(row["usu_qtdmov"]),
            "qtd_mso": _fmt_qtd(row["usu_qtdmso"]),
            "qtd_devolvida": _fmt_qtd(row["usu_qtddev"]),
            "saldos": saldos,
        })

    conn.close()

    return {"solicitacao": solicitacao, "itens": itens}


# ---------------------------------------------------------------------
# Busca de itens equivalentes (botão "Equivalentes" na segunda tela)
# Junta E075PRO (marca/descrição do produto equivalente) e E075DER
# (descrição da derivação) - preço (conpr1/conpr2) ainda não usado, a
# fonte de preço será definida depois.
# ---------------------------------------------------------------------
SQL_EQUIVALENTES = """
                SELECT eq.codder, 
                       eq.proeqi, 
                       eq.dereqi, 
                       eq.conpr1, 
                       eq.conpr2,
                       p.despro, 
                       p.codmar, 
                       p.usu_codpro2,
                       d.desder
                FROM sapiens.E075EQI eq
                JOIN sapiens.E075PRO p ON p.codemp = eq.codemp 
                                      AND p.codpro = eq.proeqi
                LEFT JOIN sapiens.E075DER d ON d.codemp = eq.codemp
                                      AND d.codpro = eq.proeqi 
                                      AND d.codder = eq.codder
                WHERE eq.codemp = :codemp
                AND eq.codpro = :codpro
"""


def get_equivalentes(codemp, codpro):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_EQUIVALENTES, codemp=codemp, codpro=codpro)
    cols = [c[0].lower() for c in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    equivalentes = []
    for row in rows:
        saldos = _saldos_por_deposito(cur, codemp, row["proeqi"], row["usu_codpro2"])
        equivalentes.append({
            "codigo": row["proeqi"],
            "descricao": (row["despro"] or row["dereqi"] or "").strip(),
            "marca": (row["codmar"] or "").strip() or None,
            "derivacao": (row["desder"] or "").strip() or None,
            "saldos": saldos,
        })
    conn.close()
    return equivalentes

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


# ---------------------------------------------------------------------
# Cancelar item na solicitação (botão "Cancelar" - só mexe na T120SIT,
# não chama o webservice do pedido)
# ---------------------------------------------------------------------
SQL_ITEM_SOLICITACAO_POR_SEQITE = """
                SELECT usu_qtdabe, usu_qtdcan, usu_numped, usu_seqipd, usu_codpro
                FROM sapiens.usu_t120sit
                WHERE usu_codemp=:codemp AND usu_codfil=:codfil
                AND usu_numsol=:numsol AND usu_seqite=:seqite
"""

SQL_CANCELAR_ITEM_SOLICITACAO = """
                UPDATE sapiens.usu_t120sit
                    SET usu_qtdabe = usu_qtdabe - :qtd,
                    usu_qtdcan = usu_qtdcan + :qtd
                WHERE usu_codemp=:codemp AND usu_codfil=:codfil
                AND usu_numsol=:numsol AND usu_seqite=:seqite
"""


def get_item_solicitacao(codemp, codfil, numsol, seqite):
    """Dados atuais de um item da solicitação pelo seqite (chave da T120SIT) -
    usado pra tela de confirmação de cancelamento (mostrar qtd aberta) e como
    base pros fluxos de troca/inserção."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_ITEM_SOLICITACAO_POR_SEQITE, codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite)
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    qtdabe, qtdcan, numped, seqipd, codpro = row
    return {
        "qtd_aberta": _fmt_qtd(qtdabe), "qtd_cancelada": _fmt_qtd(qtdcan),
        "numped": numped, "seqipd": seqipd, "codpro": codpro,
    }

def cancelar_item_solicitacao(codemp, codfil, numsol, seqite, qtd):
    """Cancela `qtd` unidades do item na solicitação (T120SIT) - move de
    qtd_aberta pra qtd_cancelada. Não mexe no pedido nem chama webservice."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        SQL_CANCELAR_ITEM_SOLICITACAO,
        qtd=qtd, codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
    )
    conn.commit()
    conn.close()
    return True

# ---------------------------------------------------------------------
# Observação do item (botão "Observação" - grava direto na T120SIT,
# substitui o antigo comentário local em SQLite). Depende da coluna
# usu_obsite existir na tabela (ver README) - se não existir, o Oracle
# levanta ORA-00904 e a rota trata isso com uma mensagem clara.
# ---------------------------------------------------------------------
SQL_SALVAR_OBSERVACAO_ITEM = """
                UPDATE sapiens.usu_t120sit
                    SET usu_obsite = :obs
                WHERE usu_codemp=:codemp AND usu_codfil=:codfil
                AND usu_numsol=:numsol AND usu_seqite=:seqite
"""

SQL_OBSERVACAO_ITEM = """
                SELECT usu_obsite FROM sapiens.usu_t120sit
                WHERE usu_codemp=:codemp AND usu_codfil=:codfil
                AND usu_numsol=:numsol AND usu_seqite=:seqite
"""


def get_observacao_item(codemp, codfil, numsol, seqite):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_OBSERVACAO_ITEM, codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite)
    row = cur.fetchone()
    conn.close()
    return (row[0] or "").strip() if row and row[0] else ""


def get_observacoes_solicitacao(codemp, codfil, numsol):
    """{seqite: observacao} de todos os itens da solicitação, pra destacar na
    listagem quais já têm observação - igual o antigo comentário local fazia.
    Levanta a mesma exceção do Oracle (ORA-00904) se usu_obsite ainda não
    existir; quem chama decide como tratar (ver detalhe_solicitacao em app.py)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT usu_seqite, usu_obsite FROM sapiens.usu_t120sit "
        "WHERE usu_codemp=:codemp AND usu_codfil=:codfil AND usu_numsol=:numsol",
        codemp=codemp, codfil=codfil, numsol=numsol,
    )
    rows = cur.fetchall()
    conn.close()
    return {seqite: obs.strip() for seqite, obs in rows if obs}


def salvar_observacao_item(codemp, codfil, numsol, seqite, observacao):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        SQL_SALVAR_OBSERVACAO_ITEM,
        obs=observacao.strip(), codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
    )
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------
# Validação de produto novo + preço (botões "Trocar" e "Inserir peça").
# Preço vem da E081ITP, registro vigente (situação ativa, data de início
# mais recente <= hoje). CODTAB (tabela de preço) tenta vir do pedido
# (E120PED.CODTAB), mas na prática esse campo está em branco (' ', não
# NULL) em quase todo pedido - confirmado por amostragem no Oracle
# (40524 de ~48000 pedidos recentes). Quando vier em branco/nulo, cai pro
# '001', que é a tabela ativa em ~99% dos produtos em todas as empresas.
# ---------------------------------------------------------------------
SQL_PRODUTO_ATIVO = """
                SELECT despro, codmar, sitpro FROM sapiens.e075pro
                WHERE codemp=:codemp AND codpro=:codpro
"""

SQL_PRECO_VIGENTE = """
                SELECT prebas FROM sapiens.e081itp
                WHERE codemp=:codemp AND codpro=:codpro AND codtpr=:codtpr
                AND sitreg='A' AND datini = (
                    SELECT MAX(datini) FROM sapiens.e081itp
                    WHERE codemp=:codemp AND codpro=:codpro AND codtpr=:codtpr
                    AND sitreg='A' AND datini <= SYSDATE
                )
"""

SQL_CODTAB_PEDIDO = "SELECT codtab FROM sapiens.e120ped WHERE codemp=:codemp AND codfil=:codfil AND numped=:numped"

CODTPR_PADRAO = "001"


def buscar_produto_preco(codemp, codfil, numped, codpro):
    """
    Valida o produto novo (E075PRO ativo) e busca o preço vigente (E081ITP)
    pela tabela de preço do pedido em questão. Retorna None se o produto não
    existir; retorna dict com preco=None se existir mas não tiver preço
    vigente cadastrado (a tela decide o que fazer nesse caso).
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(SQL_PRODUTO_ATIVO, codemp=codemp, codpro=codpro)
    prod_row = cur.fetchone()
    if not prod_row:
        conn.close()
        return None
    despro, codmar, sitpro = prod_row

    cur.execute(SQL_CODTAB_PEDIDO, codemp=codemp, codfil=codfil, numped=numped)
    codtab_row = cur.fetchone()
    codtab = (codtab_row[0] or "").strip() if codtab_row else ""
    codtab = codtab or CODTPR_PADRAO

    cur.execute(SQL_PRECO_VIGENTE, codemp=codemp, codpro=codpro, codtpr=codtab)
    preco_row = cur.fetchone()
    preco = float(preco_row[0]) if preco_row and preco_row[0] is not None else None

    conn.close()
    return {
        "codpro": codpro, "descricao": despro, "marca": (codmar or "").strip() or None,
        "ativo": sitpro == "A", "codtab": codtab, "preco": preco,
    }


# ---------------------------------------------------------------------
# Situação do item no pedido (E120IPD) - qtd aberta/cancelada/faturada,
# usado na tela de troca pra checar antes de trocar.
# ---------------------------------------------------------------------
SQL_ITEM_PEDIDO = """
                SELECT qtdped, qtdabe, qtdcan, qtdfat, preuni
                FROM sapiens.e120ipd
                WHERE codemp=:codemp AND codfil=:codfil AND numped=:numped AND seqipd=:seqipd
"""


def get_item_pedido(codemp, codfil, numped, seqipd):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_ITEM_PEDIDO, codemp=codemp, codfil=codfil, numped=numped, seqipd=seqipd)
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    qtdped, qtdabe, qtdcan, qtdfat, preuni = row
    return {
        "qtd_pedida": _fmt_qtd(qtdped), "qtd_aberta": _fmt_qtd(qtdabe),
        "qtd_cancelada": _fmt_qtd(qtdcan), "qtd_faturada": _fmt_qtd(qtdfat),
        "preco_unitario": float(preuni) if preuni is not None else None,
    }


# ---------------------------------------------------------------------
# Inserir item novo na solicitação (T120SIT) - usado por Inserir peça e
# pela segunda metade da Troca. usu_seqipd vem da resposta do webservice
# GravarPedidos (ver db/pedido_ws.py); usu_indtrc marca 'S' quando o item
# entrou por uma troca (pra diferenciar de uma inclusão simples).
# ---------------------------------------------------------------------
SQL_PROXIMO_SEQITE = """
                SELECT NVL(MAX(usu_seqite), 0) + 1 FROM sapiens.usu_t120sit
                WHERE usu_codemp=:codemp AND usu_codfil=:codfil AND usu_numsol=:numsol
"""

SQL_INSERIR_ITEM_SOLICITACAO = """
                INSERT INTO sapiens.usu_t120sit (
                    usu_codemp, usu_codfil, usu_numsol, usu_seqite,
                    usu_numped, usu_seqipd, usu_qtdsol, usu_qtdabe, usu_qtdcan,
                    usu_qtddev, usu_qtdmov, usu_qtdmso, usu_qtdate,
                    usu_codpro, usu_despec, usu_indtrc,
                    usu_datsol, usu_horsol, usu_ususol
                ) VALUES (
                    :codemp, :codfil, :numsol, :seqite,
                    :numped, :seqipd, :qtd, :qtd, 0,
                    0, 0, 0, 0,
                    :codpro, :descricao, :indtrc,
                    :data, :hora, :usuario
                )
"""


def inserir_item_solicitacao(codemp, codfil, numsol, numped, seqipd, codpro, descricao, qtd, usuario, veio_de_troca=False):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_PROXIMO_SEQITE, codemp=codemp, codfil=codfil, numsol=numsol)
    seqite = cur.fetchone()[0]

    agora = datetime.now()
    cur.execute(
        SQL_INSERIR_ITEM_SOLICITACAO,
        codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
        numped=numped, seqipd=seqipd, qtd=qtd,
        codpro=codpro, descricao=(descricao or "")[:250], indtrc=("S" if veio_de_troca else None),
        data=agora, hora=agora.hour * 60 + agora.minute, usuario=int(usuario),
    )
    conn.commit()
    conn.close()
    return seqite
