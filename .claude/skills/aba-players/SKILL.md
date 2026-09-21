---
name: aba-players
description: Plano e mapa de funcionalidades da aba Players (Baleia x Banco x Sardinha) para WIN/WDO da B3, inspirada no Sala Sagrada AI. Use quando o usuário falar de aba Players, fluxo de players, baleia/banco/sardinha, WIN, WDO, mini índice, mini dólar, B3, ProfitDLL ou fluxo de corretoras.
---

# Aba Players — WIN/WDO (B3)

Plano vivo. Atualize este arquivo conforme as fases forem sendo feitas.
Criado em 2026-09-16 a partir da engenharia reversa do bundle do
`https://salasagradaai.com.br/preview` (arquivo `assets/index-4BTz1csi.js`).

## 1. Decisão: mesmo repo, aba nova

**Fica no `trading-buddy`, rota `/players`.**

Por quê:
- O padrão já existe: collector no Windows → backend FastAPI → frontend Next.
  A aba nova só troca a fonte de dados (B3 no lugar de MT5/ActivTrades).
- Reaproveita docker, Makefile, acesso pela LAN, watchdog, tema, header.
- O que muda de verdade é um processo collector novo + tabelas novas. Isso
  cabe em `collector/` e `backend/` sem bagunçar o que já roda.

Quando valeria repo separado: se um dia isso virar produto pra vender pra
outra pessoa (login, cobrança, multi-usuário). Aí sim separa. Hoje não.

**Nome da aba:** `Players`. É o termo que a Nelogica usa e cobre os três
bichos. Alternativas descartadas: "Fluxo B3" (confunde com a strip de fluxo
que já existe), "Sardinha" (engraçado mas não descreve).

## 2. ACHADO: o dado já está na sua máquina (16/09/2026)

O usuário achou que o Sala Sagrada puxava do Black Arrow. **O Black Arrow dele
não serve** — é a versão ActivTrades (`exchangeinfo.dat` diz
`ActivTrades:R` e `FXGlobe:e`), só CFD: BRA50, USA500, USATEC, GOLD. Sem B3.

Mas, procurando, apareceu coisa muito melhor:

```
C:\Users\diego\AppData\Roaming\Nelogica\Profit\   (e \XPTrader\)
  exchangeinfo.dat   -> BMF:F, Bovespa:B  (tem B3 de verdade)
  newagents.dat      -> tabela oficial codigo -> corretora, 160 linhas
  database/assets/WDOV26_F_0/*.trd   -> Times & Trades tick a tick
```

### O formato .trd foi decodificado e validado

Registro de **45 bytes**, sem cabeçalho:

| offset | tipo | campo |
|---|---|---|
| 0–7 | double | TDateTime Delphi (dias desde 30/12/1899) |
| 8–11 | uint32 | milissegundos |
| 12–19 | double | preço |
| 20–23 | uint32 | quantidade |
| 24–27 | uint32 | (sempre 0 até agora) |
| 28–35 | double | volume financeiro |
| 36–39 | uint32 | **código da corretora compradora** |
| 40–43 | uint32 | **código da corretora vendedora** |
| 44 | uint8 | tipo do negócio |

Tipos vistos: `2` = agressão compradora, `3` = agressão vendedora,
`4` = leilão (abertura), `13` = provável RLP, `1` = raro (direto/cross).

Parser pronto e testado: `parse_trd.py` nesta mesma pasta.

**Teste real (WDOV26, 14/09/2026, arquivo de 24 MB):** 534.719 negócios,
09:00 às 18:29, zero resto de bytes, **100% dos códigos de corretora bateram
com o `newagents.dat`**. Saldo líquido do dia: BTG +24.360, Goldman +21.068,
XP +20.702, Morgan +15.101 do lado comprado; Tullett −29.695, Santander
Institucional −11.676, Ágora −11.238, JP Morgan −7.976 do lado vendido.

### O que isso muda

- **A aposta de 70% do plano anterior está resolvida: sim, a B3 manda o código
  da corretora no WIN/WDO.** Prova em disco, não em documentação.
- **Não precisa comprar ProfitDLL** pra histórico nem pra backtest. É só ler
  arquivo.
- Dá pra construir e validar as fases 5 e 6 **hoje**, com dado gravado, antes
  de gastar um centavo.

### O que ainda falta checar

- [ ] O Profit escreve o `.trd` ao vivo (dá pra ficar lendo o fim do arquivo)
      ou só grava em bloco ao fechar? Teste: abrir o Profit com Times & Trades
      do WDO e ver o arquivo crescer.
- [ ] O `.trd` só tem o que o Profit baixou enquanto esteve aberto. O arquivo
      de 15/09 tem só 3.968 negócios e para às 09:02 porque ele abriu e fechou.
      Pra ter série contínua, o Profit precisa ficar aberto (ou usar a DLL).
- [ ] Confirmar se tipo `13` é mesmo RLP. Importa muito: RLP é ordem de varejo
      internalizada pela corretora, ou seja, é sardinha por definição.
- [ ] Qual conta Nelogica é essa e se ela ainda está ativa (última gravação de
      WDO é de 14–15/09/2026, então parece viva).

### Dá pra separar baleia, banco e sardinha? (medido em 16/09/2026)

Resposta curta: **corretora, sim, 100%. Sardinha, sim, com prova dura.
Baleia, mais ou menos. Banco, mal.**

**SARDINHA — achado forte: o tipo 13 é RLP.**
Testes que confirmam (`rlp.py`):
- 119.270 negócios (22% do dia), **100% com a mesma corretora nos dois lados**
- lote médio 3,0 e 77% dos negócios são de 1–2 contratos
- só aparece em casa de varejo: XP 186k, BTG 74k, Genial 37k, Santander 32k,
  CM Capital 9k. **Zero** em UBS, Morgan, Goldman, JP Morgan, Tullett, BGC.

RLP (Retail Liquidity Provider) é um mecanismo da B3 em que a corretora é a
contraparte da ordem **do próprio cliente de varejo** — por regra, só vale
pra varejo. Ou seja: **isso não é chute, é marcação regulatória.** É o dado
mais limpo de sardinha que existe, e o Sala Sagrada provavelmente usa o mesmo.

Problema que sobra: o tipo 13 **não diz o lado** (não é 2 nem 3). Pra saber se
a sardinha comprou ou vendeu tem que inferir pela regra do tick (preço subiu
desde o último negócio = compra). `sardinha.py` já faz isso.

O tipo 1 (1.027 negócios) também é 100% mesma corretora, com lote médio 70 —
é negócio direto (a corretora cruza duas ordens dela). Mistura tudo, não usar.

**BALEIA — dá pra chegar perto, mas é leitura, não marcação.**
O perfil por corretora separa bem (`perfil.py`, WDO 14/09):

| corretora | contratos | lote méd | % vol em 50+ | % agride | % RLP |
|---|---|---|---|---|---|
| Tullett | 164.611 | 8,3 | 46 | 76 | 0 |
| BGC Liquidez | 62.126 | 6,8 | 36 | 64 | 0 |
| Morgan | 68.373 | 6,3 | 39 | 61 | 0 |
| JP Morgan | 32.334 | 4,1 | 29 | 73 | 0 |
| Goldman | 45.126 | 5,2 | 20 | 52 | 0 |
| UBS | 604.372 | 7,9 | 43 | 50 | 0 |
| — | | | | | |
| XP | 1.095.298 | 3,6 | 23 | 24 | **34** |
| Santander | 97.312 | 2,2 | 13 | 17 | **66** |
| Inter | 6.336 | 1,9 | 7 | 15 | **65** |
| Nova Futura | 83.862 | 1,7 | 5 | 15 | 4 |

Tullett Prebon e BGC Liquidez são *interdealer brokers* — são o cano por onde
passa mesa de banco e estrangeiro. Somado a RLP zero, agressão alta e lote
grande, o grupo "baleia" fica bem separado do grupo "varejo".

**BANCO — é o pior caso.** O código do Itaú junta mesa própria, cliente varejo
e cliente institucional no mesmo número. Não dá pra separar por dentro.
Ajuda um pouco: o Santander tem **dois códigos** (`Santander` com 66% RLP =
varejo, e `Santander Institucional` com 87% de agressão e 0% RLP = mesa).

**Conclusão prática:** monte a aba com **dois times confiáveis** —
sardinha (RLP, marcação dura) e baleia (interdealer + bancos estrangeiros
sem RLP). O banco local fica como terceiro card, marcado como "leitura",
não como fato.

### Primeiro teste da tese (1 dia só — não conclui nada)

`sardinha.py`: saldo da sardinha (RLP + regra do tick) em baldes de 10 min ×
retorno dos 10 min seguintes, WDO 14/09. Resultado: sardinha comprando forte →
−0,4 bps; vendendo forte → −1,0 bps. **É ruído.** 56 baldes de um pregão não
diz nada. Precisa dos meses de tape da Fase 1.

### As outras fontes continuam valendo

| # | Fonte | O que dá | Atraso | Custo |
|---|---|---|---|---|
| 1 | **`.trd` do Profit** ✅ *achado* | corretora compradora, vendedora e quem agrediu, negócio a negócio | tempo real se o Profit ficar aberto | já tem |
| 2 | **ProfitDLL** | o mesmo, por callback, sem depender de arquivo | tempo real | assinatura à parte |
| 3 | **B3 oficial** (contratos em aberto por tipo de participante) | posição por categoria: Estrangeiro, Institucional, Pessoa Física, Inst. Financeira, Empresas | D+1 | grátis |
| 4 | Estimativa pela fita (CVD + tamanho de lote) | chute | tempo real | grátis |

A fonte 3 vira o **gabarito**: com meses de `.trd` em disco dá pra ajustar o
mapa corretora → categoria por regressão contra o número oficial, em vez de
chutar.

### Ressalva que continua de pé

Corretora não é tipo de investidor. XP roteia institucional, BTG tem mesa
própria, estrangeiro entra por DMA em corretora local. Só que agora isso
deixou de ser fé e virou coisa mensurável: tem dado dos dois lados pra
calibrar.

Mapa inicial (ponto de partida, não verdade):
- **Baleia (estrangeiro):** Morgan, Goldman, JP Morgan, UBS, Citigroup,
  Merrill, Credit, Barclays, Tullett, BGC Liquidez.
- **Banco (local):** Itaú, Bradesco, Santander, Santander Institucional,
  BB, Safra, BTG.
- **Sardinha (CPF):** XP, Genial, Clear, Rico, Modal, Ideal, Ativa, Órama,
  Nova Futura, Terra, C6, Inter, Ágora, Necton, CM Capital.

## 3. Mapa de funcionalidades do Sala Sagrada AI

Tudo abaixo saiu do bundle. Está agrupado por tela. O que interessa pra nós
está marcado com prioridade: **[P1]** faz, **[P2]** talvez, **[P3]** não.

### 3.1 Núcleo — Fluxo de players  **[P1]**
O coração. Três cards lado a lado, cada um com mascote, lado e valor:

- **BALEIA** — papel "estrangeiro". Campo `perfilFluxo.institucional`.
  Lado BUY/SELL/NEUTRAL + força em %. Fonte marcada como `corretora`
  (real) ou `atividade` (deduzido).
- **BANCO** — "dealers, institucional local que equilibra book e faz
  contraparte do varejo". Campo `perfilFluxo.banco`.
- **SARDINHA** — varejo/CPF. Campo `perfilFluxo.pessoaFisica`, mais um
  `sardinha OFI` (order flow imbalance do varejo).

Ao lado disso existe `marketData.papelCorretoras`, com `grupos` (o grupo
`PONTA`), `papel` (PUXANDO_ALTA = "AGRIDE NA COMPRA", PUXANDO_BAIXA, PARADA,
PISO, GIRO) e `concentracao.anormal`. **Isso é a prova mais forte de que eles
recebem código de corretora trade a trade** — não dá pra calcular "papel da
corretora" sem saber quem é a corretora.

O card Overnight usa outra coisa: as chaves
`["estrangeiro","institucional","pessoaFisica","bancos","corretoras"]` com
`netRs` e `metric: "fluxo_rs"`. Isso é o painel oficial da B3 em R$, D+1 —
e é do mercado **à vista**, não de WIN/WDO. Ou seja, eles usam o fluxo da
bolsa à vista como proxy do estrangeiro no índice.

Regras que eles aplicam em cima:
- **Absorção:** preço cai + fita vendendo + baleia comprando = absorção
  institucional. O contrário = distribuição.
- **Fase do CPF:** EUFORIA (varejo comprando forte com preço esticado),
  PÂNICO (varejo vendendo com preço pressionado), CONTRARIAN (CPF unânime
  contra a baleia = crowding).
- **Quem puxou o viés:** qual player liderou o movimento inicial do dia.
- **Divergência banco x baleia** = disputa de fluxo, convicção baixa.

### 3.2 Fluxo e tape  **[P1]**
- Domínio do mercado (quem agride mais nos últimos ~300 ticks)
- Touro / Urso / Cobra (armadilha) / Baleia — mascotes de estado
- Força compradora, força vendedora, força dominante (nota 0–10)
- Delta do fluxo: CVD 15 min + CVD do dia, dois números lado a lado
- Velocidade da fita (negócios por minuto)
- Agressão x absorção ("papel da mesa": quem bate e quem serve)
- Selo do tape (saúde do feed; fora do pregão mostra "aguardando")
- Streak de agressão, IFAS score/lado
- Sinal real x fake (rompimento com lastro vs armadilha)
- Selo de lastro (nova máxima com fluxo ou topo furado)

### 3.3 Preço e níveis  **[P1]**
- Preço, máxima, mínima, abertura, fechamento anterior
- **Ajuste B3** (mark-to-market) — nível clássico do WIN/WDO
- **Túnel teto / túnel piso** (MaxTradLmt / MinTradLmt, bandas oficiais B3)
- Suporte, resistência, pivot PP/R1/S1
- VWAP + bandas 1σ e 2σ, VWAP semanal
- POC, Value Area (VAH/VAL)
- Fibonacci 50% e 61,8%
- Gap de abertura, "andou hoje" (amplitude), média 15 dias
- Níveis psicológicos (números redondos)
- Distância até máxima / mínima / VWAP

### 3.4 Avisos sonoros (voz)  **[P1 — o usuário quer isso]**
Fala em português quando o preço encosta em nível. Cada aviso tem cooldown
(2 min normal, 5 min pro VWAP semanal) e rearma quando o preço se afasta
4× a tolerância. Catálogo encontrado:

- "chegou no teto do túnel oficial" / "chegou no piso do túnel oficial"
- "chegou no ajuste"
- "tocou o pivô R1" / "tocou a retração de 50 por cento"
- "tocando na VWAP semanal. Região de decisão da semana."
- "tocou a primeira banda do VWAP. Um desvio padrão."
- "Atenção: tocou a SEGUNDA banda do VWAP"
- "Chegou no preço de abertura."
- "chegou na máxima provável do dia, <valor>" / mínima provável
- "chegou na média dos últimos quinze dias. Preço acima/abaixo da média."
- "tocou os cinquenta por cento de retração do dia" / "sessenta e um vírgula oito"
- "tocou o POC"
- "baleia comprando enquanto o preço cai — absorção institucional detectada"
- "baleia vendendo enquanto o preço sobe — distribuição institucional"
- "baleia institucional virou compradora/vendedora no <ativo>"
- "viés principal mudou para compra/venda no <ativo>"
- "varejo comprando forte com preço esticado — estrutura de topo possível"
- "varejo vendendo forte com preço pressionado — estrutura de fundo possível"
- "CPF unânime contra a baleia — crowding ativo"
- "placar dos treze critérios deu compra/venda. Entrada X, stop Y, alvo Z."

Níveis de prioridade: P0_CRITICAL, P1_CRITICAL, P1_MARKET, P2_GUIDE, P3_INFO.
Tem botão de liga/desliga do som e uma voz separada de "narração contínua".

### 3.5 Zona de atuação / gatilho de entrada  **[P2]**
- Zona de atuação (faixa onde operar faz sentido)
- Região de liquidez (alvo institucional) e região de invalidação (stop lógico)
- **Placar dos 13 critérios** — quando todos alinham, "arma" e entrega
  entrada, stop, alvo e payoff. A receita deles é fechada.
- Calculadora de tamanho de posição (`/api/agentes/sala-sagrada/calcular-tamanho`)
- Perfis conservador / moderado / agressivo
- Killswitch (bloqueia entradas)

### 3.6 Macro e contexto  **[P2 — boa parte disso já existe no trading-buddy]**
- S&P 500, Nasdaq, VIX, ouro, petróleo, DXY, Treasury 10Y, EWZ, minério
- DI, Selic, CDI, Ibovespa à vista
- CME FedWatch (probabilidade de juros)
- Amplitude do Ibov (quantas ações sobem/caem) e top impacto (puxadoras)
- **PTAX**: janelas de fixing e palpite da PTAX do dia — específico do WDO
- Correlação WIN x WDO (inversão clássica)
- Calendário macro, notícias com sentimento, surpresa de dado, Copom, payroll
- Regime global: risk on / risk off / neutral / fragile
- "Como o mundo acordou" (pré-abertura)
- **Overnight**: como o estrangeiro dormiu posicionado. Fonte "real" =
  painel oficial da B3 D+1; fonte "dedução" = chute do motor.

### 3.7 Tela de abertura  **[P2]**
Overlay antes das 9h20 com: gap, tipo de abertura, convicção, consenso entre
módulos, força índice, força dólar, quem puxou, memória histórica (backtest
de aberturas parecidas), níveis projetados (ajuste, suporte, resistência,
VWAP, POC, fib).

### 3.8 Guardião (IA)  **[P3 — não fazer agora]**
Chat com stream (`/api/guardian/chat-stream`), narração por voz, "explique o
mercado", "resumo em 30 segundos", "explica o dashboard", microfone.
Custa caro e não é o que traz dinheiro. O motor determinístico vem primeiro.

### 3.9 Enfeite  **[P3 — não fazer]**
Vídeo de intro com narração, clima da cidade, signo do zodíaco, frase do dia,
blog, planos de assinatura, gate de convite, mascotes animados.

### 3.10 Arquitetura deles (pra referência)
- `/api/bridge/live-prices` — snapshot inicial: `{asset, price, open, change,
  aggressionBuy, aggressionSell, volume, tickAt}`
- `/api/sse/market` — SSE com evento `market_update` empurrando as mesmas cotações
- `/api/overnight/deducao` — `{WIN, WDO, painel, placar.porAtivo}`, cache 30 min
- `/api/agentes/sala-sagrada/sse` e `/historico` — sinais do motor
- Frontend React + Vite, sem service worker (têm um kill-switch pra matar SW velho)

É praticamente o mesmo desenho do trading-buddy: um bridge no Windows
empurrando tick, SSE pro browser. Isso confirma que a fase 1 é só trocar a
fonte.

## 4. Plano por fases  *(revisado 16/09/2026 depois do achado do .trd)*

Cada fase tem um "pronto quando" verificável. Não passar sem isso.

### Fase 0 — Achar a fonte  ✅ **FEITA**
`.trd` do Profit decodificado e validado em 534 mil negócios. Parser em
`parse_trd.py`.

### Fase 1 — Leitor de tape com corretora
Levar o `parse_trd.py` pro repo (`collector/` ou `backend/adapters/`), ler os
`.trd` de WIN e WDO, aplicar o mapa de corretoras e gravar no banco: por
minuto, saldo de baleia, banco e sardinha, separando quem agrediu de quem foi
passivo.
**Pronto quando:** o saldo do dia 14/09 sai igual rodando duas vezes, e o
total de contratos bate com o volume do dia no Profit.

### Fase 2 — Ao vivo
Testar se o `.trd` cresce com o Profit aberto. Se crescer, um tailer simples
resolve (mesmo padrão do collector do MT5). Se não, aí sim avaliar ProfitDLL.
**Pronto quando:** o backend recebe negócio novo em menos de 2 s do que
aparece na tela do Profit.

### Fase 3 — Aba `/players`, versão mínima
Três cards (Baleia, Banco, Sardinha) por ativo: lado, saldo em contratos e
força em %. Selo dizendo se é dado de corretora (real) ou estimativa.
**Pronto quando:** abre no navegador, atualiza ao vivo, e o selo nunca mente.

### Fase 4 — Gabarito oficial D+1
Job diário que baixa o painel da B3 (contratos em aberto por tipo de
participante) e guarda. Regredir o saldo por corretora contra o número
oficial pra **aprender** o mapa em vez de chutar.
**Pronto quando:** com 20 dias, o mapa aprendido erra menos que o mapa
chutado da seção 2.

### Fase 5 — Níveis + avisos sonoros
Ajuste B3, túnel teto/piso, VWAP + bandas, POC, fib, média 15d. Voz em
português com cooldown e rearme (toca quando `|preço − nível| ≤ tol`,
rearma quando passa de `4 × tol`).
**Pronto quando:** num replay do `.trd` de um dia inteiro, os avisos disparam
nos lugares certos e não repetem.

### Fase 6 — Padrões de player
Absorção, distribuição, fase do CPF (euforia/pânico/contrarian), divergência
banco × baleia, quem puxou o viés.
**Pronto quando:** backtest no tape gravado mostra o acerto de cada padrão.
Padrão que não paga não entra na tela.

### Fase 7 — Sinal contra a sardinha
A tese: sardinha perde, então opere contra. Só depois de ter número.
Dá pra atacar isso **já**, com os `.trd` que ele tem em disco.

## 5. Regras que este projeto herda do trading-buddy

- Nunca inventar dado. Sem fita viva, mostra "aguardando" (eles fazem isso e
  está certo).
- Sempre mostrar a fonte: real (corretora) x estimada (fita) x oficial (D+1).
- Rebuild e subir tudo depois de mexer — ver `feedback_rebuild_apos_mudanca`.
- Cuidado com CRLF em script/Dockerfile novo — ver `project_crlf_checkout`.
- O relógio do WSL pula; medir frescor pela chegada do dado, não pelo relógio.

## 6. Quanto eu confio neste plano  *(revisado 16/09/2026)*

### Alto (95%+) — testei ou li no código
- **Formato do `.trd` e os códigos de corretora.** Rodei o parser em 534.719
  negócios de um dia inteiro: zero byte sobrando e 100% dos códigos batendo
  com a tabela oficial. Isso não é dedução, é dado.
- O mapa de funcionalidades da seção 3. Saiu do bundle deles.
- O catálogo de avisos de voz e a regra de cooldown/rearme.
- O Black Arrow instalado é o da ActivTrades e não tem B3.
- Decisão de ficar no mesmo repo. Risco baixo e reversível.

### Médio (60–75%)
- **O `.trd` ser tailável ao vivo.** Se o Profit só gravar em bloco, a Fase 2
  atrasa e volta a conversa de ProfitDLL. Não muda o backtest.
- Tipo `13` ser RLP. É palpite pelo tamanho (22% dos negócios) e pelo que se
  sabe do mercado. Precisa conferir contra a tela do Profit.
- A conta Nelogica dele estar ativa e com dado de B3 em dia.
- O arquivo D+1 da B3 ser baixável por script.

### Baixo (40–55%) — onde o plano ainda pode furar
- **Corretora → tipo de investidor.** Continua sendo o ponto fraco. A
  diferença é que agora dá pra calibrar contra o gabarito da B3 em vez de
  chutar. Isso sobe pra ~70% depois da Fase 4.
- **"Sardinha perde, então opere contra" virar dinheiro.** Que o CPF perde no
  day trade tem estudo atrás. Que o fluxo dela, minuto a minuto, dê entrada
  lucrativa é outra coisa e não tem prova. A boa notícia: dá pra testar
  **agora**, com o tape que já está no disco, sem gastar nada.

### O tamanho da amostra hoje (conferido)
Só existem **7 arquivos `.trd` no Profit e 2 no XPTrader**:

```
Profit     WDOG25  23/01/2025   13 MB
Profit     WDOV26  14/09/2026   23 MB   (dia inteiro, 534.719 negócios)
Profit     WDOV26  15/09/2026  174 KB   (só 09:00–09:02)
Profit     WINZ25  21/10/2025  198 MB
Profit     PETR4   21–22/01/2025
XPTrader   WDOFUT  19/09/2025   21 MB
XPTrader   WDOFUT  22/09/2025   15 MB
```

Ou seja: **4 ou 5 pregões cheios, não uma base**. Dá pra provar que o parser
funciona e fazer um primeiro olhar, mas não dá pra afirmar que ir contra a
sardinha paga. Pra isso precisa juntar tape — deixar o Profit aberto com
Times & Trades de WIN e WDO todo dia, ou partir pra ProfitDLL.

Isso rebaixa a Fase 7 na prática: ela depende de tempo de coleta, não de
código.

### Próximo passo, na ordem
1. Decidir como juntar tape todo dia (Profit aberto + tailer, ou ProfitDLL).
   Sem isso a amostra não cresce e a Fase 7 não sai do lugar.
2. Abrir o Profit com Times & Trades do WDO e ver se o arquivo cresce.
3. Backtest simples: saldo da sardinha por minuto × retorno dos próximos 5,
   15 e 30 min. Se não tiver sinal, o resto do plano muda de forma.

### Resumo em uma linha
O plano anterior tinha uma aposta única não verificada. Ela caiu: o dado real
de corretora já está no disco dele, de graça. O que sobra de risco é
conceitual (corretora ≠ investidor) e de tese (sardinha dá sinal?) — e as
duas coisas agora dá pra medir com o que ele já tem.

## 7. Estado da implementação (16/09/2026)

Fase 1 e 3 escritas. Arquivos:

```
backend/adapters/profit_tape.py          leitor do .trd (45 bytes) + newagents.dat
backend/use_cases/aggregate_players.py   grupos, RLP, janela de 15 min, séries 5 min
backend/api/routes/players.py            GET /api/players (leitura incremental por offset)
backend/tests/unit/test_aggregate_players.py   12 testes, todos passando
frontend/app/players/page.tsx            aba /players
frontend/components/players/*.tsx        cards, gráfico SVG, tabela de corretoras
frontend/hooks/usePlayers.ts             poll de 3s
docker/docker-compose.yml                monta PROFIT_DIR_HOST em /profit (ro)
.env                                     PROFIT_DIR_HOST, PLAYERS_ASSETS
```

Decisões que valem lembrar:

- **Quatro cards, não três.** BALEIA, BANCO, SARDINHA (RLP) e VAREJO NO BOOK.
  O RLP é pequeno e duro; o varejo por corretora é grande e é leitura. Ficam
  lado a lado em vez de um número só misturando os dois.
- **Cada card carrega o selo da fonte**: `B3 / RLP` (verde, marcação
  regulatória) ou `leitura` (cinza). Isso não é enfeite — é a diferença entre
  dado e palpite.
- **O lado vem dos últimos 15 minutos**, contados a partir do último negócio,
  não dos últimos N baldes. Numa fita rala, "os últimos 3 baldes" podem cobrir
  uma hora, e chamar isso de "últimos 15 min" seria mentira. Tem teste pra isso.
- **Quem lê é um laço em segundo plano, não o request.** A primeira versão lia
  dentro do endpoint e o primeiro GET levou **51 segundos**: o `.trd` do WIN
  tem 9,2 milhões de negócios (198 MB) e o bind mount do Windows entrega uns
  3 MB/s. Agora um laço lê no máximo 32 MB por passada (a cada 3 s) e guarda o
  snapshot; o endpoint só devolve o cache, em milissegundos. Enquanto alcança,
  a resposta traz `loading: true` e a tela avisa. Bônus: um dono só do estado =
  sem lock e sem snapshot pela metade. **Isso já pegou um bug real**: com a
  leitura dentro do request, dois GETs ao mesmo tempo liam o mesmo arquivo do
  offset zero e alimentavam o acumulador duas vezes — o WIN aparecia com
  9.212.024 negócios quando o arquivo só tem 4.606.012 (207.270.540 ÷ 45).
- **Fora do pregão a aba mostra "fita parada"** em vez de zerar os números.

### Arquivamento do tape (feito em 16/09/2026)

O Profit tinha **7 arquivos `.trd` no disco inteiro**, de meses de uso: ele só
grava a sessão cuja janela de Times & Trades foi aberta, e a virada de contrato
(WINZ25 → WINV26) deixa a pasta velha pra trás. Sem cópia, o histórico que o
backtest precisa nunca acumula, e dia de pregão perdido não volta.

`archive_tape()` em `adapters/profit_tape.py` copia toda sessão que crescer pra
`data/b3_tape/<CONTRATO>_<AAAA-MM-DD>.trd` (bind mount no compose). Escreve num
`.part` e só então renomeia, pra crash no meio nunca deixar arquivo truncado
parecendo sessão inteira; e nunca troca uma cópia grande por uma menor.

Rotina grátis que isso destrava: abrir o Profit **depois do fechamento** com o
T&T de WDO e WIN. Ele baixa o pregão inteiro de uma vez, o backend arquiva, e
sai um dia completo sem precisar de tempo real.

Primeiro uso, 16/09/2026: `WDOV26_2026-09-16.trd` (6,1 MB) e
`WINV26_2026-09-16.trd` (98 MB).

### O que falta (ordem)

1. Confirmar que o Profit escreve o `.trd` ao vivo (abrir Times & Trades do WDO
   e ver o arquivo crescer). Se não escrever, a aba só funciona em replay.
2. Comparar lado a lado com o `salasagradaai.com.br/preview` durante um pregão
   e anotar onde os dois discordam.
3. Fase 4 (gabarito D+1 da B3) e Fase 5 (níveis + avisos de voz).

## 8. Tempo real: o `.trd` não serve, e o que a ProfitDLL exige (16/09/2026)

### Medição que fecha a questão
Com o ProfitPro aberto e Times & Trades de WDO e WIN na tela, das 10:41 às 11:20:
o `.trd` do WDO foi gravado **uma vez** (10:45:40) e o do WIN **uma vez**
(10:47:29). Depois disso, 33 minutos sem nenhuma escrita — nem do tape nem dos
candles — enquanto os logs do próprio Profit seguiam escrevendo normalmente.

Conclusão: **o `.trd` é cache de histórico, não log que cresce.** O Profit
baixa a sessão até o instante em que a janela abre, grava, e o que chega depois
fica na memória dele. Serve pra replay e backtest; não serve pra gatilho.

(Falso rastro que investiguei e descartei: o log tem um `TAgentSummaryManager`,
que parecia ser o resumo por corretora. É só um componente de janela tratando
mensagem do Windows — `WM_DEVICECHANGE`, `WM_FONTCHANGE`. Não é dado.)

### ProfitDLL — pacote baixado e conferido (16/09/2026)

`C:\Users\diego\Downloads\ProfitDLL.zip`, 67 MB, versão de 08/09/2026.
Traz `ProfitDLL.dll` Win32 e Win64, manual de 79 páginas em pt/en e exemplos
em Python, C#, C++ e Delphi. Não traz chave nem readme.

**O tipo de negócio bate com o arquivo, campo por campo.** `TConnectorTrade`
tem `TradeDate`, `TradeNumber`, `Price`, `Quantity`, `Volume`, **`BuyAgent`**,
**`SellAgent`** e `TradeType` — os mesmos campos que eu decodifiquei no `.trd`.
O collector novo troca o leitor de arquivo pelo callback e o resto do caminho
(grupos, RLP, partição, tela) continua igual.

**O enum oficial confirma o RLP.** De `Exemplo C#/ProfitEnums.cs`:

```
CrossTrade = 1, AggressorBuyer = 2, AggressorSeller = 3, Auction = 4,
Surveillance = 5, Expit = 6, OptionExercise = 7, OverTheCounter = 8,
DerivativeTerm = 9, Index = 10, BTC = 11, OnBehalf = 12, RLP = 13,
BBT = 14, RFQ = 15, MPT = 16, TAC = 17, TAA = 18
```

O tipo 13 ser RLP era a aposta de maior peso da aba inteira e estava em
60-75% de confiança, deduzida da distribuição. Agora é fato, vindo do header
da própria Nelogica. O mesmo vale pro tipo 1, que eu tinha chutado como
"direto": é `CrossTrade`.

**Tem entrada só de market data.** `DLLInitializeMarketLogin(...)` inicializa
sem roteamento de ordem — responde sozinha a pergunta de "dá pra contratar só
o dado". A versão com roteamento é `DLLInitializeLogin`.

**O que falta é a chave.** As duas funções começam com
`pwcActivationKey` — "Chave de ativação fornecida para login" — mais usuário e
senha da conta correspondente. O zip é público; a chave vem do contrato. Ou
seja: o software está na mão, o acesso não.

### ProfitDLL — o que dá pra afirmar

- É biblioteca nativa do Windows que liga a aplicação direto na infraestrutura
  de Market Data e Roteamento da Nelogica, a mesma que o Profit usa: tick a
  tick, livro de ofertas, histórico e envio de ordem na B3.
- `TNewTradeCallback` / `TConnectorTrade` entrega por negócio: hora com
  milissegundo, preço, volume, lote, **agente comprador, agente vendedor** e
  quem agrediu. É exatamente o que a aba precisa.
- **É produto contratado à parte.** Não vem com a licença do Profit. O caminho
  oficial é e-mail pra `corporativo@nelogica.com.br` pra conhecer planos e
  testar. Depois de contratar, os arquivos saem da área logada do site.
- Requisito: Windows + internet. O `ProfitDLL.zip` traz DLL 32 e 64 bits,
  manual em PDF e programas de exemplo.
- **Preço: não achei.** A Nelogica não publica. O site de ajuda deles está
  atrás de Cloudflare e recusa leitura automática, e nenhuma página pública
  lista valor. Só sai perguntando.
- Conferido na máquina: **não há `ProfitDLL.dll` instalada** em nenhuma pasta
  Nelogica (só `MetaLib.dll` e `WebView2Loader.dll`, que não têm relação).

### O que perguntar no e-mail (encurtou depois do pacote conferido)
As perguntas 1 e 2 já se responderam sozinhas no manual e no header
(`DLLInitializeMarketLogin` existe; `BuyAgent`/`SellAgent` vêm no trade).
Sobrou:
1. **Como obter a chave de ativação** e quanto custa por mês pra uso
   individual, só market data.
2. Se a licença do Profit que já existe serve de pré-requisito ou se é
   contrato separado.
3. Se existe período de teste.

### Alternativa que vale cotar junto
**Cedro Technologies** — API REST/socket/websocket com times & trades da B3.
Não amarra em DLL de Windows nem em corretora, e o collector viraria um
processo normal em vez de um binário Windows. Vale pedir preço nos dois e
comparar antes de decidir.

## 9. Resolvido: tempo real pelo RTD do Profit (20/09/2026)

A seção 8 fechava dizendo que o `.trd` não serve pra gatilho e que o caminho
era contratar a ProfitDLL. **Não é mais.** O Profit expõe um servidor RTD
(`Arquivo → Exportar → Em tempo real RTD`, ou botão direito numa janela →
"Linkar Janela com Excel (RTD)") que entrega o Times & Trades negócio a
negócio, com corretora dos dois lados e agressor, já incluso na licença.

Não precisa de Excel. É COM local, sem porta TCP:
`RTDTrading.RtdServer`, CLSID `{272D2E65-05FB-4500-BD7B-5905D5B0A1B8}`.
Tópico do T&T = `(ferramenta, campo, linha)`, linha 0 = mais recente.
Campos: `DAT`, `ACP` (corretora compradora), `PRE`, `QUL`, `AVD` (vendedora),
`AGR`. `(ferramenta, "INFO", "ATV")` diz qual ativo a janela mostra.

O que isso muda no plano:
- Fases que dependiam de tempo real deixam de depender da chave da Nelogica.
- O e-mail pro `corporativo@nelogica.com.br` e a cotação da Cedro deixam de ser
  caminho crítico. Continuam valendo se um dia a fidelidade de 99% não bastar.

Implementação: `collector/profit_rtd_collector.py` (Windows) +
`backend/adapters/profit_rtd.py` + ingest em
`/api/players/ws/ingest/b3tape`. Detalhes de operação, limites medidos e
pegadinhas estão em `collector/README.md`, seção "Profit RTD B3 Tape
Collector".

### Limites medidos (não são bugs, são o teto do mecanismo)
- **Fidelidade 98,96%** contra o `.trd` de 18/09/2026 reproduzido no Replay.
  A perda é toda em rajada: a janela de 500 linhas cobre **65 ms** no pico
  (~7.700 negócios/s) e uma leitura de 3.000 tópicos custa até 90 ms.
- **Só um programa por vez.** Profit e BlackArrow registram o mesmo CLSID e
  quem abriu primeiro atende. Não dá pra escolher pelo cliente (a ROT está
  vazia e só existe um CLSID no registro).
- **Sem leilão e sem negócio direto.** A coluna de agressor só tem
  `Comprador`, `Vendedor` e `RLP` — o RLP vem, o resto é descartado e contado.
- **Corretora vem por nome, não por código.** Os 20 nomes vistos num replay
  inteiro batem com o `newagents.dat`; `BTG` e `Santander` são ambíguos e estão
  fixados no código que de fato opera (85 e 4090).

### Testar fora do pregão
Replay do Profit. A janela de T&T enche como se fosse ao vivo e o RTD serve
igual — foi assim que tudo acima foi medido num domingo. No replay o feed de
cotação fica congelado, então a aferição tem que ser contra o `.trd`.

## 10. Gravação do ao vivo (fechado em 21/09/2026)

**O buraco.** O acumulador ao vivo morava só na memória do backend. Ele começa
adotando o que o leitor de arquivo montou (o `.trd` do dia), mas o Profit para
de escrever esse arquivo logo depois de abrir a janela de T&T — por volta das
10h. Então um restart às 14h relia o arquivo (que termina às 10h) e sumia com
tudo entre 10h e 14h.

**O que foi feito.** Todo negócio que o ao vivo conta também vai pra disco, no
mesmo formato binário de 45 bytes do Profit (`append_trades`), um arquivo por
contrato e por dia em `PLAYERS_LIVE_DIR` (`data/b3_live`, montado no compose).
No boot o leitor de arquivo lê o `.trd` do dia e, quando termina, emenda a nossa
gravação por cima (`_replay_record`), jogando fora o que o arquivo já tinha. Só
depois disso o ao vivo adota o acumulador, como já fazia. A ordem é a mesma de
sempre: `.trd` → gravação nossa → RTD ao vivo, cada um cortado pelo horário do
último negócio do anterior.

Como a gravação usa o layout do Profit, ela é lida pelo mesmo `read_trades` —
em fatias de 32 MB, na thread do laço, não no handler do websocket. Enquanto
sobrar arquivo pra ler o leitor fica `busy` e os negócios do ao vivo esperam na
fila, igual já esperavam pelo `.trd`.

**Limite conhecido.** A gravação só é reproduzida se existir um `.trd` de hoje.
Na prática sempre existe, porque o RTD só funciona com a janela de T&T aberta e
é abrir a janela que cria o arquivo.

**Testes.** `backend/tests/unit/test_players_live_seed.py` — grava o que conta,
restart no meio do dia, não conta duas vezes o que o arquivo já tinha, e os
negócios esperam enquanto a gravação está sendo lida.

### Ainda aberto (menor)
- A linha do RLP no card usa `text-zinc-700` em 10px e está quase invisível,
  igual a linha dos 15 min estava antes de ser refeita.
- O card de "últimos 15 min" mostra número igual ao do dia enquanto a fita tiver
  menos de 15 minutos. Decidir se esconde ou marca "= o dia".
- A pasta `data/b3_live` cresce e ninguém limpa (um dia de WIN dá umas centenas
  de MB). Mesma situação de `data/b3_tape`.

## 11. O que a aba tem hoje (21/09/2026)

### Preço ao vivo por websocket
`/api/players/ws/tick` empurra **preço, hora do último negócio e contagem** a
cada 100 ms, que é o ritmo em que o collector entrega o negócio. O resto do
card (saldos por grupo, série e tabela de corretoras) continua no poll REST de
1 s — muda devagar o bastante. Poll de 100 ms chegou a existir e foi trocado:
era uma requisição por negócio pra fazer o trabalho de um socket aberto.

### Painel do Ibov (topo da aba)
- **Top 10 pesos** (`/api/ibov`): a barra é dimensionada pela **contribuição**
  (peso × variação), não pela variação — 3% numa ação de 0,5% de peso não move
  o índice e não pode desenhar igual à Vale.
- **Ações por nível**: quantas das 76 passaram de cada faixa (0/0,5/1/2/3/4/5%),
  cumulativo, com a barra de amplitude embaixo. Diz se a alta é do mercado
  inteiro ou de três nomes.
- Pesos: carteira teórica oficial da B3, em `backend/adapters/ibov_pesos.json`
  (fica junto do código porque `data/` é gitignored). Rebalanceia 3x por ano.
- Cotação: Yahoo, **atrasada 15 min** — está escrito no painel. O jeito certo é
  uma lista de ativos no Profit linkada no RTD; ficou pra depois.

### Tabela de corretoras
Filtro por grupo e por lado (comprado/vendido) e os quatro títulos ordenam a
lista (clique inverte, seta mostra por onde está). Tudo no cliente, em cima do
top 12 que o backend já manda.

### Leitura visual
Cinza escuro sobre fundo preto não se lia: `zinc-700/600` viraram `zinc-400`,
`zinc-500` virou `zinc-300`, os textos de 9-10 px foram pra 11 px. O gráfico de
saldo acumulado dobrou de altura (150 → 240) e as linhas foram de 1,5 pra 3 px.
O texto de abertura da aba saiu.
