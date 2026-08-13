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
  `usu_codetp`), não pela descrição. **Não fazem mais parte da tela de
  seleção inicial** (`/selecao`, que agora só pede empresa + filial) - são
  filtros do próprio painel (`/painel?tipo_servico=&etapa=`), aplicados via
  querystring/GET, sem precisar voltar pra tela de seleção pra trocar.
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
  saldo > 0. Observações (da solicitação, do pedido, da conferência e dos
  itens) ficam entre os cards de cliente/representante/solicitante e a
  tabela de itens - ver "Observação dos itens" abaixo.
- **5 botões por item** na segunda tela (a Observação saiu daqui - ver
  abaixo):
  - **Cancelar** - funcional. Só mexe na `T120SIT`, **sempre no item**
    (`usu_seqite`) - nunca cancela ou recria a solicitação inteira. Pede a
    quantidade a cancelar (default = qtd. aberta) e um motivo opcional, que
    é gravado no `usu_obsite` do próprio item cancelado. Não chama o
    webservice do pedido nem mexe no `E120IPD`. Ver regra de negócio
    detalhada abaixo.
  - **Equivalentes** - funcional, só consulta (sem gravação). Junta
    `E075EQI` (tabela real - não confundir com `E075EQUI`) + `E075PRO`
    (marca/descrição) + `E075DER` (derivação), e reaproveita a mesma lógica
    de saldo por depósito do item principal. Mostra o **profor**
    (`usu_codpro2` em `E075PRO`) em destaque, com o código interno
    (`proeqi`) como informação secundária. Tem botão pra copiar o profor
    pra área de transferência e já abrir a tela de **Trocar item** do item
    original (a pessoa cola o código copiado lá manualmente). O preço ainda
    aparece como placeholder (`—`) - fonte de preço a definir.
  - **Inserir peça** - fluxo completo (validação de produto/preço/depósito
    na `E075PRO`/`E081ITP`/`E210EST` - ver regra de negócio abaixo -,
    confirmação manual, chamada ao webservice `GravarPedidos_15` e inclusão
    na `T120SIT`), mas **precisa das credenciais do webservice**
    (`PEDIDO_WS_USER`/`PEDIDO_WS_PASSWORD` no `.env`) antes de gravar de
    verdade - sem elas, mostra erro claro.
  - **Trocar item** - mesmo fluxo do Inserir peça (mesma validação de
    produto/preço/depósito), mas cancela o item substituído no pedido + na
    solicitação antes de incluir o novo (marca `usu_indtrc='S'` no item
    novo). Mesma dependência das credenciais do webservice. Se o
    cancelamento for bem-sucedido mas a inclusão do item novo falhar, a
    tela avisa explicitamente que o item antigo já foi cancelado (evitar
    gravação "pela metade" silenciosa). A comparação de preço (substituído
    x novo) só aparece na tela quando a diferença passa da tolerância - ver
    abaixo.

- **Observação dos itens** (era um botão por item, agora é um único botão
  no cabeçalho da segunda tela, junto das outras observações). Continua
  gravando no `usu_obsite` da `usu_t120sit` - só que sem filtro de
  `usu_seqite`, então **aplica o mesmo texto em todos os itens da
  solicitação de uma vez** (`oracle_db.salvar_observacao_solicitacao`).
  **Depende de uma coluna nova no Oracle** (`usu_obsite`, ainda não criada
  em produção - ver "Ainda faltam" abaixo); enquanto não existir, a tela
  mostra aviso claro em vez de deixar o erro do Oracle estourar.

### Regra de negócio - cancelamento (`usu_sitite`)

Tanto o botão **Cancelar** quanto a etapa de cancelamento do item antigo
dentro do **Trocar item** passam pela mesma função
(`oracle_db.cancelar_item_solicitacao`), que roda **3 UPDATEs em sequência
na `usu_t120sit`, sempre filtrando pelo item (`usu_seqite`)** - nunca mexe
na solicitação inteira nem cria uma solicitação nova:

1. Soma a qtd. cancelada em `usu_qtdcan`, subtrai de `usu_qtdabe` e marca
   `usu_sitite = 2` (parcial) - só se o item ainda não estiver cancelado
   (`usu_sitite <> 3`).
2. Se `usu_qtdcan` bateu com `usu_qtdsol` (cancelou tudo que foi
   solicitado), `usu_sitite` vira `3` (cancelado).
3. Se ainda sobrou `usu_qtdsol > usu_qtdcan` (cancelamento parcial),
   garante `usu_sitite = 2`.

Os passos 2 e 3 são mutuamente exclusivos pela condição de quantidade, e
todos ignoram um item que já esteja com `usu_sitite = 3` (não "reabre" um
item já cancelado).

O motivo do cancelamento (campo opcional na tela de Cancelar) é gravado
depois dos 3 UPDATEs, no `usu_obsite` do mesmo item (`usu_seqite`) -
mesma coluna usada pela observação dos itens.

### Regra de negócio - validação de produto novo (preço + depósito)

Usada por **Inserir peça** e **Trocar item** antes de deixar confirmar a
inclusão/troca (`app.py`, rotas `inserir_item`/`trocar_item`). Além da
checagem de produto ativo já existente (`E075PRO`), agora para o processo e
avisa o usuário em 3 casos:

| Situação | Onde é checado | Mensagem |
|---|---|---|
| Produto não existe na `E075PRO` | `oracle_db.buscar_produto_preco` retorna `None` | "Produto X não foi encontrado." |
| Preço vigente (`prebas`, `E081ITP`) nulo ou 0 | `produto["preco"]` | "Produto X não possui preço - processo não pode continuar." |
| Sem ligação com o depósito da filial (`coddep`, `E210EST`) nulo/0/sem linha | `oracle_db.produto_tem_ligacao_deposito` | "Produto X não possui ligação para o depósito - processo não pode continuar." |

A ligação com o depósito usa a **mesma regra filial → depósito** já usada
no JOIN de `SQL_ITENS_SOLICITACAO` (`oracle_db._coddep_esperado`): empresa 1
com filial `L`→depósito `1`, `P`→`3`, `C`→`5`; empresas 5 e 12 sempre
depósito `1`.

### Regra de negócio - tolerância de preço na troca

No **Trocar item**, a comparação de preço (produto substituído x produto
novo) só aparece na tela quando a diferença passa da tolerância - dentro
dela, a tela pula direto pra uma confirmação simples, sem mostrar os
valores. Duas faixas (`app.py`):

- **10%** do preço atual (substituído) - `TOLERANCIA_PRECO_TROCA_PERCENTUAL`
  - regra geral, pra qualquer item.
- **R$ 200,00 fixo** - `TOLERANCIA_PRECO_TROCA_MOTOR_COMPLETO` - quando a
  solicitação é de **"motor completo"**, identificado pelo tipo de serviço
  da solicitação (`usu_ttipser.usu_destsv = "Completo"` -
  `TIPO_SERVICO_MOTOR_COMPLETO`, comparação case-insensitive).

Quando a diferença passa da tolerância, a tela exige um campo obrigatório
**"quem autorizou"** antes de deixar confirmar a troca - o texto é gravado
no `usu_obsite` do item **novo** (o que entrou no lugar do substituído),
junto com o valor da diferença.
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
