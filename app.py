"""
Acompanha Pedido API/FLASK - Estoque Retífica

"""

from datetime import datetime
from functools import wraps
import os

from flask import Flask, render_template, request, redirect, url_for, session
from dotenv import load_dotenv

from db import local_db, oracle_db, pedido_ws

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "chave-temporaria-so-para-dev")

local_db.init_db()

# Listas usadas na tela de seleção
EMPRESAS = [(1, "Retífica"), (2, "RTL"), (5, "Transmissões"), (12, "Tiête car")]
# usu_filexe (e120ped) guarda letra, não código numérico de filial
FILIAIS = [("L", "Londrina"), ("P", "Prudente"), ("C", "Cambé")] # A Filial de Cambé é a CRAF

# Tolerância de diferença de preço na troca de item (produto novo vs.
# produto substituído) - abaixo disso não mostra o comparativo de preço,
# só pede a confirmação simples; acima, mostra o alerta com os valores e
# passa a exigir o campo "quem autorizou" (gravado no usu_obsite do item
# novo). Regra única: 10% do preço atual (substituído), pra qualquer item.
TOLERANCIA_PRECO_TROCA_PERCENTUAL = 0.10

# ---------------------------------------------------------------------
# Autenticação / controle de sessão
# ---------------------------------------------------------------------
def login_obrigatorio(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper

def perfil_atual():
    # Níveis de acesso: G = Gerência, B = Boqueta, U = Usinagem
    """Perfil (G/B/U) do usuário logado, ou None se ainda não tem perfil."""
    usuario = session.get("usuario")
    return local_db.get_perfil(usuario) if usuario else None

@app.context_processor
def injetar_perfil():
    """Deixa o perfil do usuário logado disponível em qualquer template,
    pra mostrar (ou não) o atalho de administração no menu."""
    return {"perfil_logado": perfil_atual()}

# ---------------------------------------------------------------------
# Autenticação / Tela de Login por CodUsuario (usuário do Sapiens)
# ---------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"].strip()
        dados = oracle_db.verificar_login(usuario)
        if dados:
            session["usuario"] = dados["usuario"]
            session["nome"] = dados["nome"]
            local_db.upsert_usuario(dados["usuario"], dados["nome"])
            return redirect(url_for("selecao"))
        return render_template("login.html", erro="Código de usuário inválido")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------------------------------------------------------------
# Seleção inicial (empresa / filial )
# ---------------------------------------------------------------------
@app.route("/selecao", methods=["GET", "POST"])
@login_obrigatorio
def selecao():
    if request.method == "POST":
        session["filtro"] = {
            "empresa": request.form.get("empresa"),
            "filial": request.form.get("filial") or None,
        }
        return redirect(url_for("painel"))
    return render_template(
        "selecao.html",
        empresas=EMPRESAS, filiais=FILIAIS,
    )

# ---------------------------------------------------------------------
# Painel principal - tipo de serviço e etapa são usados como filtros opcionais
# ---------------------------------------------------------------------
@app.route("/painel")
@login_obrigatorio
def painel():
    filtro = session.get("filtro")
    if not filtro:
        return redirect(url_for("selecao"))

    tipo_servico = request.args.get("tipo_servico") or None
    etapa = request.args.get("etapa") or None
    numped = request.args.get("numped") or None
    numsol = request.args.get("numsol") or None
    dados = oracle_db.get_solicitacoes(
        empresa=filtro.get("empresa"), filial=filtro.get("filial"),
        tipo_servico=tipo_servico, etapa=etapa, numped=numped, numsol=numsol,
    )

    nome_empresa = dict(EMPRESAS).get(int(filtro["empresa"]), "")
    nome_filial = dict(FILIAIS).get(filtro["filial"]) if filtro.get("filial") else "todas as filiais"
    contexto = f"Empresa {filtro['empresa']} — {nome_empresa}, {nome_filial}"

    tipos_servico = oracle_db.get_tipos_servico()
    etapas = oracle_db.get_etapas()
    tipo_servico_nome = next((nome for cod, nome in tipos_servico if str(cod) == tipo_servico), None)
    etapa_nome = next((nome for cod, nome in etapas if str(cod) == etapa), None)

    return render_template(
        "painel.html",
        contexto=contexto,
        solicitados=dados["solicitados"],
        em_separacao=dados["em_separacao"],
        atendidos=dados["atendidos"],
        tipos_servico=tipos_servico, etapas=etapas,
        tipo_servico_selecionado=tipo_servico, etapa_selecionada=etapa,
        tipo_servico_nome=tipo_servico_nome, etapa_nome=etapa_nome,
        numped_selecionado=numped, numsol_selecionado=numsol,
        data_hoje=datetime.now().strftime("%d/%m/%Y"),
        hora_agora=datetime.now().strftime("%H:%M"),
    )

# ---------------------------------------------------------------------
# Assumir solicitação (Solicitado -> Em separação)
# ---------------------------------------------------------------------
@app.route("/solicitacao/assumir/<int:codemp>/<int:codfil>/<int:numsol>", methods=["GET", "POST"])
@login_obrigatorio
def assumir_solicitacao(codemp, codfil, numsol):
    cabecalho = oracle_db.get_solicitacao_cabecalho(codemp, codfil, numsol)

    if request.method == "POST":
        usuario = request.form["usuario"].strip()
        dados = oracle_db.verificar_login(usuario)
        if dados:
            oracle_db.assumir_solicitacao(codemp, codfil, numsol, dados["usuario"])
            return redirect(url_for("painel"))
        return render_template(
            "assumir_solicitacao.html", numped=cabecalho["numped"], numsol=numsol,
            solicitante=cabecalho["solicitante"], erro="Código de usuário inválido",
        )
    return render_template(
        "assumir_solicitacao.html", numped=cabecalho["numped"], numsol=numsol,
        solicitante=cabecalho["solicitante"],
    )

# ---------------------------------------------------------------------
# Segunda tela - detalhe da solicitação (itens + saldo de estoque)
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>")
@login_obrigatorio
def detalhe_solicitacao(codemp, codfil, numsol):
    dados = oracle_db.get_solicitacao_detalhe(codemp, codfil, numsol)
    return render_template(
        "detalhe_solicitacao.html",
        solicitacao=dados["solicitacao"],
        itens=dados["itens"],
        codemp=codemp, codfil=codfil, numsol=numsol,
    )

# ---------------------------------------------------------------------
# Observação do item (botão na coluna de Ações, por item - grava direto na
# T120SIT do Sapiens, usu_obsite, só do item em questão).
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/item/<int:seqite>/observacao", methods=["GET", "POST"])
@login_obrigatorio
def observacao_item(codemp, codfil, numsol, seqite):
    if request.method == "POST":
        comentario_novo = request.form.get("observacao", "").strip()
        if comentario_novo:
            linha = f"{session['usuario']}: {comentario_novo}"
            try:
                oracle_db.salvar_observacao_item(codemp, codfil, numsol, seqite, linha)
            except Exception:
                observacao = oracle_db.get_observacao_item(codemp, codfil, numsol, seqite)
                return render_template(
                    "observacao_item.html", codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
                    observacao=observacao,
                    erro="Falha ao salvar a observação - tente novamente.",
                )
        return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))
    try:
        observacao = oracle_db.get_observacao_item(codemp, codfil, numsol, seqite)
    except Exception:
        observacao = ""
    return render_template(
        "observacao_item.html", codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
        observacao=observacao,
    )

# ---------------------------------------------------------------------
# Cancelar item na solicitação (só realiza UPDATE na T120SIT)
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/item/<int:seqite>/cancelar", methods=["GET", "POST"])
@login_obrigatorio
def cancelar_item(codemp, codfil, numsol, seqite):
    item = oracle_db.get_item_solicitacao(codemp, codfil, numsol, seqite)
    if not item:
        return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))

    erro = None
    motivo = ""
    if request.method == "POST":
        motivo = request.form.get("motivo", "").strip()
        if item["qtd_aberta"] <= 0:
            erro = "Não há quantidade em aberto para cancelar."
        else:
            oracle_db.cancelar_item_solicitacao(codemp, codfil, numsol, seqite, session["usuario"], motivo=motivo)
            return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))

    return render_template(
        "cancelar_item.html", codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
        item=item, erro=erro, motivo=motivo,
    )

# ---------------------------------------------------------------------
# Inserir peça nova na solicitação + no pedido (webservice GravarPedidos_15).
# Ação do cabeçalho da segunda tela (não é mais por item) - fluxo em duas
# etapas na mesma rota: 1ª submissão valida produto/preço e mostra a
# comparação pra confirmação manual; 2ª (com "confirmar" no form) executa
# de fato - primeiro o pedido (webservice), só grava a solicitação
# (T120SIT) se o webservice confirmar sucesso.
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/inserir", methods=["GET", "POST"])
@login_obrigatorio
def inserir_item(codemp, codfil, numsol):
    cabecalho = oracle_db.get_solicitacao_cabecalho(codemp, codfil, numsol)

    erro = None
    produto = None
    codpro_novo = ""
    qtd = 0

    if request.method == "POST":
        codpro_novo = request.form.get("codpro_novo", "").strip()
        try:
            qtd = float(request.form.get("qtd", "0").replace(",", "."))
        except ValueError:
            qtd = 0

        if qtd <= 0:
            erro = "Informe uma quantidade válida."
        else:
            try:
                produto = oracle_db.buscar_produto_preco(codemp, codfil, cabecalho["numped"], codpro_novo)
            except oracle_db.ProdutoAmbiguoError as e:
                erro = str(e)
            if not erro:
                if not produto:
                    erro = f"Produto {codpro_novo} não foi encontrado."
                elif not produto["ativo"]:
                    erro = f"Produto {codpro_novo} está inativo."
                elif not produto["preco"]:
                    erro = f"Produto {codpro_novo} não possui preço - processo não pode continuar."
                elif not oracle_db.produto_tem_ligacao_deposito(codemp, codfil, cabecalho["numped"], produto["codpro"]):
                    erro = f"Produto {codpro_novo} não possui ligação para o depósito - processo não pode continuar."
                elif oracle_db.produto_ja_esta_no_pedido(codemp, codfil, cabecalho["numped"], produto["codpro"]):
                    erro = f"Produto {codpro_novo} já existe nesse pedido."

        if not erro and request.form.get("confirmar"):
            try:
                seqipd_novo = pedido_ws.incluir_item_pedido(
                    codemp, codfil, cabecalho["numped"], produto["codpro"], qtd,
                    produto["preco"], produto["codtab"], session["usuario"],
                )
                oracle_db.inserir_item_solicitacao(
                    codemp, codfil, numsol, cabecalho["numped"], seqipd_novo, produto["codpro"],
                    produto["descricao"], qtd, session["usuario"],
                )
                return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))
            except pedido_ws.PedidoWebserviceError as e:
                erro = str(e)

    return render_template(
        "inserir_item.html", codemp=codemp, codfil=codfil, numsol=numsol,
        cabecalho=cabecalho, produto=produto, qtd=qtd, codpro_novo=codpro_novo, erro=erro,
    )

# ---------------------------------------------------------------------
# Conferência com reserva - código de barras/produto + qtd (qtdcon).
# Tela pensada pra ficar aberta durante a conferência: cada envio resolve
# um produto, valida e grava; a pessoa continua conferindo o próximo item
# na mesma tela (não fecha depois de um envio com sucesso).
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/conferencia", methods=["GET", "POST"])
@login_obrigatorio
def conferencia_reserva(codemp, codfil, numsol):
    erro = None
    sucesso = None

    if request.method == "POST":
        codbar = request.form.get("codbar", "").strip()
        try:
            qtdcon = float(request.form.get("qtdcon", "0").replace(",", "."))
        except ValueError:
            qtdcon = 0

        if not codbar:
            erro = "Informe o código de barras ou do produto."
        elif qtdcon <= 0:
            erro = "Informe uma quantidade válida."
        else:
            codpro = oracle_db.resolver_codpro_conferencia(codemp, codbar)
            if not codpro:
                erro = f"Código {codbar} não encontrado (nem como derivação, nem código de barras, nem produto)."
            else:
                item = oracle_db.get_item_para_conferencia(codemp, codfil, numsol, codpro)
                if not item:
                    erro = f"Produto {codpro} não tem item em aberto nessa solicitação."
                elif qtdcon > item["qtd_aberta"]:
                    erro = f"Quantidade conferida ({qtdcon}) é maior que a quantidade aberta ({item['qtd_aberta']})."
                else:
                    filexe = oracle_db.get_filial_pedido(codemp, codfil, item["numped"])
                    coddep = oracle_db.get_coddep_esperado(codemp, filexe)
                    item["codpro"] = codpro
                    oracle_db.conferir_item_com_reserva(codemp, codfil, numsol, item, coddep, qtdcon)
                    sucesso = f"Produto {codpro} - {qtdcon} conferido(s) e reservado(s) com sucesso."

    return render_template(
        "conferencia_reserva.html", codemp=codemp, codfil=codfil, numsol=numsol,
        erro=erro, sucesso=sucesso,
    )

# ---------------------------------------------------------------------
# Troca de peça: cancela o item substituído no pedido + na solicitação e
# inclui o item novo no pedido + na solicitação (usu_indtrc='S'). Mesma
# lógica de confirmação manual em duas etapas do Inserir peça, mas com a
# checagem de qtd aberta no pedido (E120IPD) antes de trocar.
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/item/<int:seqite>/trocar", methods=["GET", "POST"])
@login_obrigatorio
def trocar_item(codemp, codfil, numsol, seqite):
    item = oracle_db.get_item_solicitacao(codemp, codfil, numsol, seqite)
    if not item:
        return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))

    item_pedido = None
    if item["seqipd"]:
        item_pedido = oracle_db.get_item_pedido(codemp, codfil, item["numped"], item["seqipd"])

    erro = None
    produto = None
    codpro_novo = ""
    qtd = 0
    diferenca_preco = None
    alerta_preco = False
    mostrar_confirmacao = False
    autorizado_por = request.form.get("autorizado_por", "").strip()

    if request.method == "POST":
        codpro_novo = request.form.get("codpro_novo", "").strip().upper()
        try:
            qtd = float(request.form.get("qtd", "0").replace(",", "."))
        except ValueError:
            qtd = 0

        if not item_pedido or qtd <= 0 or qtd > item_pedido["qtd_aberta"]:
            maximo = item_pedido["qtd_aberta"] if item_pedido else 0
            erro = f"Quantidade inválida - máximo {maximo} (qtd. aberta no pedido)."
        else:
            try:
                produto = oracle_db.buscar_produto_preco(codemp, codfil, item["numped"], codpro_novo)
            except oracle_db.ProdutoAmbiguoError as e:
                erro = str(e)
            if not erro:
                if not produto:
                    erro = f"Produto {codpro_novo} não foi encontrado."
                elif not produto["ativo"]:
                    erro = f"Produto {codpro_novo} está inativo."
                elif not produto["preco"]:
                    erro = f"Produto {codpro_novo} não possui preço - processo não pode continuar."
                elif not oracle_db.produto_tem_ligacao_deposito(codemp, codfil, item["numped"], produto["codpro"]):
                    erro = f"Produto {codpro_novo} não possui ligação para o depósito - processo não pode continuar."

        # Produto passou por todas as checagens - mostra a etapa de
        # confirmação mesmo que a autorização de preço ainda falte (ver
        # abaixo); só volta pra etapa 1 se o produto em si for inválido.
        mostrar_confirmacao = produto is not None and erro is None

        # Diferença de preço (produto novo x substituído) só é exibida quando
        # passa da tolerância: 10% do preço atual (substituído). Dentro da
        # tolerância a tela pula direto pra confirmação simples.
        if mostrar_confirmacao and item_pedido and item_pedido["preco_unitario"] is not None:
            diferenca_preco = produto["preco"] - item_pedido["preco_unitario"]
            limite = abs(item_pedido["preco_unitario"]) * TOLERANCIA_PRECO_TROCA_PERCENTUAL
            alerta_preco = diferenca_preco > limite

        if mostrar_confirmacao and request.form.get("confirmar") and alerta_preco and not autorizado_por:
            erro = "A diferença de preço passou da tolerância - informe quem autorizou a troca."

        if mostrar_confirmacao and not erro and request.form.get("confirmar"):
            try:
                pedido_ws.cancelar_item_pedido(
                    codemp, codfil, item["numped"], item["seqipd"], qtd, session["usuario"],
                )
                oracle_db.cancelar_qtd_item_solicitacao_troca(codemp, codfil, numsol, seqite, qtd)
            except pedido_ws.PedidoWebserviceError as e:
                erro = f"Falha ao cancelar o item substituído - nada foi alterado. {e}"

            if not erro:
                try:
                    preco_substituido = item_pedido["preco_unitario"] if item_pedido else None
                    # Se o preço do item substituído era maior que o do produto
                    # novo, manda esse preço (do substituído) pro webservice;
                    # senão manda sem preço (deixa o Sapiens aplicar o da
                    # tabela dele), evitando cair na checagem de tolerância de
                    # preço do próprio Sapiens.
                    preco_incluir = (
                        preco_substituido
                        if preco_substituido is not None and preco_substituido > produto["preco"]
                        else None
                    ) 
                    seqipd_novo = pedido_ws.incluir_item_pedido(
                        codemp, codfil, item["numped"], produto["codpro"], qtd,
                        preco_incluir, produto["codtab"], session["usuario"],
                    )
                    seqite_novo = oracle_db.inserir_item_solicitacao(
                        codemp, codfil, numsol, item["numped"], seqipd_novo, produto["codpro"],
                        produto["descricao"], qtd, session["usuario"], veio_de_troca=True,
                    )
                    if alerta_preco:
                        # Mensagem enxuta - usu_obsite tem limite de 99
                        # caracteres (VARCHAR2(99)).
                        msg_troca = f"{session['usuario']}: aut. {autorizado_por} (R$ {diferenca_preco:.2f})"
                        oracle_db.salvar_observacao_item(
                            codemp, codfil, numsol, seqite_novo, msg_troca,
                        )
                    return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))
                except pedido_ws.PedidoWebserviceError as e:
                    erro = (
                        f"O item substituído JÁ FOI CANCELADO, mas a inclusão do item novo falhou: {e} "
                        "Use o botão \"Inserir peça\" pra incluir o produto novo manualmente."
                    )

    return render_template(
        "trocar_item.html", codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
        item=item, item_pedido=item_pedido, produto=produto, qtd=qtd, codpro_novo=codpro_novo, erro=erro,
        diferenca_preco=diferenca_preco, alerta_preco=alerta_preco, autorizado_por=autorizado_por,
        mostrar_confirmacao=mostrar_confirmacao,
    )

def _dados_e_sugestao_loja(codemp, codfil, item):
    """dados_pedido_loja + sugestão de quantidade (qtdest da loja + o que
    ainda falta pedir, descontando usu_qtdmso) pra UM item - reaproveitado
    tanto na tela de revisão do lote quanto na gravação de cada item."""
    filexe = oracle_db.get_filial_pedido(codemp, codfil, item["numped"])
    dados_loja = oracle_db.dados_pedido_loja(codemp, filexe)
    if not dados_loja:
        return None, 0, 0
    qtdest_loja = oracle_db.get_qtd_deposito(dados_loja["codemp_loja"], dados_loja["coddep_loja"], item["codpro2"])
    saldo_solicitacao = item["qtd_aberta"] - item["qtd_mso"]
    qtd_sugerida = qtdest_loja + saldo_solicitacao if item["qtd_aberta"] > qtdest_loja else item["qtd_aberta"]
    return dados_loja, qtd_sugerida, qtdest_loja


# ---------------------------------------------------------------------
# Pedido na loja (RTL) em lote - a pessoa marca os itens direto na tabela
# (checkbox) e um botão independente (fora da coluna Ações) abre esta tela
# de revisão, com quantidade editável por item; só grava quando confirma
# aqui - um único pedido (GravarPedidos_15) com todos os itens marcados
# como linhas dele, não um pedido por item.
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/pedido_loja", methods=["POST"])
@login_obrigatorio
def pedido_loja_lote(codemp, codfil, numsol):
    seqites = [int(s) for s in request.form.getlist("seqites")]
    if not seqites:
        return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))

    detalhe = oracle_db.get_solicitacao_detalhe(codemp, codfil, numsol)
    itens_marcados = [i for i in detalhe["itens"] if i["seqite"] in seqites]

    if request.form.get("confirmar"):
        resultados = [None] * len(itens_marcados)
        itens_validos = []

        for indice, item in enumerate(itens_marcados):
            if not item["saldos"]:
                resultados[indice] = {
                    "item": item, "sucesso": False,
                    "mensagem": "Sem saldo em nenhum depósito - não é possível pedir na loja.",
                }
                continue

            try:
                qtd = float(request.form.get(f"qtd_{item['seqite']}", "0").replace(",", "."))
            except ValueError:
                qtd = 0
            if qtd <= 0:
                resultados[indice] = {"item": item, "sucesso": False, "mensagem": "Quantidade inválida."}
                continue

            dados_loja, _, qtdest_loja = _dados_e_sugestao_loja(codemp, codfil, item)
            if not dados_loja:
                resultados[indice] = {"item": item, "sucesso": False, "mensagem": "Sem regra de pedido de loja pra essa empresa/filial."}
                continue
            if qtd > qtdest_loja:
                resultados[indice] = {"item": item, "sucesso": False, "mensagem": "Saldo na loja insuficiente para essa quantidade."}
                continue

            produto = oracle_db.buscar_produto_preco(dados_loja["codemp_loja"], dados_loja["codfil_loja"], None, item["codpro2"])
            if not produto:
                resultados[indice] = {"item": item, "sucesso": False, "mensagem": f"Produto {item['codpro2']} não encontrado na loja."}
                continue

            itens_validos.append((indice, item, qtd, produto["preco"], dados_loja))

        if itens_validos:
            dados_loja = itens_validos[0][4]
            try:
                numped, resultados_ws = pedido_ws.incluir_itens_pedido_loja(
                    dados_loja["codemp_loja"], dados_loja["codfil_loja"], dados_loja["codcli"],
                    [{"codpro": item["codpro2"], "qtd": qtd, "preco": preco} for _, item, qtd, preco, _ in itens_validos],
                    tns_pro="90100", usuario=session["usuario"],
                )

                seqites_validos = [item["seqite"] for _, item, _, _, _ in itens_validos]
                for (indice, item, qtd, _preco, _dl), resultado_ws in zip(itens_validos, resultados_ws):
                    if resultado_ws["sucesso"]:
                        oracle_db.somar_qtd_mso_item(codemp, codfil, numsol, item["seqite"], qtd)
                        local_db.registrar_acao(
                            tipo_acao="pedido_criado",
                            usuario=session["usuario"],
                            codemp=codemp,
                            codfil=codfil,
                            numsol=numsol,
                            numped=numped,
                            detalhes=f"Produto {item['codpro2']}, Quantidade {qtd}"
                        )
                        resultados[indice] = {
                            "item": item, "sucesso": True, "numped": numped,
                            "mensagem": "Pedido gerado com sucesso.",
                        }
                    else:
                        resultados[indice] = {
                            "item": item, "sucesso": False,
                            "mensagem": resultado_ws["mensagem"] or "Erro não especificado.",
                        }

                if any(r["sucesso"] for r in resultados if r is not None):
                    try:
                        cod_for = oracle_db.get_codfor_filial(dados_loja["codemp_loja"], dados_loja["codfil_loja"])
                        if cod_for:
                            numocp, sucesso_oc, msg_oc = pedido_ws.gerar_ordem_compra(
                                codemp=dados_loja["EmpOcp"], codfil=dados_loja["FilOcp"], coddep = dados_loja["DepOcp"],
                                cod_for=cod_for,
                                    itens=[
                                {
                                    "codpro": item["codpro1"], 
                                    "qtd": qtd, 
                                    "preco": oracle_db.get_preco_item_pedido(dados_loja["codemp_loja"], dados_loja["codfil_loja"], numped, item["codpro1"]) or preco
                                }
                                for _, item, qtd, preco, _ in itens_validos
                            ],
                                numsol=numsol, numped=numped,
                            )
                            if sucesso_oc:
                                oracle_db.atualizar_pedido_com_oc(dados_loja["codemp_loja"], dados_loja["codfil_loja"], numped, numocp)
                                oracle_db.atualizar_itens_solicitacao_com_oc(codemp, codfil, numsol, seqites_validos)
                                local_db.registrar_acao(
                                    tipo_acao="oc_gerada",
                                    usuario=session["usuario"],
                                    codemp=codemp,
                                    codfil=codfil,
                                    numsol=numsol,
                                    numped=numped,
                                    numocp=numocp,
                                    detalhes=msg_oc
                                )
                    except pedido_ws.PedidoWebserviceError as e:
                        pass
            except pedido_ws.PedidoWebserviceError as e:
                for indice, item, _qtd, _preco, _dl in itens_validos:
                    resultados[indice] = {"item": item, "sucesso": False, "mensagem": str(e)}

        return render_template(
            "pedido_loja_lote.html", codemp=codemp, codfil=codfil, numsol=numsol,
            itens=itens_marcados, resultados=resultados,
        )

    itens_com_sugestao = []
    for item in itens_marcados:
        _, qtd_sugerida, qtdest_loja = _dados_e_sugestao_loja(codemp, codfil, item)
        itens_com_sugestao.append({
            **item, "qtd_sugerida": qtd_sugerida, "qtdest_loja": qtdest_loja, "sem_saldo": not item["saldos"],
        })

    return render_template(
        "pedido_loja_lote.html", codemp=codemp, codfil=codfil, numsol=numsol,
        itens=itens_com_sugestao, resultados=None,
    )


# ---------------------------------------------------------------------
# Solicitação de compra em lote - mesmo padrão do pedido na loja acima:
# uma única solicitação de compra (GerarSolicitacaoCompra_3) com todos os
# itens marcados como linhas dela, não uma solicitação por item.
# numPed do item de compra = numero da OS (item["numped"]), não o numsol_compra
# recém-gerado. A gravação de verdade segue com filPed/codTns ainda a
# confirmar (ver conversa anterior).
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/solicitacao_compra", methods=["POST"])
@login_obrigatorio
def solicitacao_compra_lote(codemp, codfil, numsol):
    seqites = [int(s) for s in request.form.getlist("seqites")]
    if not seqites:
        return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))

    detalhe = oracle_db.get_solicitacao_detalhe(codemp, codfil, numsol)
    itens_marcados = [i for i in detalhe["itens"] if i["seqite"] in seqites]

    if request.form.get("confirmar"):
        resultados = [None] * len(itens_marcados)
        itens_validos = []  # [(indice, item, qtd, cod_dep)]

        for indice, item in enumerate(itens_marcados):
            try:
                qtd = float(request.form.get(f"qtd_{item['seqite']}", "0").replace(",", "."))
            except ValueError:
                qtd = 0
            if qtd <= 0:
                resultados[indice] = {"item": item, "sucesso": False, "mensagem": "Quantidade inválida."}
                continue
            if qtd + item["qtd_mso"] > item["qtd_aberta"]:
                resultados[indice] = {
                    "item": item, "sucesso": False,
                    "mensagem": f"Quantidade Solicitada ({qtd}) + já em MSO ({item['qtd_mso']}) excede a quantidade em aberto ({item['qtd_aberta']})."
                }
                continue
            filexe = oracle_db.get_filial_pedido(codemp, codfil, item["numped"])
            cod_dep = oracle_db.get_coddep_esperado(codemp, filexe)
            if not cod_dep:
                resultados[indice] = {"item": item, "sucesso": False, "mensagem": "Sem depósito ligado a essa empresa/filial."}
                continue

            itens_validos.append((indice, item, qtd, cod_dep))

        if itens_validos:
            numsol_compra = oracle_db.proximo_numsol_compra(codemp)
            try:
                resultados_ws = pedido_ws.gerar_solicitacao_compra_lote(
                    codemp=codemp, numsol_compra=numsol_compra,
                    itens=[
                        {
                            "cod_dep": cod_dep, "codpro": item["codpro1"], "cod_tns": "91400",
                            "dat_prv": datetime.now(), "fil_ped": codfil, "num_ped": item["numped"],
                            "obs_sol": f"Solicitação {numsol} item {item['seqite']}", "pre_sol": None, "qtd_sol": qtd,
                        }
                        for _, item, qtd, cod_dep in itens_validos
                    ],
                    usu_sol=session["usuario"],
                )
                for seq, (indice, item, qtd, _cod_dep) in enumerate(itens_validos, start=1):
                    resultado_ws = resultados_ws.get(seq)
                    if resultado_ws and resultado_ws["sucesso"]:
                        oracle_db.salvar_numsco_item(codemp, codfil, numsol, item["seqite"], numsol_compra)
                        oracle_db.somar_qtd_mso_item(codemp, codfil, numsol, item["seqite"], qtd)
                        local_db.registrar_acao(
                            tipo_acao="solicitacao_compra_gerada",
                            usuario=session["usuario"],
                            codemp=codemp,
                            codfil=codfil,
                            numsol=numsol,
                            detalhes=f"Solicitação compra {numsol_compra}: Produto {item['codpro1']}, Quantidade {qtd}"
                        )
                        resultados[indice] = {
                            "item": item, "sucesso": True, "numsol_compra": numsol_compra,
                            "mensagem": f"Solicitação de compra {numsol_compra} gerada com sucesso.",
                        }
                    else:
                        resultados[indice] = {
                            "item": item, "sucesso": False,
                            "mensagem": (resultado_ws["mensagem"] if resultado_ws else None) or "Erro não especificado.",
                        }
            except pedido_ws.PedidoWebserviceError as e:
                for indice, item, _qtd, _cod_dep in itens_validos:
                    resultados[indice] = {"item": item, "sucesso": False, "mensagem": str(e)}

        return render_template(
            "solicitacao_compra_lote.html", codemp=codemp, codfil=codfil, numsol=numsol,
            itens=itens_marcados, resultados=resultados,
        )

    itens_com_sugestao = [
        {**item, "qtd_sugerida": item["qtd_aberta"] - item["qtd_mso"], "alerta_saldo_grupo": bool(item["saldos"])}
        for item in itens_marcados
    ]
    return render_template(
        "solicitacao_compra_lote.html", codemp=codemp, codfil=codfil, numsol=numsol,
        itens=itens_com_sugestao, resultados=None,
    )

# ---------------------------------------------------------------------
# Histórico do item - consulta, sem gravação. Reaproveita
# get_solicitacao_detalhe (mesmo dado já usado na tela principal), só que
# focado num item só: quantidades, vínculo com pedido/solicitação de
# compra, e o log de observações (cancelamento/troca/comentários).
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/item/<int:seqite>/historico")
@login_obrigatorio
def historico_item(codemp, codfil, numsol, seqite):
    detalhe = oracle_db.get_solicitacao_detalhe(codemp, codfil, numsol)
    item = next((i for i in detalhe["itens"] if i["seqite"] == seqite), None)
    if not item:
        return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))
    log_observacoes = [linha.strip() for linha in item["observacao"].split("\n") if linha.strip()]
    return render_template(
        "historico_item.html", codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
        item=item, log_observacoes=log_observacoes,
    )

# ---------------------------------------------------------------------
# Itens equivalentes (E075EQUI) - consulta, sem gravação
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/item/<int:seqite>/equivalentes/<codpro>")
@login_obrigatorio
def equivalentes_item(codemp, codfil, numsol, seqite, codpro):
    equivalentes = oracle_db.get_equivalentes(codemp, codpro)
    return render_template(
        "equivalentes_item.html",
        codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite, codpro=codpro,
        equivalentes=equivalentes,
    )

# ---------------------------------------------------------------------
# Administração de perfis (só Gerência)
# ===== HISTÓRICO DE AÇÕES =====
@app.route("/historico/<int:codemp>/<int:codfil>/<int:numsol>")
@login_obrigatorio
def historico_solicitacao(codemp, codfil, numsol):
    """Mostra o histórico de ações de uma solicitação."""
    acoes = local_db.listar_historico_por_solicitacao(codemp, codfil, numsol)
    detalhe = oracle_db.get_solicitacao_detalhe(codemp, codfil, numsol)
    return render_template(
        "historico.html",
        codemp=codemp, codfil=codfil, numsol=numsol,
        tipo="solicitacao",
        acoes=acoes,
        detalhe=detalhe
    )

@app.route("/historico/geral")
@login_obrigatorio
def historico_geral():
    """Mostra o histórico geral de todas as ações."""
    if perfil_atual() != "G":
        return redirect(url_for("painel"))
    acoes = local_db.listar_historico_geral(limite=200)
    return render_template("historico_geral.html", acoes=acoes)

# ===== ÁREA ADMINISTRATIVA =====
@app.route("/admin/perfis")
@login_obrigatorio
def admin_perfis():
    if perfil_atual() != "G":
        return redirect(url_for("painel"))
    usuarios_sapiens = oracle_db.listar_usuarios_ativos()
    usuarios = local_db.listar_usuarios_com_perfil(usuarios_sapiens)
    return render_template("admin_perfis.html", usuarios=usuarios)

@app.route("/admin/perfis/salvar", methods=["POST"])
@login_obrigatorio
def salvar_perfil():
    if perfil_atual() != "G":
        return redirect(url_for("painel"))
    local_db.salvar_perfil(
        request.form["usuario"], request.form["perfil"], request.form.get("nome")
    )
    return redirect(url_for("admin_perfis"))

@app.route("/")
def index():
    return redirect(url_for("painel") if "usuario" in session else url_for("login"))

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5051)
