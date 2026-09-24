# Quem são as baleias (e os bancos) do projeto

Atualizado em 22/09/2026. Números medidos nos pregões de 16/09 e 21/09/2026.

**Fonte da verdade:** `BALEIA_CODES` e `BANCO_CODES` em
`backend/use_cases/aggregate_players.py`. Este arquivo explica *por quê* cada
um está onde está. Se mudar o código, mude aqui também.

Pra listar com os números do dia:

```
python3 .claude/skills/aba-players/baleias.py data/b3_tape/WIN*.trd
```

## Baleia — 16 códigos

Mesas estrangeiras e os interdealer (corretoras que só atendem banco/mesa).
O código é a identidade, não o nome: a B3 troca nome muito mais do que troca
número.

| código | nome no Profit | quem é | % do grupo (WIN) | % do grupo (WDO) |
|---|---|---|---|---|
| 8 | UBS | UBS | 85,0% | 57,8% |
| 40 | Morgan | Morgan Stanley | 5,3% | 10,9% |
| 238 | Goldman | Goldman Sachs | 4,9% | 4,2% |
| 122 | BGC Liquidez | interdealer | 1,3% | 11,6% |
| 77 | Citigroup | Citi | 0,9% | 0,1% |
| 127 | Tullett | Tullett Prebon (interdealer) | 0,9% | 8,0% |
| 16 | JP Morgan | J.P. Morgan | 0,5% | 5,4% |
| 13 | Merrill | Merrill Lynch (BofA) | 0,5% | — |
| 262 | Mirae | Mirae Asset | 0,5% | 1,5% |
| 688 | ABN | ABN AMRO | 0,3% | 0,5% |

Os outros seis estão no mapa mas não negociaram nesses dois pregões:
**995** (UBS, 2º código), **45** e **833** (Credit Suisse), **206** (J.P.
Morgan, 2º código), **298** (Citibank), **363** (Credit Financier Invest).
Ficam lá porque um código que some por dois dias volta depois, e tirar do mapa
jogaria o fluxo dele em cima da sardinha sem ninguém perceber.

**O grupo todo é 9,9% da fita do WIN e 21,9% da do WDO.** Ou seja: a baleia
importa muito mais no dólar do que no índice.

**Na prática, baleia = UBS.** Ela sozinha é 85% do grupo no WIN e 58% no WDO.
Quando a tela diz "a baleia está comprando", quase sempre é a UBS. Se um dia a
leitura parecer estranha, é nela que se olha primeiro.

## Banco — 13 códigos

As **mesas** dos bancos e as **corretoras** por onde elas operam (Itaú, Ágora,
Santander). Mudou em 24/09/2026: a B3 só mostra a corretora por onde a ordem
passou, e os códigos das mesas (2028, 72, 254) nunca aparecem sozinhos na fita.
Só com as mesas, o grupo era Santander Institucional + Safra, 0,18% do WIN.

| código | nome no Profit | quem é |
|---|---|---|
| 2028 | Itau Unibanco | mesa do Itaú |
| 114 | Itau | corretora do Itaú |
| 72 | Bradesco | mesa do Bradesco |
| 39 | Agora | corretora do Bradesco |
| 27 / 622 / 635 | Santander Institucional / Santander | mesa do Santander |
| 4090 | Santander | corretora do Santander |
| 59 / 304 | Safra | mesa do Safra |
| 254 / 2659 | BB | mesa do Banco do Brasil |
| 1026 | BTG | Banco BTG Pactual |

## O custo: a corretora do banco também carrega cliente

RLP é o mecanismo da B3 em que a corretora é a contraparte do próprio cliente,
e a regra **só vale para cliente de varejo**. Então a fatia de RLP no fluxo de
uma corretora mede o quanto ela é varejo. Medido no WIN em 23 e 24/09/2026:

- Itaú **6-25%**, Ágora **2-3%** (mas 67% do volume em lotes de até 5),
  Santander **35-37%**, XP **25-29%**, BTG **21%**.
- UBS e Goldman: **0%**.

Os negócios RLP não entram em grupo nenhum (vão pra linha RLP), mas as ordens
dos clientes no book entram junto com a mesa, e a fita não separa um do outro.
Em 16/09/2026, com essas corretoras no banco, a linha marcou **+R$ 776 mi**
quando a tela de referência mostrava perto de zero.

O **BTG 85** (corretora) fica na sardinha, junto com XP, Genial, Clear e o
resto do varejo.

## Regra de quem não está no mapa

Quem não é baleia nem banco cai em **sardinha**, de propósito. Os três grupos
são uma partição fechada e os saldos têm que somar zero; um balde "outros"
sumiria com fluxo em silêncio — e era exatamente o que estava acontecendo com
3% do volume do WIN (a corretora do Santander).

## Onde isso é usado

- **Cards Baleia / Banco / Sardinha** (`/players`): saldo do dia e dos últimos
  15 min por grupo.
- **Card "agressões · 2 min"**: só entra agressão de baleia ou banco. Varejo
  fica de fora porque uma corretora agredindo 30.000 contratos é a soma dos
  clientes dela (18.574 negócios de ~2,9 contratos), não um player.
- **Tabela "quem girou o dia"**: as 12 maiores corretoras, com o grupo de cada.
