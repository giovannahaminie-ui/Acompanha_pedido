"""
Acompanha Pedido - Estoque Retífica

"""

from datetime import datetime
from functools import wraps
import os

from flask import Flask, render_template, request, redirect, url_for, session
from dotenv import load_dotenv

from db import local_db, oracle_db

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
    return render_template(
        "detalhe_solicitacao.html",
        solicitacao=dados["solicitacao"],
        itens=dados["itens"],
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
