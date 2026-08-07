# Acompanha Pedido — código inicial

Esqueleto Flask das telas que foi estruturado: login, seleção inicial,
painel principal (3 colunas), segunda tela (detalhe da solicitação com
saldo de estoque) e administração de perfis.

> Para o resumo completo das decisões de projeto (fluxo, perfis, regras de
> acesso), ver o `README.md` na pasta principal do projeto
> (`Estoque - Retifica`).


## Estado atual

- As consultas de **painel**, **detalhe da solicitação**, **assumir
  solicitação** e **login** já têm implementação real em `db/oracle_db.py`
  (usando suas queries originais), conectadas direto no Oracle de produção
  via `.env` (`ORACLE_DSN` / `ORACLE_USER` / `ORACLE_PASSWORD`).
- **Solicitante / separador / retirado por** no painel mostram o nome
  (`nomusu` de `E099USU`), não o código - resolvido via subquery escalar
  (um mesmo `codusu` tem uma linha por empresa em `E099USU`, às vezes com
  nome divergente; pegamos o nome mais longo/completo como critério).
- **Filtro de filial**: `usu_filexe` (em `e120ped`) guarda letra, não o
  código numérico de filial - `L` Londrina, `P` Prudente, `C` Cambé
  (`FILIAIS` em `app.py`). Se aparecer uma filial nova nos dados, é só
  adicionar a letra correspondente nessa lista.
- **Filtro de tipo de serviço / etapa**: as listas vêm dinamicamente do
  Oracle (`usu_ttipser` / `usu_tetppro`) via `get_tipos_servico()` /
  `get_etapas()`, e o filtro compara pelo código (`usu_codtsv` /
  `usu_codetp`), não pela descrição.
- O perfil (G/B/U) de cada usuário fica em `db/acompanha_pedido.sqlite3`
  (criado automaticamente na primeira execução). Usuário novo entra sem
  perfil = modo visualização.
- A tela de administração de perfis (`/admin/perfis`) só é acessível para
  quem tem perfil `G`. Ela lista **todos os usuários ativos do Sapiens**
  (`situsu='A'` em `E099USU`, ~680 pessoas), não só quem já logou - a
  gerência pode classificar o perfil de qualquer um a qualquer momento.
  Pra liberar o primeiro usuário Gerência (ninguém tem perfil ainda na
  primeira vez), dá pra fazer direto pelo SQLite.

## Ainda faltam (não implementados neste esqueleto)

- Terceira tela (mensagem simples com informações da solicitação).
- Ações reais na segunda tela (hoje é só consulta).
- Definição de quem bate o crachá na retirada (Atendido/parcial).

## Estrutura

```
acompanha_pedido/
  app.py                  # rotas Flask
  requirements.txt
  .env                     # credenciais do Oracle + chave do Flask (não versionado)
  .gitignore
  db/
    local_db.py            # SQLite - tabela de perfis (G/B/U)
    oracle_db.py            # queries do Sapiens
  templates/
    base.html
    login.html
    selecao.html
    painel.html
    detalhe_solicitacao.html
    assumir_solicitacao.html
    admin_perfis.html
  static/
    css/style.css
```
