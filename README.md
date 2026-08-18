# Acompanha Pedido — Estoque Retífica

> Status: painel, detalhe da solicitação, Cancelar/Trocar/Inserir peça,
> Pedido na loja e Conferência com reserva funcionando. Solicitação de
> compra **não funciona ainda**. Lista completa de pontos em aberto na
> seção 8.

---

## 1. Contexto

- 4 empresas possuem depósito próprio: **1** Retífica, **2** RTL (distribuidora
  de peças), **5** Transmissões, **12** Tiête Car.
- `codpro1` da Retífica é o código **interno**; `codpro2` é do **fabricante**.
  Na RTL é o inverso: `codpro1` é do fabricante, `codpro2` é o interno. A tela
  sempre exibe os dois lado a lado.
- Filial: `usu_filexe` (em `E120PED`) guarda **letra**, não código numérico —
  `L` Londrina, `P` Prudente, `C` Cambé (lista `FILIAIS` em `app.py`). Filial
  nova = só adicionar a letra na lista.
- Depósito por empresa/filial (`oracle_db.get_coddep_esperado`): empresa 1 —
  `L`→`1`, `P`→`3`, `C`→`5`; empresa 2 (RTL) — `L`→`1`, `P`→`2` (**não
  confirmado contra dado real**); empresas 5 e 12 — sempre `1`.

## 2. Fluxo de status

```
Solicitado  →  Em separação  →  Atendido / parcial
```

Classificação por `usu_sitsol` (`oracle_db._classificar_por_etapa`): `1,2` =
Solicitado; `5` = Em separação; qualquer outro valor não excluído pelo
filtro = Atendido/parcial. A listagem (`SQL_SOLICITACOES`) filtra
`usu_sitsol NOT IN (3,6,9)` e só traz os últimos 180 dias.

**Assumir** (Solicitado → Em separação): duplo clique no painel → pede
código de usuário do Sapiens → grava `usu_sitsol=5`, `usu_datsep`,
`usu_horsep`, `usu_ususep`.

## 3. Perfis de acesso

SQLite local (`db/local_db.py`, tabela `usuarios_perfil`) — não existe no
Sapiens.

| Perfil | Descrição |
|---|---|
| **G** — Gerência | Acesso total; único perfil que entra em `/admin/perfis` |
| **B** — Boqueta | Separa as solicitações |
| **U** — Usinagem | Solicita as peças |
| *(sem perfil)* | Usuário válido no Sapiens, ainda sem perfil aqui |

Perfil só é checado de fato em `/admin/perfis`. **Nenhuma outra ação
(assumir/cancelar/inserir/trocar/pedido na loja/conferência) restringe por
perfil hoje** — qualquer usuário autenticado executa todas.

## 4. Login

Código de usuário do Sapiens (`E099USU`, `situsu='A'`) — não existe senha
própria (`oracle_db.verificar_login`). Perfil gerenciado em `/admin/perfis`,
restrito a quem já tem perfil `G`.

## 5. Telas

### 5.1 Seleção inicial (`/selecao`)

Escolhe **empresa** e **filial**. Tipo de serviço e etapa são filtros do
painel (`/painel?tipo_servico=&etapa=`), não fazem parte dessa tela.

### 5.2 Painel principal (`/painel`)

3 colunas fixas (Solicitado / Em separação / Atendido-parcial). Cada linha
mostra data/hora, filial, O.S., número da solicitação e nome (não código)
do solicitante/separador.

### 5.3 Detalhe da solicitação (`/solicitacao/<codemp>/<codfil>/<numsol>`)

**Cabeçalho**: O.S., filial, número, data/hora, status, cliente, cidade,
solicitante, separador, 4 campos de observação (solicitação/pedido/
conferência/itens — este último edita todos os itens não cancelados de uma
vez, texto sempre concatenado, nunca sobrescreve). Cards com clamp de 4
linhas + modal "Ver mais" pra texto longo.

**Tabela de itens** — título e conteúdo centralizados (classe própria
`.tabela-itens`, não afeta `admin_perfis.html`/`equivalentes_item.html`, que
também usam `.table-card`). Observação por item aparece como balão (💬)
clicável (prévia por hover, texto completo no mesmo modal do cabeçalho) em
vez de texto cru na célula. Ícones de ação numa `<div class="acoes-grid">`
(grid 2 colunas, sempre "dois por linha"). Botão de copiar ao lado do
"Cód. Fab." (pra colar direto no campo de código da Conferência).

> Nunca usar `display:flex`/`grid` direto num `<td>` dessa tabela — tira a
> célula do comportamento normal de tabela (fundo da linha não pinta certo).
> Sempre envolver com uma `<div>` dentro do `<td>`.

**Ações por item:**

- **Cancelar** (`/item/<seqite>/cancelar`) — sempre no item, nunca na
  solicitação inteira. Só pede motivo (sempre cancela tudo que está aberto).
  Sem movimentação (`usu_qtdmov=0`): cancela o item inteiro
  (`usu_sitite=3`). Com movimentação: cancela só o aberto, preserva
  `usu_qtdate`, `usu_sitite` vira `3` ou `2`. `usu_obsite` recebe mensagem
  automática (data/hora/usuário/motivo), **substitui** o texto anterior.
- **Equivalentes** (`/item/<seqite>/equivalentes/<codpro>`) — só consulta.
  Junta `E075EQI`+`E075PRO`+`E075DER`, preço vem da `E081ITP`.
- **Inserir peça** (`/item/<seqite>/inserir`) — 2 etapas: valida
  produto/preço/depósito → confirma → `GravarPedidos_15` (`opeExe="A"`,
  pedido já existente) → só grava na solicitação se o webservice confirmar.
- **Trocar item** (`/item/<seqite>/trocar`) — mesma validação, cancela o
  substituído no pedido+solicitação, depois inclui o novo. Se cancelar
  funcionar mas incluir falhar, avisa explicitamente (evita gravação pela
  metade). Tolerância de preço: 10% (ou R$200 fixo se "motor completo") —
  acima disso exige campo "quem autorizou".
- **Histórico** — rota existe (`/item/<seqite>/historico`,
  `historico_item.html`: situação, quem/quando solicitou, vínculo com
  pedido/solicitação de compra, quantidades, log de observações), mas
  **sem atalho na tabela** (removido a pedido).

### 5.4 Administração de perfis (`/admin/perfis`)

Só acessível a quem tem perfil `G`. Lista todos os usuários ativos do
Sapiens (~680 pessoas), não só quem já logou.

### 5.5 Pedido na loja (`/solicitacao/<codemp>/<codfil>/<numsol>/pedido_loja`, POST)

Checkbox por item na tabela + botão fora dela (contador dinâmico, só libera
com 1+ marcado). 1ª submissão mostra revisão com quantidade editável por
item; confirmar executa o webservice item por item, com resultado
individual + número do pedido gerado (botão de copiar).

- **Destino fixo** (`oracle_db.dados_pedido_loja`): empresa 1 filial `P` →
  `codcli=990110572, codemp=2, codfil=2, coddep=2`; empresa 1 outras
  filiais → `codcli=1, codemp=2, codfil=1, coddep=1`; empresa 5 →
  `codcli=990108064`; empresa 12 → `codcli=990143288` (ambas `codemp=2,
  codfil=1, coddep=1`).
- **Sugestão de quantidade**: se `qtd_aberta > qtdest` (saldo da loja),
  sugere `qtdest + (qtd_aberta - qtd_mso)`; senão `qtd_aberta`.
- **Bloqueia se não tiver saldo em nenhum depósito do grupo**.
- **Webservice** (`GravarPedidos_15`): pedido sempre **novo**
  (`opeExe="I"`, não `"A"`) — Sapiens gera o número, função recebe `codCli`
  em vez de `numPed`. `tnsPro` fixo `"90100"`. `resEst="S"`.
  `ignorarPedidoBloqueado="S"` **só nesse fluxo** (pula checagem de crédito
  — `codCli` é conta fixa de transferência interna, não cliente real; não
  se aplica a Inserir peça/Trocar item).
- Depois do sucesso, incrementa `usu_qtdmso` do item.
- Tentativa que falha no meio deixa pedido órfão no Sapiens (cabeçalho sem
  item) — sem rotina de limpeza automática.

### 5.6 Solicitação de compra (`/solicitacao/<codemp>/<codfil>/<numsol>/solicitacao_compra`, POST)

**Não funciona.** Mesmo padrão de checkbox+lote+revisão do Pedido na loja.
Botão fica visível na tela por decisão consciente.

- `oracle_db.proximo_numsol_compra`: `SELECT NVL(MAX(numsol),0)+1 FROM
  E405SOL WHERE codemp=:codemp` (`E405SOL` é tabela padrão do Sapiens, sem
  prefixo `usu_`).
- Webservice `GerarSolicitacaoCompra_3`, credenciais próprias
  (`COMPRA_WS_*` no `.env`, separado do `GravarPedidos_15`). `codPro`
  enviado é `item["codpro1"]` (interno da própria empresa — diferente do
  Pedido na loja, que manda `codpro2` porque ali o `codEmp` do webservice é
  a RTL).
- **`numPed` corrigido** (2026-08-18): era enviado igual a `numsol_compra`
  (a própria solicitação recém-gerada); agora manda `item["numped"]` — o
  número da O.S./pedido real vinculado ao item (mesmo valor já usado pra
  achar `filexe`/`cod_dep` logo acima na rota). Confirmado no log
  (`numPed=129795` ≠ `numSol=26`).
- **Erro atual, mesmo com `numPed` corrigido**: "Problemas ao encontrar
  Família/Produto/Unidade de medida nas Tabelas de Familia/Produto/UM
  '<codpro>'". Investigado direto no Oracle (2026-08-18) pro caso do log:
  produto `50017649`, empresa 1 — **cadastro bate**: `E075PRO` (produto
  ativo, `codFam=50559`, `uniMed=UN`), `E012FAM` (família ativa,
  `uniMed=UN`, mesma família do produto), `E210EST` (produto tem linha no
  depósito 1 enviado). Não é falta de cadastro de produto/família/UM — o
  erro vem de outra validação interna do serviço (Senior/Sapiens),
  possivelmente ligada a `codTns` ("91400", fixo no código) não liberado
  pra essa família/depósito, ou a algum parâmetro do G5 fora do alcance de
  uma consulta SQL. Precisa isolar via SoapUI (variar `codTns`/`filPed`
  com o mesmo produto) ou verificar parametrização de TNS no G5.
- Cada tentativa (mesmo com erro) já gera uma linha órfã em `E405SOL`.

### 5.7 Conferência com reserva (`/solicitacao/<codemp>/<codfil>/<numsol>/conferencia`)

Tela dedicada, pensada pra ficar aberta com leitor de código de barras:
campo de código + quantidade conferida (`qtdcon`), confirma um item por
vez, campo limpa sozinho pro próximo.

1. **Resolve o código** (`resolver_codpro_conferencia`) — tenta em ordem:
   `E075DER` (derivação, `CodBa2`), `E075BAR` (código de barras), `E075PRO`
   (direto, interno ou fabricante, `sitpro='A'`, `codori IN
   ('40','50','60')`).
2. **Acha o item em aberto** que bate com esse produto
   (`usu_sitite IN (1,2)`, ainda não totalmente atendido).
3. **Valida** `qtdcon <= qtd_aberta`.
4. **3 UPDATEs**: `USU_T120SIT` (soma em `usu_qtdate`, subtrai de
   `usu_qtdabe`); `E210EST` (soma em `qtdres` no depósito certo); `E120IPD`
   (soma em `qtdres`, marca `resest='S'`). Não muda `usu_sitite`.

**Não valida saldo físico em estoque antes de reservar** — hoje reserva
mesmo com `qtdest=0` (diferente do Pedido na loja, que já bloqueia isso).

## 6. Webservices (`db/pedido_ws.py`)

Todo envelope (enviado/recebido) é logado em `logs/pedido_ws_envelopes.log`
e salvo separado em `logs/xml/` (nomeado com timestamp + operação).

**`GravarPedidos_15`** (Inserir peça, Trocar item, Pedido na loja):
- `opeExe`: `"I"` = incluir, `"A"` = alterar. Pedido normalmente `"A"`
  (já existe), exceto Pedido na loja (`"I"`, sempre novo). Produto `"I"`
  pra item novo, `"A"` pra alterar/cancelar existente (via `seqIpd`).
- `qtdPed`/`qtdCan`/`preUni` são `xs:string` — exige vírgula decimal
  (`"384,41"`), não ponto (`_fmt_numero`).
- `erroExecucao` vazio **não** significa sucesso — o sucesso real está em
  `respostaPedido.tipRet == 1`. Erro de negócio às vezes só aparece em
  `gridPro.retorno` (por item), não no `msgRet` do pedido.
- `ignorarPedidoBloqueado="S"` só é usado no Pedido na loja (ver 5.5).

**`GerarSolicitacaoCompra_3`** (Solicitação de compra) — ainda não
funciona, ver 5.6.

## 7. Stack técnica

- Backend: Python / Flask
- Banco principal: Oracle (Sapiens ERP), via `oracledb` (modo thick)
- Banco local: SQLite (perfis — `db/acompanha_pedido.sqlite3`, criado
  automaticamente)
- Webservices: SOAP (`zeep`) — `GravarPedidos_15` e `GerarSolicitacaoCompra_3`
- Frontend: HTML/Jinja2 + CSS próprio (`static/css/style.css`)
- Hospedagem: VM 24h já existente. `app.py` roda com `debug=False` — **não
  recarrega sozinho** quando um arquivo muda, precisa reiniciar o processo
  manualmente depois de qualquer deploy.

## 8. Pontos em aberto

- **Restringir ações por perfil** — hoje qualquer usuário logado executa
  tudo (ver seção 3).

- **Definir quem/como registra "Atendido/parcial"** fora da Conferência com
  reserva — se ela substitui essa pendência ou se ainda falta algo.
  DDL: `ALTER TABLE sapiens.usu_t120sit ADD usu_obsite VARCHAR2(250);`

- `SQL_PRODUTO_ATIVO_PRECO` traz uma regra de depósito por `codfil`
  (`10`/`1001`→`3`, senão `1`) que não é usada em lugar nenhum — avaliar se
  vale remover.

- **Crachá com código de barras (Code128, 10 dígitos)** — em discussão, nada
  implementado. O código não é o `codusu` do Sapiens direto, precisa de
  tabela de-para (crachá → `codusu`) que ainda não existe — local (SQLite)
  ou importada de outro sistema, a definir.

## 9. Estrutura

```
acompanha_pedido/
  app.py                  # rotas Flask
  requirements.txt
  .env                     # credenciais do Oracle + dos 2 webservices + chave do Flask (não versionado)
  .gitignore
  logs/
    pedido_ws_envelopes.log
    xml/
  db/
    local_db.py            # SQLite - perfis (G/B/U)
    oracle_db.py            # queries do Sapiens
    pedido_ws.py            # cliente SOAP - GravarPedidos + GerarSolicitacaoCompra
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
    pedido_loja_lote.html
    solicitacao_compra_lote.html
    conferencia_reserva.html
    historico_item.html          
  static/
    css/style.css
```
