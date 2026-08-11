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
- **Segunda tela (detalhe da solicitação)**: além da qtd. solicitada, mostra
  qtd. atendida/aberta/cancelada/movimentada/MSO/devolvida (`T120SIT`),
  formatadas sem casa decimal (`1`, não `1.0`). Só aparecem depósitos com
  saldo > 0. Observações (da solicitação e do pedido) ficam entre os cards
  de cliente/representante/solicitante e a tabela de itens.
- **6 botões por item** na segunda tela:
  - **Cancelar** - funcional. Só mexe na `T120SIT` (move quantidade de
    aberta pra cancelada) - não chama o webservice do pedido nem mexe no
    `E120IPD`. Pede a quantidade a cancelar (default = qtd. aberta).
  - **Observação** - funcional, mas **depende de uma coluna nova no Oracle**
    (`usu_obsite` em `usu_t120sit`, ainda não criada em produção - ver
    "Ainda faltam" abaixo). Substituiu o antigo botão de Comentário (que
    ficava local em SQLite, `local_db.py`) - agora é campo oficial do
    Sapiens. Enquanto a coluna não existir, a tela mostra um aviso claro em
    vez de estourar erro do Oracle.
  - **Equivalentes** - funcional, só consulta (sem gravação). Junta
    `E075EQI` (tabela real - não confundir com `E075EQUI`) + `E075PRO`
    (marca/descrição) + `E075DER` (derivação), e reaproveita a mesma lógica
    de saldo por depósito do item principal. O preço ainda aparece como
    placeholder (`—`) - fonte de preço a definir.
  - **Inserir peça** - fluxo completo (validação de produto/preço na
    `E075PRO`/`E081ITP`, confirmação manual da diferença, chamada ao
    webservice `GravarPedidos_15` e inclusão na `T120SIT`), mas **precisa das
    credenciais do webservice** (`PEDIDO_WS_USER`/`PEDIDO_WS_PASSWORD` no
    `.env`) antes de gravar de verdade - sem elas, mostra erro claro.
  - **Trocar item** - mesmo fluxo do Inserir peça, mas cancela o item
    substituído no pedido + na solicitação antes de incluir o novo (marca
    `usu_indtrc='S'` no item novo). Mesma dependência das credenciais do
    webservice. Se o cancelamento for bem-sucedido mas a inclusão do item
    novo falhar, a tela avisa explicitamente que o item antigo já foi
    cancelado (evitar gravação "pela metade" silenciosa).
- **Webservice `GravarPedidos`** (`db/pedido_ws.py`) - cliente SOAP (`zeep`)
  isolado num módulo próprio, usado só por Inserir/Trocar. Endpoint e
  credenciais já configurados no `.env` (`PEDIDO_WS_WSDL`/`PEDIDO_WS_USER`/
  `PEDIDO_WS_PASSWORD`). Testado de verdade em duas frentes:
  - Leitura (`obterItensPedido`) - confirmado, autenticação funciona.
  - Gravação (`GravarPedidos_15`) - **confirmado só o caminho "pedido novo +
    item novo"** (`opeExe="I"` em pedido e produto), testado via SoapUI fora
    deste código e criou o pedido real **781740** (empresa 2) - vale conferir
    se precisa ser cancelado/estornado, já que não era um pedido de teste
    dedicado. O caminho que Inserir/Trocar realmente usam - **incluir item
    num pedido que já existe** (`pedido.opeExe="A"` + `produto.opeExe="I"`) e
    **cancelar item existente** (`pedido.opeExe="A"` + `produto.opeExe="A"`,
    via `seqIpd`) - ainda não foi confirmado por teste real, só por
    inferência do padrão Senior (I=incluir, A=alterar). **Não usar Inserir
    peça/Trocar item em produção antes de validar isso.**

## Ainda faltam (não implementados neste esqueleto)

- Terceira tela (mensagem simples com informações da solicitação).
- **Coluna `usu_obsite`** (ou nome equivalente) na `usu_t120sit` do Oracle -
  sem ela, o botão Observação não grava. DDL sugerida:
  `ALTER TABLE sapiens.usu_t120sit ADD usu_obsite VARCHAR2(250);`
- **Validar `opeExe="A"` (pedido) + `opeExe="I"`/`"A"` (produto) contra um
  pedido real que já existe** - o único teste real feito até agora criou um
  pedido do zero (`opeExe="I"` nos dois níveis), que é um cenário diferente
  do que Inserir/Trocar precisam.
- Fonte do preço exibido no card de equivalentes.
- Definição de quem bate o crachá na retirada (Atendido/parcial) - cogitada
  leitura por câmera (celular/tablet), a estruturar depois.

## Estrutura

```
acompanha_pedido/
  app.py                  # rotas Flask
  requirements.txt
  .env                     # credenciais do Oracle + webservice + chave do Flask (não versionado)
  .gitignore
  db/
    local_db.py            # SQLite - perfis (G/B/U)
    oracle_db.py            # queries do Sapiens
    pedido_ws.py            # cliente SOAP do GravarPedidos (troca/inserção)
  templates/
    base.html
    login.html
    selecao.html
    painel.html
    detalhe_solicitacao.html
    assumir_solicitacao.html
    observacao_item.html
    cancelar_item.html
    inserir_item.html
    trocar_item.html
    equivalentes_item.html
    admin_perfis.html
  static/
    css/style.css
```
