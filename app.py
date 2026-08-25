"""
Acompanha Pedido API/FLASK - Estoque Retífica

"""

from datetime import datetime
from functools import wraps
import os

from flask import Flask, render_template, request, redirect, url_for, session, current_app
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
    """Deixa o perfil e o nome do usuário logado disponíveis em qualquer
    template, pra mostrar (ou não) o atalho de administração no menu e
    exibir quem está logado."""
    return {"perfil_logado": perfil_atual(), "nome_usuario_logado": session.get("nome")}

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
def _contexto_painel():
    """Monta o contexto do painel (dados do Oracle + visibilidade por
    perfil) - usado tanto pela página cheia quanto pelo fragmento de
    auto-refresh (/painel/dados)."""
    filtro = session.get("filtro")
    if not filtro:
        return None

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

    # Colunas visíveis por perfil: Gerência vê tudo; Boqueta vê Solicitado
    # e Em separação; Usinagem vê só Atendido/Parcial. Quem ainda não tem
    # perfil atribuído vê as três colunas, mas só consulta - sem interagir
    # (assumir solicitação, ir pro detalhe, entregar item).
    perfil = perfil_atual()
    if perfil is None:
        mostrar_solicitado = mostrar_separacao = mostrar_atendido = True
        somente_visualizacao = True
    else:
        mostrar_solicitado = perfil in ("G", "B")
        mostrar_separacao = perfil in ("G", "B")
        mostrar_atendido = perfil in ("G", "U")
        somente_visualizacao = False
    num_colunas_visiveis = sum([mostrar_solicitado, mostrar_separacao, mostrar_atendido]) or 1

    return dict(
        contexto=contexto,
        solicitados=dados["solicitados"],
        em_separacao=dados["em_separacao"],
        atendidos=dados["atendidos"],
        mostrar_solicitado=mostrar_solicitado,
        mostrar_separacao=mostrar_separacao,
        mostrar_atendido=mostrar_atendido,
        somente_visualizacao=somente_visualizacao,
        num_colunas_visiveis=num_colunas_visiveis,
        tipos_servico=tipos_servico, etapas=etapas,
        tipo_servico_selecionado=tipo_servico, etapa_selecionada=etapa,
        tipo_servico_nome=tipo_servico_nome, etapa_nome=etapa_nome,
        numped_selecionado=numped, numsol_selecionado=numsol,
        data_hoje=datetime.now().strftime("%d/%m/%Y"),
        hora_agora=datetime.now().strftime("%H:%M"),
    )

def _renderizar_block(template_nome, block_nome, **contexto):
    """Renderiza só um {% block %} de um template - evita precisar de um
    arquivo .html separado só pro fragmento de auto-refresh do painel."""
    template = current_app.jinja_env.get_template(template_nome)
    ctx = template.new_context(contexto)
    return "".join(template.blocks[block_nome](ctx))

@app.route("/painel")
@login_obrigatorio
def painel():
    ctx = _contexto_painel()
    if ctx is None:
        return redirect(url_for("selecao"))
    return render_template("painel.html", **ctx)

@app.route("/painel/dados")
@login_obrigatorio
def painel_dados():
    """Só o fragmento das 3 colunas (bloco 'grid' de painel.html) - usado
    pelo auto-refresh via JS a cada 10s."""
    ctx = _contexto_painel()
    if ctx is None:
        return "", 401
    return _renderizar_block("painel.html", "grid", **ctx)

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
            return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))
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
def _render_detalhe(
    codemp, codfil, numsol,
    erro_inserir=None, sucesso_inserir=None, painel_aberto=False, avisar_alteracao=None,
    erro_conf=None, sucesso_conf=None, painel_conf_aberto=False, sucesso_troca=None,
):
    dados = oracle_db.get_solicitacao_detalhe(codemp, codfil, numsol)
    pendentes_inserir = local_db.listar_itens_pendentes(codemp, codfil, numsol)
    pendentes_conferencia = local_db.listar_itens_conferencia_pendentes(codemp, codfil, numsol)
    itens_conferencia = [
        i for i in dados["itens"]
        if i["sitite"] in (1, 2) and i["qtd_atendida"] < i["qtd_solic"]
    ]
    return render_template(
        "detalhe_solicitacao.html",
        solicitacao=dados["solicitacao"],
        itens=dados["itens"],
        codemp=codemp, codfil=codfil, numsol=numsol,
        pendentes_inserir=pendentes_inserir,
        erro_inserir=erro_inserir,
        sucesso_inserir=sucesso_inserir,
        sucesso_troca=sucesso_troca,
        avisar_alteracao=avisar_alteracao,
        painel_inserir_aberto=painel_aberto or bool(pendentes_inserir),
        itens_conferencia=itens_conferencia,
        pendentes_conferencia=pendentes_conferencia,
        erro_conf=erro_conf, sucesso_conf=sucesso_conf,
        painel_conf_aberto=painel_conf_aberto or bool(pendentes_conferencia),
    )

@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>")
@login_obrigatorio
def detalhe_solicitacao(codemp, codfil, numsol):
    return _render_detalhe(codemp, codfil, numsol)

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
# Painel embutido na própria tela de detalhe (não é mais página/modal
# separado) - permite montar uma lista de peças (rota "adicionar", uma
# validação de produto por vez) antes de gravar de fato no pedido/
# solicitação (rota "confirmar", processa a lista inteira em sequência).
# A lista pendente fica salva em local_db (itens_inserir_pendentes), não
# em campos ocultos do formulário - assim sobrevive a sair da tela e voltar.
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/inserir/adicionar", methods=["POST"])
@login_obrigatorio
def inserir_peca_adicionar(codemp, codfil, numsol):
    cabecalho = oracle_db.get_solicitacao_cabecalho(codemp, codfil, numsol)
    codpro_novo = request.form.get("codpro_novo", "").strip()
    try:
        qtd = float(request.form.get("qtd", "0").replace(",", "."))
    except ValueError:
        qtd = 0
    confirmar_alteracao = request.form.get("confirmar_alteracao") == "1"

    erro = None
    avisar_alteracao = None
    pendentes_atuais = local_db.listar_itens_pendentes(codemp, codfil, numsol)
    if not codpro_novo:
        erro = "Informe o código do produto."
    elif qtd <= 0:
        erro = "Informe uma quantidade válida."
    elif codpro_novo in [p["codpro"] for p in pendentes_atuais]:
        erro = f"Produto {codpro_novo} já está na lista."
    else:
        produto = None
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
        if not erro:
            item_existente = oracle_db.get_item_solicitacao_por_codpro(codemp, codfil, numsol, produto["codpro"])
            if item_existente and not confirmar_alteracao:
                avisar_alteracao = {
                    "codpro": produto["codpro"], "descricao": produto["descricao"],
                    "qtd_atual": item_existente["qtd_solicitada"], "qtd_adicionar": qtd,
                }
            elif item_existente:
                local_db.adicionar_item_pendente(
                    codemp, codfil, numsol, produto["codpro"], produto["descricao"],
                    qtd, produto["preco"], produto["codtab"], session["usuario"],
                    is_alteracao=True, seqite_existente=item_existente["seqite"],
                    seqipd_existente=item_existente["seqipd"],
                )
            else:
                local_db.adicionar_item_pendente(
                    codemp, codfil, numsol, produto["codpro"], produto["descricao"],
                    qtd, produto["preco"], produto["codtab"], session["usuario"],
                )

    if erro or avisar_alteracao:
        return _render_detalhe(codemp, codfil, numsol, erro_inserir=erro, avisar_alteracao=avisar_alteracao, painel_aberto=True)
    return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))

@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/inserir/remover/<int:id_pendente>", methods=["POST"])
@login_obrigatorio
def inserir_peca_remover(codemp, codfil, numsol, id_pendente):
    local_db.remover_item_pendente(id_pendente)
    return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))

@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/inserir/confirmar", methods=["POST"])
@login_obrigatorio
def inserir_peca_confirmar(codemp, codfil, numsol):
    cabecalho = oracle_db.get_solicitacao_cabecalho(codemp, codfil, numsol)
    pendentes = local_db.listar_itens_pendentes(codemp, codfil, numsol)
    if not pendentes:
        return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))

    try:
        for item in pendentes:
            if item["is_alteracao"]:
                pedido_ws.adicionar_qtd_item_pedido(
                    codemp, codfil, cabecalho["numped"], item["seqipd_existente"], item["qtd"], session["usuario"],
                )
                oracle_db.adicionar_qtd_item_solicitacao(
                    codemp, codfil, numsol, item["seqite_existente"], item["qtd"],
                )
            else:
                seqipd_novo = pedido_ws.incluir_item_pedido(
                    codemp, codfil, cabecalho["numped"], item["codpro"], item["qtd"],
                    item["preco"], item["codtab"], session["usuario"],
                )
                oracle_db.inserir_item_solicitacao(
                    codemp, codfil, numsol, cabecalho["numped"], seqipd_novo, item["codpro"],
                    item["descricao"], item["qtd"], session["usuario"],
                )
            local_db.remover_item_pendente(item["id"])
    except pedido_ws.PedidoWebserviceError as e:
        return _render_detalhe(codemp, codfil, numsol, erro_inserir=f"Falha ao incluir peça: {e}", painel_aberto=True)

    itens_txt = "; ".join(f"{item['codpro']} -{item['descricao']}" for item in pendentes)
    sucesso_inserir = (
        f"Item {itens_txt} inserido na solicitação."
    )
    return _render_detalhe(codemp, codfil, numsol, sucesso_inserir=sucesso_inserir)

# ---------------------------------------------------------------------
 #Conferência com reserva - bipar/adicionar fica local (rápido, sem ida
# ao Oracle); "confirmar" processa a lista inteira de uma vez só.
# ---------------------------------------------------------------------
@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/conferencia", methods=["POST"])
@login_obrigatorio
def conferencia_adicionar(codemp, codfil, numsol):
    erro = None
    codbar = request.form.get("codbar", "").strip().upper()
    try:
        qtdcon = float(request.form.get("qtdcon", "0").replace(",", "."))
    except ValueError:
        qtdcon = 0

    if not codbar:
        erro = "Informe o código de barras ou do produto."
    elif qtdcon <= 0:
        erro = "Informe uma quantidade válida."
    else:
        local_db.adicionar_item_conferencia_pendentes(
            codemp, codfil, numsol, codbar, qtdcon, session["usuario"],
        )

    return _render_detalhe(codemp, codfil, numsol, erro_conf=erro, painel_conf_aberto=True)

@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/conferencia/remover/<int:id_pendente>", methods=["POST"])
@login_obrigatorio
def conferencia_remover(codemp, codfil, numsol, id_pendente):
    local_db.remover_item_conferencia_pendente(id_pendente)
    return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))

@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/conferencia/confirmar", methods=["POST"])
@login_obrigatorio
def conferencia_confirmar(codemp, codfil, numsol):
    pendentes = local_db.listar_itens_conferencia_pendentes(codemp, codfil, numsol)
    if not pendentes:
        return redirect(url_for("detalhe_solicitacao", codemp=codemp, codfil=codfil, numsol=numsol))

    erro = None
    sucesso_count = 0
    for p in pendentes:
        codpro = oracle_db.resolver_codpro_conferencia(codemp, p["codbar"])

        if not codpro: 
            erro = f"Código {p['codbar']} não encontrado (nem como derivação, nem código de barras, nem produto. Verificar)."
            break

        item = oracle_db.get_item_para_conferencia(codemp, codfil, numsol, codpro)
        if not item:
            erro = f"Produto {codpro} não possui item em aberto nessa solicitação."
            break
        if p["qtd"] > item["qtd_aberta"]:
            erro = f"Quantidade conferida ({p['qtd']}) é maior que a quantidade em aberto ({item['qtd_aberta']}) do produto {codpro}."
            break

        filexe = oracle_db.get_filial_pedido(codemp, codfil, item["numped"])
        coddep = oracle_db.get_coddep_esperado(codemp, filexe)
        item["codpro"] = codpro
        oracle_db.conferir_item_com_reserva(codemp, codfil, numsol, item, coddep, p["qtd"], p["usuario"])
        local_db.remover_item_conferencia_pendente(p["id"])
        sucesso_count += 1

    if sucesso_count:
        oracle_db.atualizar_situacao_atendida(codemp, codfil, numsol)

    sucesso = f"{sucesso_count} item(ns) conferido(s) e reservado(s) com sucesso" if sucesso_count else None
    return _render_detalhe(codemp, codfil, numsol, erro_conf=erro, sucesso_conf=sucesso, painel_conf_aberto=True)

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

    if item["qtd_movimentada"]:
        return render_template(
            "trocar_item.html", codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite, item=item, item_pedido=item_pedido,
            produto=None, qtd=0, codpro_novo="", erro=None, diferenca_preco=None, alerta_preco=False, autorizado_por="", mostrar_confirmacao=False,
            item_existente_solicitacao=None, bloqueado=True, 
        )

    erro = None
    produto = None
    codpro_novo = ""
    qtd = 0
    diferenca_preco = None
    alerta_preco = False
    mostrar_confirmacao = False
    item_existente_solicitacao = None
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

        if not erro and produto:
            item_existente_solicitacao = oracle_db.get_item_solicitacao_por_codpro(codemp, codfil, numsol, produto["codpro"])

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
                    if item_existente_solicitacao:
                        pedido_ws.adicionar_qtd_item_pedido(
                            codemp, codfil, item["numped"], item_existente_solicitacao["seqipd"], qtd, session["usuario"],
                        )
                        oracle_db.adicionar_qtd_item_solicitacao(
                            codemp, codfil, numsol, item_existente_solicitacao["seqite"], qtd,
                        )
                        seqite_novo = item_existente_solicitacao["seqite"]
                    else:
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
                    sucesso_troca = f"Troca concluída: {item['codpro']} trocado por {produto['codpro']} - {produto['descricao']}."
                    return _render_detalhe(codemp, codfil, numsol, sucesso_troca=sucesso_troca)
                except pedido_ws.PedidoWebserviceError as e:
                    erro = (
                        f"O item substituído JÁ FOI CANCELADO, mas a inclusão do item novo falhou: {e} "
                        "Use o botão \"Inserir peça\" pra incluir o produto novo manualmente."
                    )

    return render_template(
        "trocar_item.html", codemp=codemp, codfil=codfil, numsol=numsol, seqite=seqite,
        item=item, item_pedido=item_pedido, produto=produto, qtd=qtd, codpro_novo=codpro_novo, erro=erro,
        diferenca_preco=diferenca_preco, alerta_preco=alerta_preco, autorizado_por=autorizado_por,
        mostrar_confirmacao=mostrar_confirmacao, item_existente_solicitacao=item_existente_solicitacao,
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

@app.route("/api/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/itens-entrega")
@login_obrigatorio
def api_itens_entrega(codemp, codfil, numsol):
    """Retorna JSON com itens disponíveis para entrega."""
    from flask import jsonify
    detalhe = oracle_db.get_solicitacao_detalhe(codemp, codfil, numsol)

    if not detalhe:
        return jsonify({"error": "Solicitação não encontrada"}), 404

    itens_entrega = []
    for i in detalhe["itens"]:
        qtd_atendida = float(str(i["qtd_atendida"]).replace(",","."))
        qtd_aberta = float(str(i["qtd_aberta"]).replace(",","."))
        qtd_movi = float(str(i["qtd_movimentada"]).replace(",","."))

        if qtd_atendida > qtd_movi:
            itens_entrega.append({
            "seqite": i["seqite"],
            "codpro2": i["codpro2"],
            "codpro1": i["codpro1"],
            "descricao": i["descricao"],
            "qtd_aberta": qtd_aberta,
            "qtd_atendida": qtd_atendida,
            "qtd_movi": qtd_movi,
            "seqipd": i["seqipd"]
        })

    return jsonify({"itens": itens_entrega})


@app.route("/solicitacao/<int:codemp>/<int:codfil>/<int:numsol>/entrega", methods=["GET", "POST"])
@login_obrigatorio
def entrega_item(codemp, codfil, numsol):
    detalhe = oracle_db.get_solicitacao_detalhe(codemp, codfil, numsol)
    
    # Filtra apenas itens com saldo a entregar
    itens_entrega = [
    i for i in detalhe["itens"]
    if float(i["qtd_atendida"]) > float(i["qtd_movimentada"])
]
    
    if request.method == "POST":
        seqites = [int(s) for s in request.form.getlist("seqites")]
        itens_selecionados = [i for i in itens_entrega if i["seqite"] in seqites]
        
        if itens_selecionados:
            try:
                # Chamar webservice com todos os itens de uma vez
                filexe = oracle_db.get_filial_pedido(codemp, codfil, detalhe["solicitacao"]["numped"])
                coddep = oracle_db.get_coddep_esperado(codemp, filexe)

                # Estorna a reserva ANTES de transferir - senão o webservice
                # calcula o saldo disponível já descontando a reserva feita
                # na conferência e recusa por "sem estoque".
                for item in itens_selecionados:
                    qtd_entrega = float(item["qtd_atendida"]) - float(item["qtd_movimentada"])
                    oracle_db.estornar_reserva_estoque(
                        codemp=codemp, coddep=coddep, codpro=item["codpro1"], qtd=qtd_entrega
                    )

                sucesso, datmovws, mensagem_retorno = pedido_ws.transferencia_produtos(
                    itens=itens_selecionados,
                    codemp=codemp,
                    codfil=codfil,
                    numped=detalhe["solicitacao"]["numped"],
                    usuario=session["usuario"],
                    filexe=filexe,
                )

                if sucesso:
                    # Atualizar item a item no banco de dados
                    for item in itens_selecionados:
                        qtd_entrega = float(item["qtd_atendida"]) - float(item["qtd_movimentada"])

                        oracle_db.atualizar_mvp(
                            codemp=codemp, codpro=item["codpro1"],
                            numped=detalhe["solicitacao"]["numped"], seqipd=item["seqipd"],
                            usuario=session["usuario"], datmovws=datmovws
                        )
                        oracle_db.atualizar_ipd(
                            codemp=codemp, filped=codfil, numped=detalhe["solicitacao"]["numped"],
                            seqipd=item["seqipd"], qtd=qtd_entrega
                        )
                        oracle_db.atualizar_entrega_e120sit(
                            codemp=codemp, codfil=codfil, numsol=numsol,
                            seqite=item["seqite"], qtd=qtd_entrega,
                            usuario=session["usuario"], datmovws=datmovws
                        )

                    local_db.registrar_acao(
                        tipo_acao="entrega_realizada",
                        usuario=session["usuario"],
                        codemp=codemp, codfil=codfil, numsol=numsol,
                        detalhes=f"Entrega de {len(itens_selecionados)} item(ns)"
                    )
                    return redirect(url_for("painel"))
                else:
                    erro = mensagem_retorno or "Falha na transferência de estoque"
            except Exception as e:
                erro = str(e)
        else:
            erro = "Nenhum item selecionado"
        
        return render_template(
            "entrega_item.html", codemp=codemp, codfil=codfil, numsol=numsol,
            itens=itens_entrega, erro=erro, detalhe=detalhe
        )
    
    return render_template(
        "entrega_item.html", codemp=codemp, codfil=codfil, numsol=numsol,
        itens=itens_entrega, detalhe=detalhe
    )

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5051)
