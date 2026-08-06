# Acompanha Pedido — Estoque Retífica

Projeto para substituir a tela atual de **Acompanhamento de Solicitações de
Peças** por um sistema novo, desenvolvido em Flask + Oracle (Sapiens) + SQLite
local. Este documento reúne o desenho e as decisões tomadas até o momento,
para servir de referência durante o desenvolvimento.

> Status: fase de desenho (mockups fechados). Nenhum código foi escrito ainda.

---

## 1. Contexto

- 4 empresas possuem depósito próprio:
  - **1** — Retífica
  - **2** — RTL (distribuidora de peças, onde a tela atual está hospedada)
  - **5** — Transmissões
  - **12** — Tiête Car
- Cada empresa tem seu próprio depósito.
- Fluxo atual: a usinagem (Retífica) solicita uma peça no estoque; alguém da
  boqueta pega a solicitação, separa o pedido; depois a peça é retirada — mas
  hoje **ninguém registra quem retirou fisicamente**. Esse é o problema
  central que motiva o projeto.
- A tela vai rodar como **serviço numa VM 24h** já existente, acessível por
  várias pessoas/computadores (não é uma aplicação desktop local).

### Observações de dados

- `codpro1` da Retífica é o código **interno**; `codpro2` é do **fabricante**.
- Na RTL é o inverso: `codpro1` é do **fabricante**; `codpro2` é o **interno**.
- A tela nova sempre exibe os dois códigos lado a lado (ver seção 5).

---

## 2. Fluxo de status

Apenas 3 etapas reais (sem etapa de conferência):

```
Solicitado  →  Em separação  →  Atendido / parcial
```

- **Solicitado**: usinagem solicita a peça e o solicitante pede a peça. Ação de "pegar":
  duplo clique no item → preenche usuário e senha do Sapiens (da pessoa que
  está assumindo) → o usuário de quem solicitou já aparece ali, só leitura. 
- **Em separação**: alguém da boqueta assume a solicitação. Ação de "pegar":
  duplo clique no item → preenche usuário e senha do Sapiens (da pessoa que
  está assumindo) → o usuário de quem solicitou já aparece ali, só leitura.
- **Atendido / parcial**: a peça é retirada. **Novidade do projeto**: controle
  de quem retira, por leitura de crachá (código de barras/RFID) no momento do
  atendimento.
  - Em aberto: quem exatamente realiza essa ação (perfil livre por crachá vs.
    perfil restrito) ainda não foi decidido.

Query base de listagem (usu_t120sdg + e120ped), update de "pegar solicitação"
(seta `usu_sitsdg=5`, grava separador/data/hora) e select de itens da
solicitação já existem — ver `Selects_Estoque.txt` do projeto original.

---

## 3. Perfis de acesso

Os perfis definem **o que a pessoa pode fazer** na tela, não quem ela é (não
classificam o solicitante).

| Perfil | Descrição | Ação na tela |
|---|---|---|
| **G** — Gerência | Acompanha e supervisiona tudo | Só visualização e relatórios, mas com acesso e controle total |
| **B** — Boqueta | Separa as solicitações | Assume itens em Solicitado, move para Em separação |
| **U** — Usinagem | Solicita as peças | Cria novas solicitações |
| *(sem perfil)* | Usuário válido no Sapiens, ainda não cadastrado neste sistema | Modo visualização, sem nenhuma ação (fail-safe) |

Regras:

- Perfil **"C"** foi cogitado e **descartado** — não faz parte do desenho.
- Cada usuário tem **exatamente 1 perfil fixo** (sem acúmulo de perfis).
- Todos os perfis veem as 3 colunas do painel; cada um só age na etapa que
  lhe cabe.

---

## 4. Login e administração de perfis

- **Autenticação**: usuário e senha reaproveitados da tabela de usuários que
  já existe no Oracle/Sapiens.
- **Perfil (G/B/U)**: informação nova, específica deste sistema — não existe
  no Sapiens. Vive numa tabela local (SQLite), relacionando o login do
  Sapiens ao perfil.
- **Administração de perfis**: tela restrita à Gerência, para atribuir/editar
  o perfil de cada usuário.
- **Usuário sem perfil**: consegue logar normalmente (credenciais válidas no
  Sapiens), mas cai em modo só leitura até alguém da Gerência atribuir um
  perfil.

---

## 5. Telas

### 5.1 Tela de seleção inicial

Aberta ao iniciar o programa, antes do painel. A pessoa escolhe:

- Empresa
- Filial
- Tipo de serviço (`DesTsv`)
- Etapa (`DesEtp`)

Depois de escolher, abre o painel já filtrado. Um atalho no cabeçalho do
painel ("Trocar seleção") reabre esse menu sem precisar fechar a tela.

### 5.2 Painel principal (Acompanhamento)

Mostra **só as 3 colunas** (Solicitado / Em separação / Atendido-Parcial),
sem barra de filtros visível — os filtros já foram aplicados na seleção
inicial. É um painel fixo, pensado para ficar exibido publicamente (tipo
TV/monitor de parede), então a densidade da lista precisa comportar várias
linhas visíveis.

Colunas exibidas em cada card: data/hora, filial, O.S., **número da
solicitação** (`usu_numsol`) e o nome relevante da etapa (solicitante,
separador, ou quem retirou).

### 5.3 Segunda tela (detalhe da solicitação)

Aberta ao clicar num item da coluna **Em separação**. Substitui o pop-up
"Acompanhamentos" atual. Duas partes:

1. **Cabeçalho**, no formato do relatório impresso (RVPE134GER): O.S.,
   filial, número da solicitação, data/hora, status, cliente, cidade,
   solicitante, separador, observação do pedido.
2. **Lista de itens da solicitação**, com saldo de estoque por depósito ao
   lado de cada item (query "select saldos estoque"). Cada linha mostra:
   - Produto (código 1) e **Produto 2** (o outro código, dependendo da
     empresa — ver seção 1)
   - Descrição, marca, quantidade solicitada
   - Saldo por depósito (os depósitos exibidos variam conforme a empresa e
     filial do item — mesma lógica condicional da query original)

No momento, é uma **tela de consulta**, sem botões de ação — ainda não
decidido se vai ganhar ações no futuro.

### 5.4 Terceira tela (ainda não desenhada)

Mensagem simples com as informações da solicitação (equivalente aos pop-ups
"INFORMAÇÕES DA SOLICITAÇÃO" que existem hoje). Ainda não foi desenhada.

---

## 6. Pontos em aberto

- [ ] Desenhar a terceira tela (mensagem com informações da solicitação).
- [ ] Decidir se a segunda tela terá ações além de consulta.
- [ ] Definir quem realiza a ação de atendimento/retirada com o crachá
      (crachá aberto a qualquer pessoa vs. restrito a um perfil).
- [ ] Estrutura técnica: rotas Flask, modelo da tabela local de perfis,
      integração real com o relatório RVPE134GER.

---

## 7. Stack técnica

- Backend: Python / Flask
- Banco principal: Oracle (Sapiens ERP), via `oracledb` (thick mode)
- Banco local: SQLite (perfis de usuário, e o que mais for específico deste
  sistema)
- Frontend: HTML/JS
- Hospedagem: serviço rodando numa VM 24h já existente