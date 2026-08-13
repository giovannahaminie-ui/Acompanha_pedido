# Acompanha Pedido — Estoque Retífica

Sistema em Flask + Oracle (Sapiens) + SQLite local que substitui a tela atual
de **Acompanhamento de Solicitações de Peças**. Fluxo: a usinagem (Retífica)
solicita uma peça no estoque; alguém da boqueta assume a solicitação e
separa; depois a peça é retirada.

> Status: telas e regras de negócio principais implementadas e conectadas ao
> Oracle de produção. Alguns pontos ainda dependem de configuração ou
> validação antes de ir pra produção — ver "Ainda faltam / pendências".

---

## 1. Contexto

- 4 empresas possuem depósito próprio: **1** Retífica, **2** RTL (distribuidora
  de peças, onde a tela atual está hospedada), **5** Transmissões, **12** Tiête
  Car.
- `codpro1` da Retífica é o código **interno**; `codpro2` é do **fabricante**.
  Na RTL é o inverso: `codpro1` é do fabricante, `codpro2` é o interno. A tela
  sempre exibe os dois lado a lado.
- Filial: `usu_filexe` (em `E120PED`) guarda **letra**, não código numérico —
  `L` Londrina, `P` Prudente, `C` Cambé (lista `FILIAIS` em `app.py`). Filial
  nova = só adicionar a letra na lista.

## 2. Fluxo de status

```
Solicitado  →  Em separação  →  Atendido / parcial
```

Classificação por `usu_sitsol` (`oracle_db._classificar_por_etapa`):

| `usu_sitsol` | Coluna no painel |
|---|---|
| 1, 2 | Solicitado |
| 5 | Em separação |
| qualquer outro valor não excluído pelo filtro | Atendido / parcial |

A listagem (`SQL_SOLICITACOES`) já filtra `usu_sitsol NOT IN (3,6,9)` e só
traz solicitações dos últimos 180 dias (`usu_datsol >= sysdate-180`).

- **Ação "assumir"** (Solicitado → Em separação): duplo clique no item do
  painel → pede o código de usuário do Sapiens de quem está assumindo →
  grava `usu_sitsol=5`, `usu_datsep`, `usu_horsep`, `usu_ususep`
  (`oracle_db.assumir_solicitacao`).
- **Atendido / parcial**: ainda não tem tela/ação própria neste sistema —
  quem registra a retirada e como (leitura de crachá, etc.) segue em aberto.

## 3. Perfis de acesso

Guardados localmente (SQLite, `db/local_db.py`, tabela `usuarios_perfil`) —
não existem no Sapiens.

| Perfil | Descrição |
|---|---|
| **G** — Gerência | Acesso total; único perfil que entra em `/admin/perfis` |
| **B** — Boqueta | Separa as solicitações |
| **U** — Usinagem | Solicita as peças |
| *(sem perfil)* | Usuário válido no Sapiens, ainda sem perfil aqui |

**Importante:** hoje o perfil só é checado de fato em `/admin/perfis` (só
`G` acessa — `app.py`, `admin_perfis`/`salvar_perfil`) e usado em
`base.html` só pra mostrar ou esconder o atalho de administração no menu.
As ações de **assumir**, **cancelar**, **inserir peça** e **trocar item**
**não checam o perfil de quem está logado** — qualquer usuário autenticado
(mesmo sem perfil) consegue executá-las hoje. Se a intenção é restringir por
perfil (B só assume/separa, U só solicita, etc.), isso ainda precisa ser
implementado nas rotas.

## 4. Login e administração de perfis

- **Autenticação**: código de usuário do Sapiens (`E099USU`, `situsu='A'`) —
  não existe senha própria, só o código (`oracle_db.verificar_login`).
- **Perfil**: gerenciado em `/admin/perfis`, restrito a quem já tem perfil
  `G`. Lista **todos os usuários ativos do Sapiens** (~680 pessoas), não só
  quem já logou.
- **Usuário sem perfil**: loga normalmente, mas sem nenhum botão de ação
  bloqueado por hoje (ver ressalva na seção 3).

## 5. Telas

### 5.1 Seleção inicial (`/selecao`)

Escolhe **empresa** e **filial**. Tipo de serviço e etapa **não** fazem mais
parte dessa tela — viraram filtros do próprio painel
(`/painel?tipo_servico=&etapa=`, aplicados via querystring, sem precisar
voltar à seleção pra trocar). Atalho "Trocar seleção" no cabeçalho do painel
reabre esse menu.

### 5.2 Painel principal (`/painel`)

3 colunas fixas (Solicitado / Em separação / Atendido-parcial), pensado para
ficar exibido tipo TV/monitor de parede. Cada linha mostra data/hora, filial,
O.S., número da solicitação e o nome relevante da etapa (solicitante,
separador). Solicitante/separador mostram **nome** (`nomusu` de `E099USU`),
não o código — resolvido por subquery escalar (um `codusu` pode ter mais de
uma linha em `E099USU`; usamos o nome mais longo como critério de
desempate).

### 5.3 Detalhe da solicitação (`/solicitacao/<codemp>/<codfil>/<numsol>`)

Aberta ao clicar num item da coluna "Em separação". Duas partes:

1. **Cabeçalho** (formato do relatório RVPE134GER): O.S., filial, número da
   solicitação, data/hora, status, cliente, cidade, solicitante, separador,
   e 4 campos de observação (da solicitação, do pedido, da conferência, dos
   itens — este último com botão de editar, aplica em todos os itens **não
   cancelados** de uma vez). O texto novo é **concatenado** com o que já
   existia (não sobrescreve), numa linha com data/hora/usuário
   (`oracle_db.salvar_observacao_solicitacao`) — itens já cancelados
   (`usu_sitite=3`) ficam de fora, tanto pra gravar quanto pra reler.
   Cada card de observação mostra até 4 linhas de texto (clamp);
   se o texto for maior, aparece um botão "Ver mais" que abre o texto
   completo num modal — os 4 cards ficam com altura proporcional entre si em
   vez de esticarem conforme o tamanho do texto (`static/css/style.css`,
   `.info-card-value.clamp` / `.obs-modal-*`).
2. **Tabela de itens**, com qtd. solicitada/atendida/aberta/cancelada/
   movimentada/MSO/devolvida (`T120SIT`, sem casa decimal quando o valor é
   inteiro) e saldo por depósito (só depósitos com saldo > 0, variam
   conforme empresa/filial do item).

**4 ações por item:**

- **Cancelar** (`/item/<seqite>/cancelar`) — só mexe na `T120SIT`, sempre no
  item (`usu_seqite`), nunca na solicitação inteira. **Não pede mais
  quantidade** — sempre cancela tudo que está aberto (o quanto exatamente
  depende de o item já ter movimentação ou não, ver seção 6); só pede
  motivo, usado pra gerar a mensagem de `usu_obsite`. Não chama webservice,
  não mexe no `E120IPD`. Regra de negócio detalhada na seção 6.
- **Equivalentes** (`/item/<seqite>/equivalentes/<codpro>`) — só consulta,
  sem gravação. Junta `E075EQI` + `E075PRO` (marca/descrição) + `E075DER`
  (derivação), reaproveita a mesma lógica de saldo por depósito. Preço vem
  da `E081ITP` (`SQL_PRECO_EQUIVALENTE`, pelo `proeqi`), mesma regra fixa
  (`codtpr='001'`, `datini` por empresa) que `buscar_produto_preco` usa pra
  qualquer outro produto — **não** vem mais de `E075EQI.conpr1`/`conpr2`
  (chegaram a ser usados, mas os valores reais eram `1,00`/`0,00`/vazio,
  não batiam com preço de peça de verdade).
- **Inserir peça** (`/item/<seqite>/inserir`) — fluxo em duas etapas na
  mesma rota: 1ª submissão valida produto/preço/depósito e mostra
  confirmação manual; 2ª (com `confirmar` no form) chama o webservice
  `GravarPedidos_15` e só grava na `T120SIT` se o webservice confirmar
  sucesso.
- **Trocar item** (`/item/<seqite>/trocar`) — mesma validação do Inserir
  peça, mas primeiro cancela o item substituído no pedido + na solicitação,
  depois inclui o novo. Se o cancelamento funcionar mas a inclusão do novo
  falhar, a tela avisa explicitamente que o item antigo já foi cancelado
  (evita gravação "pela metade" silenciosa). O item novo entra com
  `usu_sitite=1` fixo — hoje não fica mais registrado no Oracle se o item
  veio de uma troca ou de uma inclusão direta (ver seção 6).

### 5.4 Administração de perfis (`/admin/perfis`)

Só acessível a quem tem perfil `G`.

## 6. Regras de negócio

### Cancelamento (`usu_sitite`)

**Botão Cancelar** (`oracle_db.cancelar_item_solicitacao`) e **cancelamento
do item antigo dentro de Trocar item** (`oracle_db.cancelar_qtd_item_
solicitacao_troca`) usam funções e regras **diferentes** hoje — não
compartilham mais a mesma lógica.

**Botão Cancelar** — sempre no item (`usu_seqite`), nunca na solicitação
inteira. A tela não pede mais quantidade (sempre cancela tudo que está
aberto) — só pede o motivo. Dois caminhos, decididos pela `usu_qtdmov`
atual do item (`SQL_ITEM_MOVIMENTACAO`):

- **Sem movimentação** (`usu_qtdmov = 0`) — cancela o item inteiro de uma
  vez: `usu_sitite=3`, `usu_qtdcan=usu_qtdsol`, zera `usu_qtdate` e
  `usu_qtdabe`.
- **Com movimentação** (`usu_qtdmov <> 0`) — cancela só o que está aberto:
  soma `usu_qtdabe` em `usu_qtdcan`, zera `usu_qtdabe`, `usu_sitite` vira
  `3` se isso cancelou tudo que sobrava ou `2` se ainda restou algo aberto.
  **Preserva `usu_qtdate`** (não apaga o que já foi atendido/movimentado).

Nos dois casos, `usu_obsite` recebe uma mensagem **gerada automaticamente**
com data/hora/usuário/motivo (ex: `"Cancelado em 13/08/2026 09:20 por
12345 - motivo: peça descontinuada"`) — **substitui** o texto anterior, não
concatena (diferente da Observação, ver abaixo).

**Troca de item** (cancelamento do item substituído) — função separada
(`cancelar_qtd_item_solicitacao_troca`), porque a troca pode ser parcial
(ex: 3 unidades solicitadas, troca só 1 — as outras 2 continuam em aberto
no item original). Mantém o padrão de 3 UPDATEs em sequência que o
Cancelar usava antes: soma a qtd. trocada em `usu_qtdcan`/subtrai de
`usu_qtdabe` e marca `usu_sitite=2`; se bateu com `usu_qtdsol` vira `3`;
senão garante `2`. Não mexe em `usu_obsite`.

### Validação de produto novo (preço + depósito)

Usada por **Inserir peça** e **Trocar item** antes de confirmar. Desde a
consolidação da query (`SQL_PRODUTO_ATIVO_PRECO`, junta `E075PRO` + `E081ITP`
+ `E210EST` + `E120IPD` numa única consulta), o preço e o produto são
validados juntos; a checagem de depósito continua numa função separada:

| Situação | Onde é checado | Mensagem |
|---|---|---|
| Produto não existe ou está inativo na `E075PRO` | `buscar_produto_preco` retorna `None` (o `WHERE p.sitpro='A'` da query já filtra os dois casos juntos) | "Produto X não foi encontrado." — **não distingue mais** "não encontrado" de "inativo" (antes distinguia) |
| Preço vigente (`prebas`, `E081ITP`, `codtpr='001'` fixo) nulo/0 | `produto["preco"]` | "Produto X não possui preço - processo não pode continuar." |
| Sem ligação com o depósito da filial (`E210EST`) | `produto_tem_ligacao_deposito` (função separada, `_coddep_esperado`) | "Produto X não possui ligação para o depósito - processo não pode continuar." |

`codtpr` (tabela de preço) é **fixo em `'001'`** na query nova — antes vinha
dinamicamente do `codtab` do pedido (com fallback pra `001` quando em
branco). Como ~40 mil de ~48 mil pedidos amostrados já caíam no fallback
`001` na prática (ver nota antiga), isso muda o resultado só pra pedidos com
`codtab` explicitamente diferente de `001`.

A checagem de depósito (`produto_tem_ligacao_deposito`) usa a regra filial →
depósito do JOIN de itens da solicitação: empresa 1 com filial `L`→depósito
`1`, `P`→`3`, `C`→`5`; empresas 5 e 12 sempre depósito `1`; **empresa 2
(RTL)** com filial `L`→depósito `1`, `P`→`2` — essa última **inferida** do
`CASE` de `SQL_SALDO_ESTOQUE_PADRAO` (`"RTL LD"`/`"RTL PP"`), **ainda não
confirmada contra dado real** (antes disso não existia regra nenhuma pra
empresa 2 aqui, e toda solicitação da RTL caía direto em "sem ligação").

A função `SQL_DEPOSITO_LIGADO_PRODUTO` também passou a resolver o produto em
`E075PRO` antes de checar a `E210EST` — aceita tanto o código interno quanto
o do fabricante (`TO_CHAR(p.codpro)=:codpro OR p.usu_codpro2=:codpro`, mesmo
padrão de `SQL_PRODUTO_ATIVO_PRECO`), e usa sempre o interno pra bater com a
`E210EST` (que é indexada pelo interno). Antes comparava a `E210EST`
direto com o texto digitado, o que sempre falhava quando a pessoa colava o
código do fabricante (ex: vindo da tela de Equivalentes, que mostra
justamente o `profor`/fabricante em destaque) — dava "sem ligação para o
depósito" mesmo o produto tendo saldo de verdade.

**Atenção:** a query `SQL_PRODUTO_ATIVO_PRECO` também traz um `coddep` (via
`E210EST`), mas com uma regra *diferente* — por `codfil` numérico
(`10`/`1001` → depósito `3`, senão `1`) — que não é usada em lugar nenhum
hoje (o depósito de verdade usado é sempre o de `produto_tem_ligacao_deposito`).
Duas regras de depósito coexistem no arquivo; só uma é realmente aplicada.

### Tolerância de preço na troca

Regra existe **só em Trocar item** (não em Inserir peça — lá não há um
"item substituído" pra comparar preço). A comparação de preço (substituído
× novo) só aparece quando passa da tolerância — dentro dela, confirmação
simples sem mostrar valores:

- **10%** do preço atual — regra geral (`TOLERANCIA_PRECO_TROCA_PERCENTUAL`).
- **R$ 200,00 fixo** — quando a solicitação é de "motor completo"
  (`usu_ttipser.usu_destsv = "Completo"`, case-insensitive).

Passando da tolerância, a tela exige o campo obrigatório "quem autorizou"
antes de confirmar — gravado no `usu_obsite` do item **novo**, junto com a
diferença de valor.

### Webservice `GravarPedidos` (`db/pedido_ws.py`)

Cliente SOAP (`zeep`) isolado, usado só por Inserir/Trocar. Todo envelope
enviado/recebido é logado em texto puro (senha mascarada) em
`logs/pedido_ws_envelopes.log` **e também** salvo como arquivo `.xml`
separado em `logs/xml/` (um par enviado/recebido por chamada, nomeado com
timestamp + operação — ex: `20260813_091530_123456_incluir_item_pedido_
recebido.xml`) — pra poder abrir cada retorno isolado sem procurar dentro
do log grande.

- `opeExe`: "I" = incluir, "A" = alterar. Pedido sempre `"A"` (já existe);
  produto `"I"` pra item novo, `"A"` pra alterar/cancelar item existente
  (via `seqIpd`).
- `qtdPed`/`qtdCan`/`preUni` são `xs:string` no XSD — o Sapiens exige
  vírgula decimal (`"384,41"`, não `"384.41"`) — ver `_fmt_numero`.
- `erroExecucao` vazio **não** significa sucesso por si só — o sucesso real
  por pedido está em `respostaPedido.tipRet == 1`. O erro de negócio às
  vezes só aparece em `gridPro.retorno` (por item), não no `msgRet` do
  pedido.
- **Testado de verdade**: leitura (`obterItensPedido`) e o caminho
  "pedido novo + item novo" (`opeExe="I"` nos dois níveis, criou o pedido
  real 781740, empresa 2 — vale conferir se precisa ser estornado). O
  caminho que Inserir/Trocar realmente usam em produção — incluir/cancelar
  item num pedido **já existente** (`pedido.opeExe="A"`) — ainda não foi
  validado por teste real, só por inferência do padrão Senior. **Não usar
  Inserir peça / Trocar item em produção antes de validar isso.**

## 7. Inconsistências conhecidas / já corrigidas

- ~~`assumir_solicitacao` gravava `usu_horsep` como string `"HH:MM"`~~ —
  **corrigido**: agora grava minutos desde a meia-noite (inteiro), mesmo
  formato que `_fmt_hora` espera ao ler `usu_horsol`/`usu_horsep`/
  `usu_horcon`/`usu_horent` e que `inserir_item_solicitacao` já usava.
  Antes disso, qualquer tela que viesse a exibir a hora da separação via
  `_fmt_hora` quebraria com `ValueError`.
- ~~`db/local_db.py` mantinha a tabela `comentarios_item` e as funções
  `get_comentario`/`salvar_comentario`/`get_comentarios_solicitacao`~~ —
  **removido**: era código morto, nenhuma rota em `app.py` chamava mais
  (foram substituídas pela observação gravada direto no Oracle,
  `usu_obsite`).
- ~~`buscar_produto_preco` ficou com o SQL quebrado numa edição~~ —
  **corrigido**: a query nova (`SQL_PRODUTO_ATIVO_PRECO`) estava sendo
  chamada com parâmetros de bind que não existiam (`prebas`, `codmar`,
  `coddep`, `qtdabe`, `qtdped`, `despro` — na verdade colunas do `SELECT`,
  não binds) e o resultado era desempacotado errado; a função também
  dependia de `SQL_CODTAB_PEDIDO`/`CODTPR_PADRAO`/`SQL_PRECO_VIGENTE`, que
  não existiam mais no arquivo. Corrigido pra usar só os binds reais da
  query (`empsol`/`filsol`/`pronew`) e desempacotar as 8 colunas certas —
  ver ressalva sobre `codtpr` fixo e a distinção "não encontrado" vs.
  "inativo" na seção 6.
- ~~`produto_tem_ligacao_deposito` (e `_coddep_esperado`,
  `SQL_FILIAL_PEDIDO`, `SQL_DEPOSITO_LIGADO_PRODUTO`) sumiram do arquivo~~
  — **reposto**: essas funções são chamadas direto por `app.py`
  (`inserir_item`/`trocar_item`); sem elas essas duas rotas quebravam com
  `AttributeError`. Repostas sem mudança de lógica.
- ~~`SQL_INSERIR_ITEM_SOLICITACAO` tinha o texto `retorno wbs` solto dentro
  do SQL~~ — **corrigido** (quebrava a query no Oracle). Nessa mesma edição,
  `usu_qtdmso` e `usu_indtrc` foram tirados do `INSERT` de propósito (não é
  mais gravado se o item veio de uma troca) e `usu_sitite` passou a entrar
  fixo em `1` — mudança intencional, mantida assim.
- `get_solicitacao_cabecalho` reaproveita `SQL_SOLICITACOES`, que tem
  `WHERE usu_sitsol NOT IN (3,6,9) AND usu_datsol >= sysdate-180` fixo. Isso
  significa que abrir o detalhe de uma solicitação **já cancelada** ou com
  **mais de 180 dias** retorna cabeçalho vazio. Ainda não corrigido —
  avaliar se o detalhe deveria ter uma consulta própria, sem esse filtro.
- `SQL_PRODUTO_ATIVO_PRECO` traz uma regra de depósito por `codfil`
  (`10`/`1001`→`3`, senão `1`) que **não é usada** — o depósito de verdade
  usado nas validações é o de `produto_tem_ligacao_deposito` (regra por
  filial `L`/`P`/`C`). Duas regras diferentes coexistem no arquivo; avaliar
  se vale limpar a que não é usada, pra não confundir depois.
- ~~`SQL_PRODUTO_ATIVO_PRECO` comparava `t.datini` (coluna `DATE`) direto com
  string (`'01/04/2011'` etc.)~~ — **corrigido**: a conversão implícita
  dependia do `NLS_DATE_FORMAT` da sessão Oracle, e nesse ambiente não é
  `DD/MM/YYYY` — dava `ORA-01843: not a valid month`. Trocado por
  `TO_DATE(..., 'DD/MM/YYYY')` explícito, que não depende da sessão.
- ~~`SQL_PRODUTO_ATIVO_PRECO` comparava `p.codpro`/`p.usu_codpro2` (um deles
  `NUMBER`) direto com o texto digitado~~ — **corrigido**: quando alguém
  digitava um código de fabricante com letra, o Oracle tentava converter
  esse texto pra número no lado `p.codpro=:pronew` e estourava
  `ORA-01722: invalid number`. Trocado por `TO_CHAR(p.codpro)=:pronew` (
  converte a coluna pra texto, não o texto pra número - sempre seguro).
- ~~`get_solicitacao_cabecalho` não tinha mais a chave `tipo_servico` no
  dict retornado~~ — **corrigido**: `trocar_item` em `app.py` acessa
  `cabecalho["tipo_servico"]` direto (sem `.get`), causava `KeyError`.
- ~~`get_equivalentes` não tinha mais a chave `profor` no dict retornado~~ —
  **corrigido**: sem ela, a tela de Equivalentes voltava a mostrar o
  código interno (`proeqi`) em destaque em vez do código do fabricante
  (`usu_codpro2`), e o botão de copiar-e-ir-pra-Trocar sumia (dependia
  dessa mesma chave).
- ~~`get_observacao_solicitacao`/`salvar_observacao_solicitacao`/
  `SQL_SALVAR_OBSERVACAO_SOLICITACAO` sumiram do arquivo~~ — **repostas**:
  `app.py` chama as duas em 3 lugares (abrir o detalhe da solicitação e a
  tela de observação); sem elas essas telas quebravam com `AttributeError`.
- ~~`assumir_solicitacao` voltou a gravar `usu_horsep` como string
  `"HH:MM"`~~ — **corrigido de novo** (mesmo bug já registrado acima,
  reapareceu numa edição posterior) — causava `ORA-01722` ao tentar
  converter `"09:08"` pra número.
- ~~`produto_tem_ligacao_deposito` comparava `E210EST.codpro` direto com o
  texto digitado~~ — **corrigido**: `E210EST` é sempre indexada pelo
  código **interno**, mas a pessoa podia digitar/colar o código do
  **fabricante** (ex: vindo da tela de Equivalentes) - a checagem nunca
  encontrava a linha e dava "sem ligação para o depósito" mesmo o produto
  tendo saldo de verdade. `SQL_DEPOSITO_LIGADO_PRODUTO` agora resolve o
  produto em `E075PRO` primeiro (aceita interno ou fabricante, mesmo
  padrão de `SQL_PRODUTO_ATIVO_PRECO`) antes de bater com a `E210EST`.
- ~~`_coddep_esperado` não tinha regra nenhuma pra empresa 2 (RTL)~~ —
  **adicionada**: `L`→depósito `1`, `P`→depósito `2`, inferida do `CASE`
  de `SQL_SALDO_ESTOQUE_PADRAO` (`"RTL LD"`/`"RTL PP"`). **Ainda não
  confirmada contra dado real** — antes disso, toda solicitação da RTL
  caía direto em "sem ligação para o depósito", pra qualquer produto.
- ~~`cancelar_item_solicitacao` ficou pela metade numa edição (UPDATE só
  com `usu_qtdabe`/`usu_qtdcan`, sem `usu_sitite`/`usu_qtdate`/
  `usu_obsite`, e sem aceitar o parâmetro `motivo` que `app.py` já
  passava)~~ — **corrigido e reescrito**: hoje decide entre dois UPDATEs
  (sem/com movimentação, ver seção 6) e sempre grava a mensagem
  data/hora/usuário/motivo. Criada `cancelar_qtd_item_solicitacao_troca`
  em separado pro cancelamento parcial que a Troca de item precisa (a
  Troca não pode mais reaproveitar `cancelar_item_solicitacao`, que agora
  sempre cancela o item inteiro).
- ~~`get_observacao_item` (+ `SQL_OBSERVACAO_ITEM`) — código morto~~ —
  **removido**: nenhuma rota chamava, a observação por item foi
  substituída pela observação única da solicitação (ver seção 5.3).
- ~~Preço dos Equivalentes vinha de `E075EQI.conpr1`/`conpr2`~~ —
  **trocado**: os valores reais chegavam como `1,00`/`0,00`/vazio, não
  batiam com preço de peça de verdade (confirmado testando na tela). Preço
  agora vem da `E081ITP` (`SQL_PRECO_EQUIVALENTE`, pelo `proeqi`), mesma
  regra fixa que `buscar_produto_preco` já usa pra qualquer outro produto.

## 8. Ainda faltam / pendências

- Terceira tela (mensagem simples com informações da solicitação, tipo o
  pop-up "INFORMAÇÕES DA SOLICITAÇÃO" atual) — não desenhada.
- Definir quem/como registra a retirada em "Atendido/parcial" (crachá aberto
  vs. restrito a um perfil) — não implementado.
- Restringir as ações (assumir/cancelar/inserir/trocar) por perfil — hoje
  qualquer usuário logado pode executar todas (ver seção 3).
- Coluna `usu_obsite` na `usu_t120sit` — as telas de observação (de item e
  de solicitação) dependem dela; `app.py` trata a ausência com um
  try/except e mostra aviso claro em vez de deixar o erro do Oracle
  estourar, então é rápido conferir: se o aviso aparecer ao usar essas
  telas, a coluna ainda não existe no ambiente. DDL sugerida:
  `ALTER TABLE sapiens.usu_t120sit ADD usu_obsite VARCHAR2(250);`
- Validar o caminho `opeExe="A"` (pedido existente) do webservice
  `GravarPedidos_15` contra um pedido real (ver seção 6) antes de liberar
  Inserir peça / Trocar item em produção.
- Resolver o item da seção 7 sobre `get_solicitacao_cabecalho` (filtro de
  180 dias / situação cancelada).
- Decidir se a regra de depósito por `codfil`, não usada, dentro de
  `SQL_PRODUTO_ATIVO_PRECO` deve ser removida (ver seção 7).
- **Confirmar a regra de depósito da RTL** (`L`→`1`, `P`→`2` em
  `_coddep_esperado`) contra um caso real — foi inferida do `CASE` de
  `SQL_SALDO_ESTOQUE_PADRAO`, não testada (ver seção 7).

## 9. Stack técnica

- Backend: Python / Flask
- Banco principal: Oracle (Sapiens ERP), via `oracledb` (modo thick)
- Banco local: SQLite (perfis de usuário — `db/acompanha_pedido.sqlite3`,
  criado automaticamente na primeira execução)
- Webservice: SOAP (`zeep`) — `GravarPedidos_15`, só para Inserir/Trocar
- Frontend: HTML/Jinja2 + CSS próprio (`static/css/style.css`)
- Hospedagem: serviço numa VM 24h já existente

## 10. Estrutura

```
acompanha_pedido/
  app.py                  # rotas Flask
  requirements.txt
  .env                     # credenciais do Oracle + webservice + chave do Flask (não versionado)
  .gitignore
  logs/
    pedido_ws_envelopes.log # log de texto único dos envelopes SOAP enviados/recebidos
    xml/                     # mesmos envelopes, um .xml por chamada (enviado + recebido)
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
