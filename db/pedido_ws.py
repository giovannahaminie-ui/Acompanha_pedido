"""
Estrutura de Webservices, utilizados para Incluir Item no pedido, 
Pedido na Loja e Solicitação de Compra

Placeholder (Estoque - TransacaoProduto)

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

# ---------------------------------------------------------------------
# Webservice (GravarPedido_15) - Incluir item no pedido
# ---------------------------------------------------------------------

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
# Webservice (GravarPedido_15) - Pedido na loja (RTL)
# ---------------------------------------------------------------------

def incluir_itens_pedido_loja(codemp_loja, codfil_loja, codcli, itens, tns_pro, usuario):
    """Grava um único pedido novo com todos os itens (lista de dicts
    {codpro, qtd, preco}) como linhas desse mesmo pedido - antes cada item
    virava um pedido separado, um de cada vez.

    Retorna (numped, resultados) - numped é o número do pedido novo gerado
    pelo Sapiens (compartilhado por todos os itens); resultados é uma lista
    paralela a `itens`, cada item {sucesso, seqipd, mensagem}. Assume que o
    gridPro devolvido vem na mesma ordem em que os produtos foram enviados
    (não confirmado com um teste real de mais de um item ainda - se algum
    dia vier fora de ordem, dá pra casar por codPro em vez de por índice).
    """
    pedido = {
        "opeExe": "I", "codEmp": codemp_loja, "codFil": codfil_loja, "codCli": codcli,
        "fecPed": "S",
        "usuario": [
            {"cmpUsu": "usu_sitent", "vlrUsu": "4"},
            {"cmpUsu": "usu_sitped", "vlrUsu": "6"},
        ],
        "produto": [
            {
                "opeExe": "I",
                "codPro": item["codpro"], "qtdPed": _fmt_numero(item["qtd"]), "preUni": _fmt_numero(item["preco"]),
                "tnsPro": tns_pro, "resEst": "S",
                "usuGer": str(usuario),
            }
            for item in itens
        ],
    }
    client, history = _get_client()
    try:
        resposta = client.service.GravarPedidos_15(
            user=PEDIDO_WS_USER, password=PEDIDO_WS_PASSWORD, encryption=0,
            parameters={"pedido": [pedido], "ignorarPedidoBloqueado": "S"},
        )
    finally:
        _log_envelopes(history, "incluir_itens_pedido_loja")

    if (resposta.erroExecucao or "").strip().upper() == "S":
        raise PedidoWebserviceError(resposta.mensagemRetorno or "Erro não especificado no GravarPedidos.")

    respostas_pedido = resposta.respostaPedido or []
    if not respostas_pedido:
        raise PedidoWebserviceError("GravarPedidos não retornou o pedido gravado.")
    resposta_pedido = respostas_pedido[0]
    numped = getattr(resposta_pedido, "numPed", None)

    grid_pro = getattr(resposta_pedido, "gridPro", None) or []
    resultados = []
    for indice, item in enumerate(itens):
        linha = grid_pro[indice] if indice < len(grid_pro) else None
        if linha is None:
            resultados.append({"sucesso": False, "seqipd": None, "mensagem": "Sem retorno pra esse item."})
            continue
        retorno_item = str(getattr(linha, "retorno", "") or "").strip().upper()
        if retorno_item not in ("", "S", "OK"):
            resultados.append({"sucesso": False, "seqipd": None, "mensagem": getattr(linha, "retorno", None) or "Erro não especificado."})
        else:
            resultados.append({"sucesso": True, "seqipd": linha.seqIpd, "mensagem": None})
    return numped, resultados


# ---------------------------------------------------------------------
# Webservice (GerarSolicitacaoCompra_3) - Solicitação de compra 
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

def gerar_solicitacao_compra_lote(codemp, numsol_compra, itens, usu_sol):
    """Grava uma única solicitação de compra (numsol_compra) com todos os
    itens (lista de dicts {cod_dep, codpro, cod_tns, dat_prv, fil_ped,
    num_ped, obs_sol, pre_sol, qtd_sol}) como linhas dela - antes cada item
    virava uma solicitação de compra separada, um de cada vez.

    Retorna um dict {seqSol: {sucesso, mensagem}} - seqSol é 1-based, na
    mesma ordem em que os itens foram passados (o retornoSolicitacao do
    webservice já vem com seqSol pra cada linha, então casamos por esse
    campo em vez de por índice/ordem da resposta).
    """
    client, history = _get_client_compra()
    try:
        resposta = client.service.GerarSolicitacaoCompra_3(
            user=COMPRA_WS_USER, password=COMPRA_WS_PASSWORD, encryption=0,
            parameters={
                "codEmp": codemp,
                "itensProduto": [
                    {
                        "codDep": item["cod_dep"],
                        "codPro": item["codpro"],
                        "codTns": item["cod_tns"],
                        "datPrv": item["dat_prv"].strftime("%d/%m/%Y"),
                        "filPed": item["fil_ped"],
                        "numPed": item["num_ped"],
                        "obsSol": item["obs_sol"],
                        "preSol": f"{float(item['pre_sol']):.2f}" if item.get("pre_sol") is not None else None,
                        "qtdSol": f"{float(item['qtd_sol']):.2f}",
                        "seqIpd": seq,
                        "seqSol": seq,
                        "uniMed": "UN",
                        "usuSol": usu_sol,
                    }
                    for seq, item in enumerate(itens, start=1)
                ],
                "numSol": numsol_compra,
            },
        )
    finally:
        _log_envelopes(history, "gerar_solicitacao_compra_lote")

    erro_execucao = getattr(resposta, "erroExecucao", None)
    if (erro_execucao or "").strip().upper() == "S":
        raise PedidoWebserviceError(
            getattr(resposta, "mensagemRetorno", None) or "Erro não especificado no GerarSolicitacaoCompra."
        )

    resultados = {}
    for retorno in resposta.retornoSolicitacao or []:
        tip_ret = getattr(retorno, "tipRet", None)
        resultados[retorno.seqSol] = {
            "sucesso": tip_ret is not None and int(tip_ret) == 1,
            "mensagem": getattr(retorno, "msgRet", None) or "",
        }
    return resultados

# ---------------------------------------------------------------------
# Ordem de compra (GravarOrdensCompra_5) - Gerado ao fechar o pedido da loja
# ---------------------------------------------------------------------
OC_WS_WSDL = os.environ.get("OC_WS_WSDL", "")
OC_WS_USER = os.environ.get("OC_WS_USER", "")
OC_WS_PASSWORD = os.environ.get("OC_WS_PASSWORD", "")

def _get_client_oc():
    if not (OC_WS_WSDL and OC_WS_USER and OC_WS_PASSWORD):
        raise PedidoWebserviceError(
            "Webservice de Ordem de Compra não configurado - faltam "
            "OC_WS_WSDL/OC_WS_USER/OC_WS_PASSWORD no .env."
        )
    import zeep
    from zeep.plugins import HistoryPlugin
    history = HistoryPlugin()
    client = zeep.Client(OC_WS_WSDL, plugins=[history])
    return client, history

def gerar_ordem_compra(codemp, codfil, cod_for, itens, numsol, numped):
    """itens: lista de dicts {codpro, qtd, preco}.
    Retorna (numocp, sucesso, mensagem)."""
    client, history = _get_client_oc()
    try:
        resposta = client.service.GravarOrdensCompra_5(
            user=OC_WS_USER, password=OC_WS_PASSWORD, encryption=0,
            parameters={
                "tipoProcessamento": 1,
                "identificadorSistema": "INTEGRADO",
                "dadosGerais": [{
                    "codEmp": codemp,
                    "codFil": codfil,
                    "codFor": cod_for,
                    "tipoProcessamento": 1,
                    "tnsPro": "90403",
                    "obsOcp": f"Solicitação {numsol} - Pedido {numped}",
                    "produtos": [
                        {
                            "codPro": item["codpro"],
                            "qtdPed": item["qtd"],
                            "preUni": item["preco"],
                            "uniMed": "UN",
                        }
                        for item in itens
                    ],
                }],
            },
        )
    finally:
        _log_envelopes(history, "gerar_ordem_compra")

    erro_execucao = getattr(resposta, "erroExecucao", None)
    if (erro_execucao or "").strip().upper() == "S":
        raise PedidoWebserviceError(
            getattr(resposta, "mensagemRetorno", None) or "Erro não especificado no GravarOrdensCompra."
        )

    dados_retorno = resposta.dadosRetorno or []
    if not dados_retorno:
        raise PedidoWebserviceError("GravarOrdensCompra não retornou a OC gerada.")
    retorno = dados_retorno[0]
    tip_ret = getattr(retorno, "tipRet", None)
    sucesso = tip_ret is not None and int(tip_ret) == 1
    return retorno.numOcp, sucesso, (getattr(retorno, "retorno", None) or "")
