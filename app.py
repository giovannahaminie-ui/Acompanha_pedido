"""
Acompanha Pedido - Estoque Retífica

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
FILIAIS = [("L", "Londrina"), ("P", "Prudente"), ("C", "Cambé")]
# tipo_servico/etapa vêm do Oracle (usu_ttipser / usu_tetppro) 


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
# Seleção inicial (empresa / filial / tipo de serviço / etapa)
# ---------------------------------------------------------------------
@app.route("/selecao", methods=["GET", "POST"])
@login_obrigatorio
def selecao():
    if request.method == "POST":
        session["filtro"] = {
            "empresa": request.form.get("empresa"),
            "filial": request.form.get("filial") or None,
            "tipo_servico": request.form.get("tipo_servico") or None,
            "etapa": request.form.get("etapa") or None,
        }
        return redirect(url_for("painel"))
    return render_template(
        "selecao.html",
        empresas=EMPRESAS, filiais=FILIAIS,
        tipos_servico=oracle_db.get_tipos_servico(), etapas=oracle_db.get_etapas(),
    )


# ---------------------------------------------------------------------
# Painel principal
# ---------------------------------------------------------------------
@app.route("/painel")
@login_obrigatorio
def painel():
    filtro = session.get("filtro")
    if not filtro:
        return redirect(url_for("selecao"))

    dados = oracle_db.get_solicitacoes(**filtro)

    nome_empresa = dict(EMPRESAS).get(int(filtro["empresa"]), "")
    nome_filial = dict(FILIAIS).get(filtro["filial"]) if filtro.get("filial") else "todas as filiais"
    contexto = f"Empresa {filtro['empresa']} — {nome_empresa}, {nome_filial}"

    return render_template(
        "painel.html",
        contexto=contexto,
        solicitados=dados["solicitados"],
        em_separacao=dados["em_separacao"],
        atendidos=dados["atendidos"],
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
    try:
        observacoes = oracle_db.get_observacoes_solicitacao(codemp, codfil, numsol)
    except Exception:
        observacoes = {}  # coluna usu_obsite ainda não existe no Oracle
    for item in dados["itens"]:
        item["observacao"] = observacoes.get(item["seqite"])
    return render_template(
        "detalhe_solicitacao.html",
        solicitacao=dados["solicitacao"],
        itens=dados["itens"],
        codemp=codemp, codfil=codfil, numsol=numsol,
    )


# ---------------------------------------------------------------------
# Observação do item (grava direto na T120SIT do Sapiens - substitui o
# antigo comentário local em SQLite). Depende da coluna usu_obsite existir
# no Oracle (ver README); se ainda não existir, mostra aviso claro em vez
# de deixar o erro do Oracle estourar pro usuário.
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
                erro="Não foi possível salvar - o campo de observação (usu_obsite) ainda não existe na T120SIT.",
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
# Cancelar item na solicitação (só mexe na T120SIT - não chama o
# webservice do pedido, não mexe no E120IPD)
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/item/<int:seqite>/cancelar", methods=["GET", "POST"])
@login_obrigatorio
def cancelar_item(codemp, codfil, numsol, seqite):
    item = oracle_db.get_item_solicitacao(codemp, codfil, numsol, seqite)
    if not item:
        return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))

    erro = None
    if request.method == "POST":
        try:
            qtd = float(request.form.get("qtd", "0").replace(",", "."))
        except ValueError:
            qtd = 0
        if qtd <= 0 or qtd > item["qtd_aberta"]:
            erro = f"Quantidade inválida - máximo {item['qtd_aberta']} (qtd. aberta)."
        else:
            oracle_db.cancelar_item_solicitacao(codemp, codfil, numsol, seqite, qtd)
            return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))

    return render_template(
        "cancelar_item.html", codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
        item=item, erro=erro,
    )


# ---------------------------------------------------------------------
# Inserir peça nova na solicitação + no pedido (webservice GravarPedidos).
# Fluxo em duas etapas na mesma rota: 1ª submissão valida produto/preço e
# mostra a comparação pra confirmação manual; 2ª (com "confirmar" no form)
# executa de fato - primeiro o pedido (webservice), só grava a solicitação
# (T120SIT) se o webservice confirmar sucesso.
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/item/<int:seqite>/inserir", methods=["GET", "POST"])
@login_obrigatorio
def inserir_item(codemp, codfil, numsol, seqite):
    item = oracle_db.get_item_solicitacao(codemp, codfil, numsol, seqite)
    if not item:
        return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))

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
            produto = oracle_db.buscar_produto_preco(codemp, codfil, item["numped"], codpro_novo)
            if not produto:
                erro = f"Produto {codpro_novo} não encontrado."
            elif not produto["ativo"]:
                erro = f"Produto {codpro_novo} está inativo."

        if not erro and request.form.get("confirmar"):
            try:
                seqipd_novo = pedido_ws.incluir_item_pedido(
                    codemp, codfil, item["numped"], codpro_novo, qtd,
                    produto["preco"], produto["codtab"], session["usuario"],
                )
                oracle_db.inserir_item_solicitacao(
                    codemp, codfil, numsol, item["numped"], seqipd_novo, codpro_novo,
                    produto["descricao"], qtd, session["usuario"],
                )
                return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))
            except pedido_ws.PedidoWebserviceError as e:
                erro = str(e)

    return render_template(
        "inserir_item.html", codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
        item=item, produto=produto, qtd=qtd, codpro_novo=codpro_novo, erro=erro,
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
            produto = oracle_db.buscar_produto_preco(codemp, codfil, item["numped"], codpro_novo)
            if not produto:
                erro = f"Produto {codpro_novo} não encontrado."
            elif not produto["ativo"]:
                erro = f"Produto {codpro_novo} está inativo."

        if not erro and request.form.get("confirmar"):
            try:
                pedido_ws.cancelar_item_pedido(
                    codemp, codfil, item["numped"], item["seqipd"], qtd, session["usuario"],
                )
                oracle_db.cancelar_item_solicitacao(codemp, codfil, numsol, seqite, qtd)
            except pedido_ws.PedidoWebserviceError as e:
                erro = f"Falha ao cancelar o item substituído - nada foi alterado. {e}"

            if not erro:
                try:
                    seqipd_novo = pedido_ws.incluir_item_pedido(
                        codemp, codfil, item["numped"], codpro_novo, qtd,
                        produto["preco"], produto["codtab"], session["usuario"],
                    )
                    oracle_db.inserir_item_solicitacao(
                        codemp, codfil, numsol, item["numped"], seqipd_novo, codpro_novo,
                        produto["descricao"], qtd, session["usuario"], veio_de_troca=True,
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
    )


# ---------------------------------------------------------------------
# Itens equivalentes (E075EQUI) - consulta, sem gravação
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/item/<codpro>/equivalentes")
@login_obrigatorio
def equivalentes_item(codemp, codfil, numsol, codpro):
    equivalentes = oracle_db.get_equivalentes(codemp, codpro)
    return render_template(
        "equivalentes_item.html",
        codemp=codemp, codfil=codfil, numsol=numsol, codpro=codpro,
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
    app.run(debug=True, port=5051)
