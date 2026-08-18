"""
Cliente do webservice GravarPedidos (Sapiens/Senior) - usado só pelos fluxos de
Troca e Inserção de peça, pra cancelar/incluir item no PEDIDO (E120IPD). A
solicitação (T120SIT) é gravada à parte por meio de UPDATE, direto no Oracle, 
e só depois o webservice é chamado pra mexer no pedido real. 

Estrutura da chamada validada por introspecção do WSDL real (GravarPedidos_15)
e por testes reais (via SoapUI, fora deste código):
  - `opeExe` é obrigatório em `pedido` e em cada `produto` - marca o tipo de
    operação daquele nível: "I" = incluir, "A" = alterar (existente).
    Confirmado por teste real: "I"/"I" cria pedido+item do zero (pedido
    781740). "A" no pedido também foi aceito sem reclamação (um teste com
    numPed em branco falhou só por falta do numPed, não por causa do opeExe).
    Como Trocar/Inserir peça sempre mexem num pedido que JÁ EXISTE, usamos
    pedido.opeExe="A"; no produto, "I" pra item novo (inclusão/troca) e "A"
    pra alterar um item existente (cancelamento, via seqIpd).
  - Cada `produto` tem campo nativo `usuGer` (quem incluiu) mas NÃO tem campo
    nativo `usuAlt` - pra registrar quem alterou/cancelou um item existente,
    usa-se o mecanismo genérico `usuario: [{cmpUsu, vlrUsu}]` com
    cmpUsu="USUALT".
  - A resposta devolve, por produto processado (`respostaPedido.gridPro`), o
    `seqIpd` da linha - é esse valor que vai pra usu_t120sit.usu_seqipd
    quando o item é novo (inclusão/troca).
  - `erroExecucao` vazio/nulo NÃO significa sucesso por si só - um teste real
    (opeExe="A" mas numPed em branco) voltou com erroExecucao nil e
    mensagemRetorno "Processado com Sucesso." no nível raiz, mas o pedido em
    si falhou (`respostaPedido.tipRet=2`, `msgRet`="É necessário informar o
    número do pedido..."). O sucesso de verdade por pedido está em
    `respostaPedido.tipRet==1` (1=sucesso, 2=erro nos testes reais) - é isso
    que _chamar_gravar_pedidos confere, não só o erroExecucao do topo.
  - `qtdPed`/`qtdCan`/`preUni` são `xs:string` no XSD, não número - o Sapiens
    exige vírgula decimal ("384,41", não "384.41"), confirmado por erro real
    ('O valor informado para o campo "PreUni" não é numérico. O separador
    decimal padrão é ","'). Ver _fmt_numero().
  - o erro de negócio de verdade às vezes vem só no `gridPro.retorno` (por
    item), não no `msgRet`/`retorno` do pedido - esse último pode ficar
    genérico ("Verifique as entidades ligadas ao pedido...") enquanto o
    motivo real está um nível abaixo, no item específico que falhou.

Todo envelope SOAP enviado/recebido é gravado em texto puro (senha mascarada)
em logs/pedido_ws_envelopes.log - assim dá pra conferir exatamente o XML que
foi montado e a resposta real do Sapiens. Além disso, cada par de envelopes (enviado/recebido) 
é salvo em logs/xml/ como arquivos separados, nomeados com timestamp + operação, pra poder abrir cada retorno isolado.

"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PEDIDO_WS_WSDL = os.environ.get("PEDIDO_WS_WSDL", "")
PEDIDO_WS_USER = os.environ.get("PEDIDO_WS_USER", "")
PEDIDO_WS_PASSWORD = os.environ.get("PEDIDO_WS_PASSWORD", "")

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_XML_DIR = _LOG_DIR / "xml"
_XML_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("pedido_ws")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.FileHandler(_LOG_DIR / "pedido_ws_envelopes.log", encoding="utf-8")
    _handler.setFormatter(logging.Formatter("\n%(asctime)s [%(levelname)s]\n%(message)s"))
    logger.addHandler(_handler)


class PedidoWebserviceError(Exception):
    """Erro de configuração ou retornado pelo próprio webservice (erroExecucao/retorno)."""

def _fmt_numero(valor):
    """qtdPed/qtdCan/preUni são `xs:string` no XSD, não número - o Sapiens
    espera formato BR (vírgula decimal), confirmado por erro real do
    webservice: 'O valor informado para o campo "PreUni" não é numérico.
    O separador decimal padrão é ",".'"""
    if valor is None:
        return None
    return str(valor).replace(".", ",")

def _get_client():
    if not (PEDIDO_WS_WSDL and PEDIDO_WS_USER and PEDIDO_WS_PASSWORD):
        raise PedidoWebserviceError(
            "Webservice de pedidos não configurado - faltam PEDIDO_WS_WSDL/"
            "PEDIDO_WS_USER/PEDIDO_WS_PASSWORD no .env."
        )
    import zeep
    from zeep.plugins import HistoryPlugin

    history = HistoryPlugin()
    client = zeep.Client(PEDIDO_WS_WSDL, plugins=[history])
    return client, history

def _envelope_para_texto(entrada_historico):
    """Serializa o envelope SOAP (capturado pelo zeep HistoryPlugin) pra XML
    legível, mascarando a senha antes de gravar em log."""
    from lxml import etree

    if not entrada_historico:
        return "(sem envelope capturado)"
    xml = etree.tostring(entrada_historico["envelope"], pretty_print=True).decode()
    return re.sub(r"(<(?:\w+:)?password>).*?(</(?:\w+:)?password>)", r"\1****\2", xml)

def _log_envelopes(history, operacao):
    logger.info(
        "%s - enviado:\n%s\n%s - recebido:\n%s",
        operacao, _envelope_para_texto(history.last_sent),
        operacao, _envelope_para_texto(history.last_received),
    )
    _salvar_xml_arquivos(history, operacao)

def _salvar_xml_arquivos(history, operacao):
    """Salva o envelope enviado e o recebido como arquivos .xml separados em
    logs/xml/ (um par por chamada, nomeado com timestamp + operação) - além
    do log de texto único (_log_envelopes), pra poder abrir cada retorno
    isolado (ex: num editor de XML) sem procurar dentro do log grande."""
    agora = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for sufixo, entrada in (("enviado", history.last_sent), ("recebido", history.last_received)):
        xml = _envelope_para_texto(entrada)
        caminho = _XML_DIR / f"{agora}_{operacao}_{sufixo}.xml"
        caminho.write_text(xml, encoding="utf-8")

def _chamar_gravar_pedidos(pedidos, operacao, ignorar_pedido_bloqueado=False):
    """`ignorar_pedido_bloqueado` pula a consideração de análise de crédito
    do cliente (atraso de títulos) - só faz sentido pro codcli fixo de
    transferência interna do Pedido na loja (não pro cliente real de
    Inserir peça/Trocar item, onde o bloqueio de crédito é uma checagem de
    negócio válida)."""
    client, history = _get_client()
    try:
        resposta = client.service.GravarPedidos_15(
            user=PEDIDO_WS_USER, password=PEDIDO_WS_PASSWORD, encryption=0,
            parameters={
                "pedido": pedidos,
                "ignorarPedidoBloqueado": "S" if ignorar_pedido_bloqueado else "N",
            },
        )
    finally:
        _log_envelopes(history, operacao)

    if (resposta.erroExecucao or "").strip().upper() == "S":
        raise PedidoWebserviceError(resposta.mensagemRetorno or "Erro não especificado no GravarPedidos.")

    for resp_pedido in resposta.respostaPedido or []:
        tip_ret = getattr(resp_pedido, "tipRet", None)
        if tip_ret is not None and int(tip_ret) != 1:
            motivo_item = None
            for grid_pro in getattr(resp_pedido, "gridPro", None) or []:
                retorno_item = str(getattr(grid_pro, "retorno", "") or "")
                if retorno_item.strip().upper() not in ("", "S", "OK"):
                    motivo_item = retorno_item
                    break
            raise PedidoWebserviceError(
                motivo_item
                or getattr(resp_pedido, "msgRet", None) or getattr(resp_pedido, "retorno", None)
                or "Erro não especificado ao gravar o pedido."
            )
    return resposta

def _seqipd_da_resposta(resposta, codpro):
    """Procura, na resposta, o seqIpd da linha do produto que acabou de ser
    processada (pra gravar o vínculo em usu_t120sit.usu_seqipd)."""
    for resp_pedido in resposta.respostaPedido or []:
        for grid_pro in resp_pedido.gridPro or []:
            if str(getattr(grid_pro, "retorno", "")).strip().upper() not in ("", "S", "OK"):
                raise PedidoWebserviceError(f"Erro ao processar item {codpro}: {grid_pro.retorno}")
            return grid_pro.seqIpd
    raise PedidoWebserviceError("GravarPedidos não retornou a linha do produto gravado.")

def _numped_da_resposta(resposta):
    """numPed do pedido processado - só faz sentido quando o pedido é novo
    (opeExe="I" no nível do pedido), pra mostrar o número gerado na tela."""
    for resp_pedido in resposta.respostaPedido or []:
        return getattr(resp_pedido, "numPed", None)
    return None

def cancelar_item_pedido(codemp, codfil, numped, seqipd, qtd_cancelar, usuario):
    """Cancela `qtd_cancelar` unidades de um item já existente no pedido
    (E120IPD, via seqIpd), registrando o usuário em USUALT (campo genérico,
    ver docstring do módulo)."""
    pedido = {
        "opeExe": "A", "codEmp": codemp, "codFil": codfil, "numPed": numped,
        "produto": [{
            "opeExe": "A",
            "seqIpd": seqipd,
            "qtdCan": _fmt_numero(qtd_cancelar),
            "usuario": [{"cmpUsu": "USUALT", "vlrUsu": str(usuario)}],
        }],
    }
    _chamar_gravar_pedidos([pedido], "cancelar_item_pedido")
    return True

def incluir_item_pedido(codemp, codfil, numped, codpro, qtd, preco, codtab, usuario):
    """Inclui um item novo num pedido que já existe. Retorna o seqIpd que o
    Sapiens atribuiu à linha nova (pra gravar em usu_t120sit.usu_seqipd)."""
    pedido = {
        "opeExe": "A", "codEmp": codemp, "codFil": codfil, "numPed": numped,
        "produto": [{
            "opeExe": "I",
            "codPro": codpro, "qtdPed": _fmt_numero(qtd), "preUni": _fmt_numero(preco), "codTpr": codtab,
            "usuGer": str(usuario),
        }],
    }
    resposta = _chamar_gravar_pedidos([pedido], "incluir_item_pedido")
    return _seqipd_da_resposta(resposta, codpro)

# ---------------------------------------------------------------------
# Pedido na loja (RTL) - mesmo webservice GravarPedidos_15 já usado por
# incluir_item_pedido, mas com resEst/tnsPro e apontando pra loja. O pedido
# é sempre NOVO (opeExe="I" no nível do pedido, não "A") - o número é
# gerado pelo Sapiens na hora, não existe um pedido aberto de antemão pra
# reaproveitar. Por isso não recebe numped, e sim codCli (pra abrir o
# pedido do zero).
# ---------------------------------------------------------------------
def incluir_item_pedido_loja(codemp_loja, codfil_loja, codcli, codpro, qtd, preco, tns_pro, usuario):
    """Retorna (seqipd, numped) - numped é o número do pedido novo que o
    Sapiens gerou, pra mostrar na tela pra pessoa copiar."""
    pedido = {
        "opeExe": "I", "codEmp": codemp_loja, "codFil": codfil_loja, "codCli": codcli,
        "produto": [{
            "opeExe": "I",
            "codPro": codpro, "qtdPed": _fmt_numero(qtd), "preUni": _fmt_numero(preco),
            "tnsPro": tns_pro, "resEst": "S",
            "usuGer": str(usuario),
        }],
    }
    resposta = _chamar_gravar_pedidos([pedido], "incluir_item_pedido_loja", ignorar_pedido_bloqueado=True)
    seqipd = _seqipd_da_resposta(resposta, codpro)
    numped = _numped_da_resposta(resposta)
    return seqipd, numped


# ---------------------------------------------------------------------
# Solicitação de compra - webservice (GerarSolicitacaoCompra_3)
# ---------------------------------------------------------------------
COMPRA_WS_WSDL = os.environ.get("COMPRA_WS_WSDL", "")
COMPRA_WS_USER = os.environ.get("COMPRA_WS_USER", "")
COMPRA_WS_PASSWORD = os.environ.get("COMPRA_WS_PASSWORD", "")

def _get_client_compra():
    if not (COMPRA_WS_WSDL and COMPRA_WS_USER and COMPRA_WS_PASSWORD):
        raise PedidoWebserviceError(
            "Webservice de solicitação de compra não configurado - faltam "
            "COMPRA_WS_WSDL/COMPRA_WS_USER/COMPRA_WS_PASSWORD no .env."
        )
    import zeep
    from zeep.plugins import HistoryPlugin

    history = HistoryPlugin()
    client = zeep.Client(COMPRA_WS_WSDL, plugins=[history])
    return client, history

def gerar_solicitacao_compra(codemp, numsol, cod_dep, codpro, cod_tns, dat_prv, fil_ped, num_ped, obs_sol, pre_sol, qtd_sol, usu_sol):
    client, history = _get_client_compra()
    try:
        resposta = client.service.GerarSolicitacaoCompra_3(
            user=COMPRA_WS_USER, password=COMPRA_WS_PASSWORD, encryption=0,
            parameters={
                "codEmp": codemp,
                "itensProduto": [{
                    "codDep": cod_dep,
                    "codPro": codpro,
                    "codTns": cod_tns,
                    "datPrv": dat_prv.strftime("%d/%m/%Y"),
                    "filPed": fil_ped,
                    "numPed": num_ped,
                    "obsSol": obs_sol,
                    "preSol": f"{float(pre_sol):.2f}" if pre_sol is not None else None,
                    "qtdSol": f"{float(qtd_sol):.2f}",
                    "seqIpd": 1,
                    "seqSol": 1,
                    "uniMed": "UN",
                    "usuSol": usu_sol,
                }],
                "numSol": numsol,
            },
        )
    finally:
        _log_envelopes(history, "gerar_solicitacao_compra")

    erro_execucao = getattr(resposta, "erroExecucao", None)
    if (erro_execucao or "").strip().upper() == "S":
        raise PedidoWebserviceError(
            getattr(resposta, "mensagemRetorno", None) or "Erro não especificado no GerarSolicitacaoCompra."
        )
    return numsol