"""
Acesso ao Oracle (Sapiens). Querys estruturadas para o app Acompanha Pedido, toda a lÃ³gica de funcionamento dos botÃµes - Estoque RetÃ­fica.

"""

import os
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()  # Lê o arquivo .env na raiz do projeto (contendo ORACLE_DSN, ORACLE_USER, ORACLE_PASSWORD, FLASK_SECRET_KEY)

ORACLE_DSN = os.environ.get("ORACLE_DSN", "")
ORACLE_USER = os.environ.get("ORACLE_USER", "")
ORACLE_PASSWORD = os.environ.get("ORACLE_PASSWORD", "")
ORACLE_CLIENT_LIB_DIR = os.environ.get("ORACLE_CLIENT_LIB_DIR") or None

_oracle_client_iniciado = False

def get_connection():
    """
    Abre conexão Oracle em modo thick
    """
    global _oracle_client_iniciado
    import oracledb
    if not _oracle_client_iniciado:
        oracledb.init_oracle_client(lib_dir=ORACLE_CLIENT_LIB_DIR)
        _oracle_client_iniciado = True
    return oracledb.connect(
        user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=ORACLE_DSN
    )

# ---------------------------------------------------------------------
# Autenticação - identifica o usuário pelo código do Sapiens (por enquanto)
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
# Select das solicitações a serem exibidas na tela:
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
    """Lista (código, descrição) de usu_ttipser - para o filtro."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT usu_codtsv, usu_destsv FROM sapiens.usu_ttipser ORDER BY usu_destsv")
    tipos = cur.fetchall()
    conn.close()
    return tipos

def get_etapas():
    """Lista (código, descrição) de usu_tetppro - para o filtro."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT usu_codetp, usu_desetp FROM sapiens.usu_tetppro ORDER BY usu_desetp")
    etapas = cur.fetchall()
    conn.close()
    return etapas

def get_solicitacoes(empresa=None, filial=None, tipo_servico=None, etapa=None, numped=None, numsol=None):
    """
    Retorna as solicitação já separadas por etapa (solicitado / em
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
    if numped:
        sql += " and s.usu_numped = :numped"
        binds["numped"] = int(numped)
    if numsol:
        sql += " and s.usu_numsol = :numsol"
        binds["numsol"] = int(numsol)

    sql += " ORDER BY s.usu_datsol"

    cur.execute(sql, **binds)
    cols = [c[0].lower() for c in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
    return _classificar_por_etapa(rows)

def _fmt_hora(valor):
    """
    Os campos USU_HORSOL/HORSEP/HORCON/HORENT guardam a hora como minutos
    desde a meia-noite (ex: 828 = 13:48, nÃ£o 08:28 convertendo
    como HHMM, ~38% dos registros reais). 0/None = sem horário registrado ainda.

    """
    if not valor:
        return ""
    valor = int(valor)
    return f"{valor // 60:02d}:{valor % 60:02d}"


def _fmt_qtd(valor):
    if valor is None:
        return 0
    return int(valor) if valor == int(valor) else valor


def _classificar_por_etapa(rows):
    """
    usu_sitsol: situaÃ§Ã£o da solicitação.
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
# Select dos itens de uma solicitação (para a segunda tela / detalhe):
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
                       i.usu_indamo,
                       i.usu_obsite,
                       i.usu_numsco,
                       i.usu_datsol,
                       i.usu_horsol,
                       i.usu_ususol,
                       (SELECT MAX(nomusu) KEEP (DENSE_RANK FIRST ORDER BY LENGTH(nomusu) DESC)
                           FROM sapiens.E099USU nu WHERE nu.codusu = i.usu_ususol) AS nome_item_solicitante
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
                ORDER BY i.usu_sitite, i.usu_seqite
"""

# Select de saldo de estoque - duas variações (empresas 1/2/12 e a 5):
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
        "tipo_servico": (cab.get("usu_destsv") or "").strip(),
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
    """CabeÃ§alho + itens + saldo de estoque, para a segunda tela."""
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
        sitite = row["usu_sitite"]
        # Item já cancelado (3) ou atendido (4, 6) - não busca saldo de
        # estoque, fica de consulta na tela (botões de ações escondidos
        # no template):
        if sitite in (3, 4, 6):
            saldos = []
        else:
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
            "sitite": row["usu_sitite"],
            "tem_observacao": bool((row["usu_obsite"] or "").strip()),
            "observacao": (row["usu_obsite"] or "").strip(),
            "numsco": row["usu_numsco"],
            "data_hora_item": (
                f'{row["usu_datsol"]:%d/%m/%Y} {_fmt_hora(row["usu_horsol"])}'.strip()
                if row.get("usu_datsol") else ""
            ),
            "solicitante_item": row["nome_item_solicitante"] or row["usu_ususol"],
            "saldos": saldos,
        })

    conn.close()

    return {"solicitacao": solicitacao, "itens": itens}

# ---------------------------------------------------------------------
# Busca de itens equivalentes (botão "Equivalentes" na segunda tela)
# Junta E075PRO (marca/descrição do produto equivalente) e E075DER
# (descrição da derivação) - preço (conpr1/conpr2) ainda não usado.
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
                       d.desder,
                       t.prebas
                FROM sapiens.E075EQI eq
                JOIN sapiens.E075PRO p ON p.codemp = eq.codemp
                                      AND p.codpro = eq.proeqi
                LEFT JOIN sapiens.E075DER d ON d.codemp = eq.codemp
                                      AND d.codpro = eq.proeqi
                                      AND d.codder = eq.codder
                LEFT JOIN sapiens.E081ITP t ON t.codemp = p.codemp
                                           AND t.codtpr = '001'
                                           AND t.codpro = p.codpro
                                           AND t.qtdmax = 999999999
                                           AND t.datini = CASE WHEN p.codemp=1 then TO_DATE('01/04/2011','DD/MM/YYYY')
                                                               WHEN p.codemp=12 then TO_DATE('01/01/2023','DD/MM/YYYY')
                                                               WHEN p.codemp=5 then TO_DATE('01/04/2014','DD/MM/YYYY') END
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
            "profor": (row["usu_codpro2"] or "").strip() or None,
            "descricao": (row["despro"] or row["dereqi"] or "").strip(),
            "marca": (row["codmar"] or "").strip() or None,
            "derivacao": (row["desder"] or "").strip() or None,
            "preco": float(row["prebas"]) if row["prebas"] is not None else None,
            "saldos": saldos,
        })
    conn.close()
    return equivalentes

# ---------------------------------------------------------------------
# Update quando a boqueta pega a solicitação (Solicitado -> Em sepração)
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
        dataatual=agora, horaatual=agora.hour * 60 + agora.minute,
        usucracha=usuario_separador, empsol=codemp, filsol=codfil, numsol=numsol,
    )
    conn.commit()
    conn.close()
    return True

# ---------------------------------------------------------------------
# Cancelar item na solicitação (botão "Cancelar" - não mexe na T120SIT,
# não chama o webservice do pedido)
# ---------------------------------------------------------------------
SQL_ITEM_SOLICITACAO_POR_SEQITE = """

                SELECT usu_qtdabe, usu_qtdcan, usu_numped, usu_seqipd, usu_codpro
                FROM sapiens.usu_t120sit
                    WHERE usu_codemp=:codemp 
                    AND usu_codfil=:codfil
                    AND usu_numsol=:numsol 
                    AND usu_seqite=:seqite

"""

SQL_ITEM_MOVIMENTACAO = """
                SELECT usu_qtdmov FROM sapiens.usu_t120sit
                WHERE usu_codemp=:codemp AND usu_codfil=:codfil
                AND usu_numsol=:numsol AND usu_seqite=:seqite
"""

# Sem movimentação (usu_qtdmov = 0): cancela o item inteiro de uma vez.
SQL_CANCELAR_ITEM_SOLICITACAO_TOTAL = """
                UPDATE sapiens.usu_t120sit
                    SET usu_sitite = 3,
                        usu_qtdcan = usu_qtdsol,
                        usu_qtdate = 0,
                        usu_qtdabe = 0,
                        usu_obsite = :msgcan
                WHERE usu_codemp=:codemp AND usu_codfil=:codfil
                AND usu_numsol=:numsol AND usu_seqite=:seqite
"""

# Com movimentação (usu_qtdmov <> 0): cancela o que ainda está aberto,
# preserva usu_qtdate (não apaga o que já foi atendido/movimentado).

SQL_CANCELAR_ITEM_SOLICITACAO_QTD_ABERTA = """
                UPDATE sapiens.usu_t120sit
                    SET usu_qtdcan = usu_qtdcan + usu_qtdabe,
                        usu_sitite = CASE WHEN usu_qtdsol = usu_qtdcan + usu_qtdabe THEN 3 ELSE 2 END,
                        usu_qtdabe = 0,
                        usu_obsite = :msgcan
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

def cancelar_item_solicitacao(codemp, codfil, numsol, seqite, usuario, motivo=None):
    """Cancela o item na solicitação (T120SIT) - não mexe no pedido nem
    chama webservice. A usu_obsite recebe uma mensagem gerada com
    data/hora/usuário/motivo - CONCATENA com o texto anterior (não
    sobrescreve, mesmo padrão da Observação de item). Dois caminhos,
    decididos pela usu_qtdmov atual do item:
      - SEM movimentação (usu_qtdmov=0): cancela o item inteiro de uma vez
        (usu_sitite=3, usu_qtdcan=usu_qtdsol, zera usu_qtdate/usu_qtdabe).
      - COM movimentação (usu_qtdmov<>0): cancela o que ainda está
        aberto, preserva usu_qtdate (não apaga o que já foi
        atendido/movimentado).
    Usada pelo botão "Cancelar" - a Troca de item usa
    cancelar_qtd_item_solicitacao_troca (abaixo), que cancela a
    quantidade trocada, podendo deixar o resto do item em aberto."""
    motivo_txt = (motivo or "").strip() or "sem motivo"
    linha_nova = f"{usuario}: cancelado - {motivo_txt}"
    anterior = get_observacao_item(codemp, codfil, numsol, seqite)
    msgcan = f"{anterior}\n{linha_nova}" if anterior else linha_nova

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_ITEM_MOVIMENTACAO, codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite)
    row = cur.fetchone()
    tem_movimentacao = bool(row and row[0])

    sql = SQL_CANCELAR_ITEM_SOLICITACAO_QTD_ABERTA if tem_movimentacao else SQL_CANCELAR_ITEM_SOLICITACAO_TOTAL
    cur.execute(sql, msgcan=msgcan, codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite)
    conn.commit()
    conn.close()
    return True

# ---------------------------------------------------------------------
# Cancelamento PARCIAL do item substituido numa Troca - diferente do botão
# Cancelar (que sempre cancela o item inteiro): aqui a quantidade que
# está sendo trocada e cancelada (ex: 3 unidades solicitadas, troca são 1,
# as outras 2 continuam em aberto no item original). 3 UPDATEs em
# sequência, sempre filtrando pelo item (usu_seqite), nunca a solicitação
# inteira:
#  1) soma qtd em qtdcan / subtrai de qtdabe, marca sitite=2 (parcial);
#  2) se qtdcan bateu com qtdsol (cancelou tudo que sobrava), sitite vira
#     3 (cancelado);
#  3) se ainda sobrou qtdsol > qtdcan, garante sitite=2 (parcial).
# Passos 2 e 3 sÃ£o mutuamente exclusivos pela condição de quantidade; todos
# ignoram item já com sitite=3. NÃ£o mexe em usu_obsite (a Troca não coleta
# motivo pra esse passo).
# ---------------------------------------------------------------------
SQL_CANCELAR_QTD_ITEM_TROCA = """
                UPDATE sapiens.usu_t120sit
                    SET usu_qtdcan = usu_qtdcan + :qtd,
                        usu_qtdabe = usu_qtdabe - :qtd,
                        usu_sitite = 2
                WHERE usu_codemp=:codemp AND usu_codfil=:codfil
                AND usu_numsol=:numsol AND usu_seqite=:seqite
                AND usu_sitite <> 3
                AND usu_qtdabe >= :qtd
"""

SQL_CANCELAR_QTD_ITEM_TROCA_TOTAL_SE_COMPLETO = """
                UPDATE sapiens.usu_t120sit
                    SET usu_sitite = 3
                WHERE usu_codemp=:codemp AND usu_codfil=:codfil
                AND usu_numsol=:numsol AND usu_seqite=:seqite
                AND usu_qtdsol = usu_qtdcan
                AND usu_sitite <> 3
"""

SQL_CANCELAR_QTD_ITEM_TROCA_PARCIAL_SE_SOBROU = """
                UPDATE sapiens.usu_t120sit
                    SET usu_sitite = 2
                WHERE usu_codemp=:codemp AND usu_codfil=:codfil
                AND usu_numsol=:numsol AND usu_seqite=:seqite
                AND usu_qtdsol > usu_qtdcan
                AND usu_sitite <> 3
"""

def cancelar_qtd_item_solicitacao_troca(codemp, codfil, numsol, seqite, qtd):
    """Cancela a `qtd` unidades do item substituí­do (usado pela Troca) -
    pode deixar o resto do item em aberto se a troca for parcial. Não mexe
    no pedido nem chama webservice, nÃ£o mexe em usu_obsite.

    IMPORTANTE: o webservice do Sapiens (GravarPedidos_15)
    atualizava usu_qtdcan sozinho, por conta própria, duplicando com o que
    a função também fazia (usu_qtdcan ficava com o dobro da quantidade
    trocada). Isso foi corrigido do lado do Sapiens -
    agora usu_qtdcan volta a ser 100% responsabilidade desta função, o
    Sapiens não mexe mais nele. Trava usu_qtdabe >= :qtd impede descontar
    mais do que está aberto."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        SQL_CANCELAR_QTD_ITEM_TROCA,
        qtd=qtd, codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
    )
    cur.execute(
        SQL_CANCELAR_QTD_ITEM_TROCA_TOTAL_SE_COMPLETO,
        codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
    )
    cur.execute(
        SQL_CANCELAR_QTD_ITEM_TROCA_PARCIAL_SE_SOBROU,
        codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
    )
    conn.commit()
    conn.close()
    return True

# ---------------------------------------------------------------------
# Observação do item (botão "Observação" - grava direto na T120SIT.
# ---------------------------------------------------------------------
SQL_SALVAR_OBSERVACAO_ITEM = """
                UPDATE sapiens.usu_t120sit
                    SET usu_obsite = :obs
                WHERE usu_codemp=:codemp 
                AND usu_codfil=:codfil
                AND usu_numsol=:numsol 
                AND usu_seqite=:seqite
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


def salvar_observacao_item(codemp, codfil, numsol, seqite, texto_novo):
    """Concatena `texto_novo` com o que já existir em usu_obsite - NUNCA
    sobrescreve o texto anterior. `texto_novo` já deve vir formatado pelo
    chamador (ex: com data/hora/usuÃ¡rio na frente)."""
    anterior = get_observacao_item(codemp, codfil, numsol, seqite)
    texto_final = f"{anterior}\n{texto_novo.strip()}" if anterior else texto_novo.strip()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        SQL_SALVAR_OBSERVACAO_ITEM,
        obs=texto_final, codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
    )
    conn.commit()
    conn.close()
    return True

# ---------------------------------------------------------------------
# Validações de produto novo + preço (botões "Trocar" e "Inserir peças").
# preço vem da E081ITP, registro vigente (situação ativa, data de inicio
# mais recente <= hoje). CODTAB (tabela de preço) tenta vir do pedido
# (E120PED.CODTAB), mas na prática esse campo está em branco (' ', nÃ£o
# NULL) em quase todo pedido - confirmado por amostragem no Oracle
# (40524 de ~48000 pedidos recentes). Quando vier em branco/nulo, cai pro
# '001', que é a tabela ativa em ~99% dos produtos em todas as empresas.
# ---------------------------------------------------------------------
CODTPR_PADRAO = "001"

SQL_PRODUTO_ATIVO_PRECO = """
                SELECT t.codpro,t.prebas,e.coddep,a.qtdabe,a.qtdped, p.codmar, p.despro, a.seqipd 
                FROM sapiens.e075pro p
                LEFT JOIN sapiens.e081itp t ON t.codemp=p.codemp 
                    AND t.codtpr='001' 
                    AND t.qtdmax=999999999 
                    AND t.datini = CASE WHEN p.codemp=1 THEN TO_DATE('01/04/2011','DD/MM/YYYY') WHEN p.codemp=12 THEN TO_DATE('01/01/2023','DD/MM/YYYY') WHEN p.codemp=5 THEN TO_DATE('01/04/2014','DD/MM/YYYY') WHEN p.codemp=2 THEN TO_DATE('31/03/2011','DD/MM/YYYY') END
                    AND t.codpro = p.codpro
                LEFT JOIN sapiens.e210est e ON e.codemp=p.codemp 
                    AND e.codpro=p.codpro AND e.coddep = CASE WHEN p.codemp=1 
                    AND :filsol in (10,1001) THEN '3' ELSE '1' end
                LEFT JOIN sapiens.e120ipd a ON a.codemp=p.codemp 
                    AND a.codfil=:filsol 
                    AND a.codpro=p.codpro 
                    AND a.sitipd <> 5
                    AND a.numped = :numped
                WHERE p.sitpro='A' 
                    AND t.sitreg='A' 
                    AND p.codemp=:empsol 
                    AND (TO_CHAR(p.codpro)=:pronew OR p.usu_codpro2=:pronew)
"""

def buscar_produto_preco(codemp, codfil, numped, codpro):
    """
    Valida o produto novo (E075PRO ativo) e busca o preço vigente (E081ITP,
    codtpr fixo '001') numa consulta são (SQL_PRODUTO_ATIVO_PRECO). Retorna
    None se o produto não existir/estiver inativo (já filtrado no WHERE);
    retorna dict com preco=None se existir mas não tiver preço vigente
    cadastrado (a tela decide o que fazer nesse caso).

    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(SQL_PRODUTO_ATIVO_PRECO, empsol=codemp, filsol=codfil, pronew=codpro, numped=numped)
    prod_row = cur.fetchone()
    conn.close()
    if not prod_row:
        return None
    codpro_enc, prebas, _coddep, _qtdabe, _qtdped, codmar, despro, _seqipd = prod_row

    preco = float(prebas) if prebas is not None else None
    return {
        "codpro": codpro_enc, "descricao": despro, "marca": (codmar or "").strip() or None,
        "ativo": True, "codtab": CODTPR_PADRAO, "preco": preco,
    }

SQL_FILIAL_PEDIDO = "SELECT usu_filexe FROM sapiens.e120ped " \
    "                   WHERE codemp=:codemp " \
    "                   AND codfil=:codfil " \
    "                   AND numped=:numped"

SQL_DEPOSITO_LIGADO_PRODUTO = """
                SELECT MAX(e.coddep)
                FROM sapiens.e210est e
                JOIN sapiens.e075pro p ON p.codemp = e.codemp 
                AND p.codpro = e.codpro
                WHERE e.codemp = :codemp
                AND (TO_CHAR(p.codpro) = :codpro OR p.usu_codpro2 = :codpro)
                AND e.coddep = :coddep_esperado
"""

def _coddep_esperado(codemp, filexe):
    filexe = (filexe or "").strip().upper()
    if codemp == 1:
        return {"L": "1", "P": "3", "C": "5"}.get(filexe)
    if codemp == 2:
        return {"L": "1", "P": "2"}.get(filexe)
    if codemp in (5, 12):
        return "1"
    return None

def get_coddep_esperado(codemp, filexe):
    """Versão pública de _coddep_esperado - reaproveitada pela Solicitação
    de compra (o depósito de destino é o mesmo depósito ligado à empresa/
    filial da solicitação original)."""
    return _coddep_esperado(codemp, filexe)

def produto_tem_ligacao_deposito(codemp, codfil, numped, codpro):
    """True se o produto tiver linha em E210EST no depósito ligado á filial
    do pedido (coddep nulo/0 ou sem linha = sem ligação)."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(SQL_FILIAL_PEDIDO, codemp=codemp, codfil=codfil, numped=numped)
    filial_row = cur.fetchone()
    filexe = (filial_row[0] or "").strip() if filial_row else ""
    coddep_esperado = _coddep_esperado(codemp, filexe)
    if not coddep_esperado:
        conn.close()
        return False

    cur.execute(SQL_DEPOSITO_LIGADO_PRODUTO, codemp=codemp, codpro=codpro, coddep_esperado=coddep_esperado)
    coddep_row = cur.fetchone()
    conn.close()
    coddep = coddep_row[0] if coddep_row else None
    return bool(coddep) and str(coddep).strip() not in ("", "0")

# ---------------------------------------------------------------------
# Situação do item no pedido (E120IPD) - qtd aberta/cancelada/faturada,
# usado na tela de troca pra checar antes de trocar.
# ---------------------------------------------------------------------
SQL_ITEM_PEDIDO = """
                SELECT qtdped, qtdabe, qtdcan, qtdfat, preuni
                FROM sapiens.e120ipd
                    WHERE codemp=:codemp 
                    AND codfil=:codfil 
                    AND numped=:numped 
                    AND seqipd=:seqipd
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
# Checa se o produto já está no pedido (botÃ£o "Inserir peça") - evita
# incluir o mesmo produto duas vezes no mesmo pedido. Ignora linhas já
# canceladas (sitipd=5, mesma regra usada no JOIN de SQL_PRODUTO_ATIVO_PRECO).
# ---------------------------------------------------------------------
SQL_PRODUTO_JA_NO_PEDIDO = """
                SELECT COUNT(*) FROM sapiens.e120ipd
                WHERE codemp=:codemp AND codfil=:codfil AND numped=:numped
                AND codpro=:codpro AND sitipd <> 5
"""

def produto_ja_esta_no_pedido(codemp, codfil, numped, codpro):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_PRODUTO_JA_NO_PEDIDO, codemp=codemp, codfil=codfil, numped=numped, codpro=codpro)
    count = cur.fetchone()[0]
    conn.close()
    return count > 0

# ---------------------------------------------------------------------
# Inserir item novo na solicitação (T120SIT) - usado por Inserir peça e
# pela segunda metade da Troca. usu_seqipd vem da resposta do webservice
# GravarPedidos (ver db/pedido_ws.py). usu_sitite entra fixo em 1 (aberto).
# ---------------------------------------------------------------------
SQL_PROXIMO_SEQITE = """
                SELECT NVL(MAX(usu_seqite), 0) + 1 
                FROM sapiens.usu_t120sit
                    WHERE usu_codemp=:codemp 
                    AND usu_codfil=:codfil 
                    AND usu_numsol=:numsol
"""

SQL_INSERIR_ITEM_SOLICITACAO = """
                INSERT INTO sapiens.usu_t120sit (
                    usu_codemp, usu_codfil, usu_numsol, usu_seqite,
                    usu_numped, usu_seqipd, usu_qtdsol, usu_sitite,
                    usu_qtdabe, usu_qtdcan,
                    usu_qtddev, usu_qtdmov, usu_qtdate,
                    usu_codpro, usu_despec,
                    usu_datsol, usu_horsol, usu_ususol
                ) VALUES (
                    :codemp, :codfil, :numsol, :seqite,
                    :numped, :seqipd, :qtd, 1,
                    :qtd, 0, 0, 0, 0,
                    :codpro, :descricao,
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
        codpro=codpro, descricao=(descricao or "")[:250],
        data=agora, hora=agora.hour * 60 + agora.minute, usuario=int(usuario),
    )

    conn.commit()
    conn.close()
    return seqite

# ---------------------------------------------------------------------
# NOVO - Lógica de Pedido na loja (RTL, empresa 2) e solicitação de compra
# Regras fixas baseadas em cada empresa, filial e depósito, para decidir 
# para onde vai cada pedido de compra na loja. 
# ---------------------------------------------------------------------

def dados_pedido_loja(codemp, filexe):
    """Codcli/codemp_loja/codfil_loja/coddep_loja fixos para pedidos 
    de loja (empresa 2, RTL). Conforma a empresa/filial da solicitação original.
    Cambé utiliza o mesmo de Londrina"""

    filexe = (filexe or "").strip().upper()
    if codemp == 1:
        #FilExe = P
        if filexe == "P":
            return {"codcli": 990110572, "codemp_loja": 2,
                    "codfil_loja": 2, "coddep_loja": "2", "EmpOcp":"1", "FilOcp": "10", "DepOcp": "3"}
        #Filexe = L
        if filexe == "L":
            return {"codcli": 1, "codemp_loja": 2,
                "codfil_loja": 1, "coddep_loja": "1", "EmpOcp": 1, "FilOcp": 1,"DepOcp":"1"}
        
        #Filexe = C
        if filexe == "C":
            return {"codcli": 1, "codemp_loja": 2,
                    "codfil_loja": 1, "coddep_loja": "1", "EmpOcp": 1, "FilOcp": 1,"DepOcp": "5"}
    #Empresa = 5
    if codemp == 5:
        return {"codcli": 990108064, "codemp_loja": 2, "codfil_loja": 1, "coddep_loja": "1", "EmpOcp": 5, "FilOcp": 1,"DepOcp":"1"}
    
    #Empresa = 12
    if codemp == 12:
        return {"codcli": 990143288, "codemp_loja": 2, "codfil_loja": 1, "coddep_loja": "1","EmpOcp": 12, "FilOcp": 1,"DepOcp":"1"}
    return None

def get_filial_pedido(codemp, codfil, numped):
        """Usu_filexe do pedido (E120PED) - mesma leitura usada em produto_tem_ligacao_deposito que já está
            exposta como função própria para ser reaproveitada pelos botões.
        """
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(SQL_FILIAL_PEDIDO, codemp=codemp, codfil=codfil, numped=numped)
        row = cur.fetchone()
        conn.close()
        return (row[0] or "").strip() if row else ""

SQL_QTD_DEPOSITO = """
                SELECT (e.qtdest - e.qtdres - e.qtdrae) AS sldest
                FROM sapiens.e210est e
                WHERE e.codemp = :codemp
                AND e.coddep = :coddep
                AND e.codpro = :codpro
"""

def get_qtd_deposito(codemp, coddep, codpro):
    """
        Quantidade disponível no depósito (E210EST) - Usado para comparar com a qtdabe do item 
        sugerir quantidade nos botÃµes novos.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_QTD_DEPOSITO, codemp=codemp, coddep=coddep, codpro=codpro)
    row = cur.fetchone()
    conn.close()
    return _fmt_qtd(row[0]) if row and row[0] is not None else 0

SQL_SOMAR_QTDMSO_ITEM = """
                UPDATE sapiens.usu_t120sit
                    SET usu_qtdmso = NVL(usu_qtdmso, 0) + :qtd
                    WHERE usu_codemp=:codemp 
                    AND usu_codfil=:codfil
                    AND usu_numsol=:numsol 
                    AND usu_seqite=:seqite
"""

def somar_qtd_mso_item(codemp, codfil, numsol, seqite, qtd):
    """
        Incrementa usu_qtdmso depois que o pedido na loja OU a solicitação de
        compra forem confirmados com sucesso - registra que essa qtd já foi
        pedida, pra não sugerir de novo da próxima vez.

    """
    conn = get_connection()
    cur = conn.cursor() 
    cur.execute(
        SQL_SOMAR_QTDMSO_ITEM,
        qtd=qtd, codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
    )
    conn.commit()
    conn.close()
    return True

SQL_PROXIMO_NUMSOL_COMPRA = """
                SELECT NVL(MAX(numsol), 0) + 1 FROM sapiens.E405SOL
                WHERE codemp=:codemp
                """

def proximo_numsol_compra(codemp):

    """" Próximo número de solicitações de compra (E405SOL) 
         usado pra gerar o próximo número de 
         solicitação de compra na loja, feito antes de montar o envelope de solicitação de compra. 
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_PROXIMO_NUMSOL_COMPRA, codemp=codemp)
    numsol = cur.fetchone()[0]
    conn.close()
    return numsol

SQL_SALVAR_NUMSCO_ITEM = """
                UPDATE sapiens.usu_t120sit
                    SET usu_numsco = :numsco
                    WHERE usu_codemp=:codemp 
                    AND usu_codfil=:codfil
                    AND usu_numsol=:numsol 
                    AND usu_seqite=:seqite

"""

def salvar_numsco_item(codemp, codfil, numsol, seqite, numsco):
    """
        Salva o número da solicitação de compra (E405SOL) no item da solicitação
        (T120SIT) - usado depois que a solicitação de compra foi gerada com sucesso,
        pra registrar que esse item já foi pedido, e não sugerir de novo na próxima vez.

    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        SQL_SALVAR_NUMSCO_ITEM,
        numsco=numsco, codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
    )

    conn.commit()
    conn.close()
    return True

# ---------------------------------------------------------------------
# Conferência com reserva - campo de código de barras/produto + qtd
# (qtdcon). Resolve o código digitado pro codpro (3 fontes, nessa ordem:
# derivação, código de barras, código direto), acha o item em aberto na
# solicitação que bate com esse produto, e - se a qtd conferida couber na
# qtd aberta - grava o atendimento + reserva estoque/pedido.
# ---------------------------------------------------------------------

SQL_CODPRO_POR_DERIVACAO = """
                SELECT codpro FROM sapiens.E075DER
                    WHERE codemp = :codemp
                    AND CodBa2 = :codbar
                    AND sitder = 'A'
"""

SQL_CODPRO_POR_BARRAS = """
                SELECT codpro FROM sapiens.E075BAR 
                    WHERE codemp = :codemp
                    AND codbar = :codbar               
"""

SQL_CODPRO_POR_CODIGO = """
                SELECT codpro FROM sapiens.E075PRO
                    WHERE codemp = :codemp
                    AND (codpro = :codbar OR usu_codpro2 = :codbar)
                    AND sitpro = 'A'
                    AND codori IN ('40', '50', '60')
"""

def resolver_codpro_conferencia(codemp, codbar):
    """
    Resolve o texto digitado/escaneado (código de barras OU código de
    produto) pro codpro interno - tenta as 3 fontes em ordem, usa a
    primeira que encontrar.

    """
    conn = get_connection()
    cur = conn.cursor()
    for sql in (SQL_CODPRO_POR_DERIVACAO, SQL_CODPRO_POR_BARRAS, SQL_CODPRO_POR_CODIGO):
        cur.execute(sql, codemp=codemp, codbar=codbar)
        row = cur.fetchone()
        if row:
            conn.close()
            return row[0]
    conn.close()
    return None

SQL_ITEM_PARA_CONFERENCIA = """
                    SELECT usu_seqite, usu_qtdabe, usu_seqipd, usu_numped
                    FROM sapiens.USU_T120SIT
                    WHERE usu_codemp = :codemp
                    AND usu_codfil = :codfil
                    AND usu_numsol = :numsol
                    AND usu_codpro = :codpro
                    AND usu_sitite IN (1,2)
                    AND (usu_qtdate < usu_qtdsol OR usu_qtdate = 0 OR usu_qtdate IS NULL)
"""

def get_item_para_conferencia(codemp, codfil, numsol, codpro):
    """Item em aberto da solicitação que bate com esse codpro - None se
    não achar (produto não faz parte dessa solicitação, ou já foi
    totalmente atendido/cancelado)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_ITEM_PARA_CONFERENCIA, codemp=codemp, codfil=codfil, numsol=numsol, codpro=codpro)
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    seqite, qtdabe, seqipd, numped = row
    return {
        "seqite": seqite, "qtd_aberta": _fmt_qtd(qtdabe),
        "seqipd": seqipd, "numped": numped,
    }

SQL_CONFERIR_ITEM_SOLICITACAO = """
                UPDATE sapiens.USU_T120SIT
                    SET usu_qtdate = usu_qtdate + :qtdcon,
                        usu_qtdabe = usu_qtdabe - :qtdcon
                WHERE usu_codemp=:codemp 
                AND usu_codfil=:codfil
                AND usu_numsol=:numsol
                AND usu_seqite=:seqite
"""

SQL_RESERVAR_ESTOQUE = """
                UPDATE sapiens.E210EST
                    SET qtdres = qtdres + :qtdcon
                WHERE codemp = :codemp
                AND coddep = :coddep
                AND codpro = :codpro
"""

SQL_RESERVAR_ITEM_PEDIDO = """
                UPDATE sapiens.E120IPD
                    SET qtdres = qtdres + :qtdcon, resest = 'S'
                WHERE codemp = :codemp
                AND codfil = :codfil
                AND numped = :numped
                AND seqipd = :seqipd
"""

def conferir_item_com_reserva(codemp, codfil, numsol, item, coddep, qtdcon):
    """3 UPDATEs em sequência - `item` é o dict que get_item_para_conferencia
    devolveu (seqite/seqipd/numped já vêm de lá)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        SQL_CONFERIR_ITEM_SOLICITACAO,
        qtdcon=qtdcon, codemp=codemp, codfil=codfil, numsol=numsol, seqite=item["seqite"],
    )
    cur.execute(
        SQL_RESERVAR_ESTOQUE,
        qtdcon=qtdcon, codemp=codemp, coddep=coddep, codpro=item.get("codpro"),
    )
    cur.execute(
        SQL_RESERVAR_ITEM_PEDIDO,
        qtdcon=qtdcon, codemp=codemp, codfil=codfil, numped=item["numped"], seqipd=item["seqipd"],
    )
    conn.commit()
    conn.close()
    return True

SQL_FORNECEDOR_FILIAL = """
                    SELECT filfor FROM sapiens.E070FIL
                            WHERE codemp = :codemp
                            AND codfil = :codfil
"""

def get_codfor_filial(codemp, codfil):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_FORNECEDOR_FILIAL, codemp=codemp, codfil=codfil)
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

# ---------------------------------------------------------------------
# Ordem de Compra - UPDATEs após sucesso
# ---------------------------------------------------------------------

SQL_UPDATE_PEDIDO_OC = """
                UPDATE sapiens.E120PED
                    SET obsped = :obs_oc
                    WHERE codemp = :codemp
                    AND codfil = :codfil
                    AND numped = :numped
"""

def atualizar_pedido_com_oc(codemp, codfil, numped, numocp):
    """Marca o pedido (E120PED) com o número da ordem de compra gerada."""
    conn = get_connection()
    cur = conn.cursor()
    obs_oc = f"Ordem de compra {numocp}"
    cur.execute(SQL_UPDATE_PEDIDO_OC, {"obs_oc": obs_oc, "codemp": codemp, "codfil": codfil, "numped": numped})
    conn.commit()
    conn.close()

SQL_UPDATE_ITEM_SOLICITACAO_OC = """
                UPDATE sapiens.USU_T120SIT
                    SET usu_obsite = :obs_item
                    WHERE usu_codemp = :codemp
                    AND usu_codfil = :codfil
                    AND usu_numsol = :numsol
                    AND usu_seqite IN ({})
"""

def atualizar_itens_solicitacao_com_oc(codemp, codfil, numsol, seqites):
    """Marca os itens da solicitação (USU_T120SIT) com observação de OC gerada."""
    if not seqites:
        return
    conn = get_connection()
    cur = conn.cursor()
    placeholders = ",".join([f":{i}" for i in range(len(seqites))])
    sql = SQL_UPDATE_ITEM_SOLICITACAO_OC.format(placeholders)
    params = {"codemp": codemp, "codfil": codfil, "numsol": numsol, "obs_item": f"Solicitação {numsol} - Pedido"}
    for i, seqite in enumerate(seqites):
        params[str(i)] = seqite
    cur.execute(sql, params)
    conn.commit()
    conn.close()