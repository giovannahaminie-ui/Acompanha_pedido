"""
Cliente do webservice GravarPedidos (Sapiens/Senior) - usado só pelos fluxos de
Troca e Inserção de peça, pra cancelar/incluir item no PEDIDO (E120IPD). A
solicitação (T120SIT) é gravada à parte, direto no Oracle (ver oracle_db.py),
só depois que o webservice confirmar sucesso.

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
  - cada `produto` tem campo nativo `usuGer` (quem incluiu) mas NÃO tem campo
    nativo `usuAlt` - pra registrar quem alterou/cancelou um item existente,
    usa-se o mecanismo genérico `usuario: [{cmpUsu, vlrUsu}]` com
    cmpUsu="USUALT".
  - a resposta devolve, por produto processado (`respostaPedido.gridPro`), o
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
foi montado e a resposta real do Sapiens, sem depender de reconstruir isso a
partir do dict Python. Ver _log_envelopes().
"""

import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PEDIDO_WS_WSDL = os.environ.get("PEDIDO_WS_WSDL", "")
PEDIDO_WS_USER = os.environ.get("PEDIDO_WS_USER", "")
PEDIDO_WS_PASSWORD = os.environ.get("PEDIDO_WS_PASSWORD", "")

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

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


def _chamar_gravar_pedidos(pedidos, operacao):
    client, history = _get_client()
    try:
        resposta = client.service.GravarPedidos_15(
            user=PEDIDO_WS_USER, password=PEDIDO_WS_PASSWORD, encryption=0,
            parameters={"pedido": pedidos},
        )
    finally:
        _log_envelopes(history, operacao)

    if (resposta.erroExecucao or "").strip().upper() == "S":
        raise PedidoWebserviceError(resposta.mensagemRetorno or "Erro não especificado no GravarPedidos.")

    # erroExecucao vazio não garante sucesso - cada pedido tem seu próprio
    # tipRet (1=sucesso, 2=erro, confirmado nos testes reais). Sem essa
    # checagem, uma falha de negócio (ex: numPed inválido) passaria como
    # sucesso silencioso.
    for resp_pedido in resposta.respostaPedido or []:
        tip_ret = getattr(resp_pedido, "tipRet", None)
        if tip_ret is not None and int(tip_ret) != 1:
            # a mensagem do pedido (msgRet/retorno) costuma ser genérica
            # ("Verifique as entidades ligadas ao pedido...") - o motivo real
            # geralmente está no gridPro do item específico que falhou.
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
