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
# novo). Regra: 10% do preço atual (substituído) pra maioria dos itens;
# R$ 200,00 fixo pra "motor completo" (identificado pelo tipo de serviço)
TOLERANCIA_PRECO_TROCA_PERCENTUAL = 0.10
TOLERANCIA_PRECO_TROCA_MOTOR_COMPLETO = 200.0
TIPO_SERVICO_MOTOR_COMPLETO = "Completo"

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
    dados = oracle_db.get_solicitacoes(
        empresa=filtro.get("empresa"), filial=filtro.get("filial"),
        tipo_servico=tipo_servico, etapa=etapa,
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
        observacao = request.form.get("observacao", "")
        try:
            oracle_db.salvar_observacao_item(codemp, codfil, numsol, seqite, observacao)
            return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))
        except Exception:
            return render_template(
                "observacao_item.html", codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
                observacao=observacao,
                erro="Falha ao salvar a observação - tente novamente.",
            )
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
                elif not oracle_db.produto_tem_ligacao_deposito(codemp, codfil, cabecalho["numped"], codpro_novo):
                    erro = f"Produto {codpro_novo} não possui ligação para o depósito - processo não pode continuar."

        if not erro and request.form.get("confirmar"):
            try:
                seqipd_novo = pedido_ws.incluir_item_pedido(
                    codemp, codfil, cabecalho["numped"], codpro_novo, qtd,
                    produto["preco"], produto["codtab"], session["usuario"],
                )
                oracle_db.inserir_item_solicitacao(
                    codemp, codfil, numsol, cabecalho["numped"], seqipd_novo, codpro_novo,
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

    cabecalho = oracle_db.get_solicitacao_cabecalho(codemp, codfil, numsol)
    motor_completo = cabecalho["tipo_servico"].strip().lower() == TIPO_SERVICO_MOTOR_COMPLETO.lower()

    erro = None
    produto = None
    codpro_novo = ""
    qtd = 0
    diferenca_preco = None
    alerta_preco = False
    mostrar_confirmacao = False
    autorizado_por = request.form.get("autorizado_por", "").strip()

    if request.method == "POST":
        codpro_novo = request.form.get("codpro_novo", "").strip()
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
                elif not oracle_db.produto_tem_ligacao_deposito(codemp, codfil, item["numped"], codpro_novo):
                    erro = f"Produto {codpro_novo} não possui ligação para o depósito - processo não pode continuar."

        # Produto passou por todas as checagens - mostra a etapa de
        # confirmação mesmo que a autorização de preço ainda falte (ver
        # abaixo); só volta pra etapa 1 se o produto em si for inválido.
        mostrar_confirmacao = produto is not None and erro is None

        # Diferença de preço (produto novo x substituído) só é exibida quando
        # passa da tolerância: 10% do preço atual (substituído), ou R$ 200,00
        # fixo quando a solicitação é de "motor completo" (tipo de serviço).
        # Dentro da tolerância a tela pula direto pra confirmação simples.
        if mostrar_confirmacao and item_pedido and item_pedido["preco_unitario"] is not None:
            diferenca_preco = produto["preco"] - item_pedido["preco_unitario"]
            limite = (
                TOLERANCIA_PRECO_TROCA_MOTOR_COMPLETO if motor_completo
                else abs(item_pedido["preco_unitario"]) * TOLERANCIA_PRECO_TROCA_PERCENTUAL
            )
            alerta_preco = abs(diferenca_preco) > limite

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
                        codemp, codfil, item["numped"], codpro_novo, qtd,
                        preco_incluir, produto["codtab"], session["usuario"],
                    )
                    seqite_novo = oracle_db.inserir_item_solicitacao(
                        codemp, codfil, numsol, item["numped"], seqipd_novo, codpro_novo,
                        produto["descricao"], qtd, session["usuario"], veio_de_troca=True,
                    )
                    if alerta_preco:
                        # Mensagem compacta - usu_obsite tem limite de tamanho
                        # (VARCHAR2(250)): data, hora, usuário, codpro do
                        # produto antigo (substituído) e a mensagem, só isso.
                        agora_msg = datetime.now()
                        msg_troca = (
                            f"{agora_msg:%d/%m/%Y %H:%M} {session['usuario']} "
                            f"troca de {item['codpro']}: autorizado por {autorizado_por} "
                            f"(dif. R$ {diferenca_preco:.2f})"
                        )
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
# ---------------------------------------------------------------------
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
    app.run(debug=True, host="0.0.0.0", port=5051)
