# Apify — actors, campos e parâmetros

Referência para ajustar o motor (`scripts/gerar_leads.py`) quando a busca padrão
não bastar. Os dois actors já são usados em produção pela `plano-de-acao`.

## Tokens (NUNCA hardcode — o repo é versionado)

O script lê o token de fora do código, nesta ordem:

1. `APIFY_TOKEN` (env) — um único token; se setado, ganha de tudo.
2. `APIFY_TOKENS` (env) — vários separados por vírgula; escolhe o de maior saldo.
3. `scripts/apify_tokens.local` — um token por linha, **fora do Git**
   (está no `.gitignore`). É onde a máquina do time guarda as contas.

Quando há vários candidatos, o script consulta o saldo de cada um e usa o que
ainda tem orçamento no mês. A conta do time costuma estourar o teto de ~USD
5/mês, então deixe a conta reserva também na lista. Checar saldo manualmente:
`GET https://api.apify.com/v2/users/me/limits?token=<T>` → `data.current.monthlyUsageUsd`.

> As contas em uso ficam documentadas internamente (fora deste repo). Se um
> token vazar, **revogue e gere outro** no painel do Apify.

## Runs assíncronos (não use run-sync para buscas amplas)

Buscas grandes estouram o `run-sync` (~100 s). O script usa o padrão robusto:

1. `POST /v2/acts/{actor}/runs?token=T` → retorna `data.id` e `data.defaultDatasetId`.
2. `GET /v2/actor-runs/{id}?token=T` → poll até `status` = `SUCCEEDED`.
3. `GET /v2/datasets/{datasetId}/items?token=T&clean=true` → itens.

`{actor}` usa `~` no lugar de `/` (ex: `compass~crawler-google-places`).

## Actor: `compass/crawler-google-places` (Google Maps)

**Input** (o que o script manda):

```json
{
  "searchStringsArray": ["endocrinologista Tijuca Rio de Janeiro RJ"],
  "maxCrawledPlacesPerSearch": 20,
  "language": "pt-BR",
  "scrapePlaceDetailPage": true,
  "includeReviews": false,
  "includeImages": false
}
```

- `language` **tem que ser `pt-BR`** — `pt` sozinho não é aceito.
- `searchStringsArray` aceita **VÁRIAS queries num run só** — é assim que a fonte
  Instagram cruza N médicos com o Google numa única chamada (uma query por
  médico, `maxCrawledPlacesPerSearch: 1`).
- `scrapePlaceDetailPage: true` traz `website` e o endereço destrinchado.
- Deixamos `includeReviews`/`includeImages` em `false` para baratear e acelerar
  (só precisamos de `totalScore` e `reviewsCount`, que vêm sem baixar reviews).

**Campos de saída usados:** `title`, `categoryName`, `address`, `street`,
`city`, `state`, `phone`, `website`, `totalScore`, `reviewsCount`, `url`
(link do Maps), `searchString` (a query que gerou aquele place — usada pra casar
no cruzamento IG→Google).

> ⚠️ Nota do time: para nº de fotos leia `imagesCount` (não `imageUrls.Count`);
> para saber se a ficha é reivindicada, confira `responseFromOwnerText` nas
> reviews, não só `claimThisBusiness`. (Aqui não usamos fotos, mas fica o aviso
> caso alguém estenda o script.)

## Actor: `apify/instagram-scraper` (Instagram)

Usado de dois jeitos:

**A) Descoberta (fonte Instagram)** — busca de usuários por termo:

```json
{ "search": "endocrinologista Tijuca", "searchType": "user",
  "searchLimit": 40, "resultsType": "details", "resultsLimit": 1 }
```

Retorna perfis com detalhes: `username`, `fullName`, `biography`,
`followersCount`, `postsCount`, `verified`, `externalUrl`, `externalUrls`
(onde mora o link de WhatsApp), `businessCategoryName`.

- A busca casa por **nome + bio** (fonte "threads"); termos muito estreitos
  retornam pouco. Se vier pouco resultado, o script pede `searchLimit` maior e
  filtra localmente pela especialidade + região.

**B) Achar o @ de um médico (cruzamento Google→IG)** — mesma busca, com o nome
do médico: `"search": "<Nome> <especialidade> <cidade>"`. O script roda essas
buscas **em paralelo** (uma por médico faltante), capadas por `--max-ig-lookup`
para não gastar demais, e casa por similaridade de nome (Jaccard dos tokens).

**WhatsApp da bio:** vem embutido em `externalUrls[].lynx_url` como
`wa.me/<num>` ou `phoneNumber=<num>` — o script extrai via regex.

## Extração de Instagram a partir do "site" do GMB

Muito médico põe um **linktree/beacons** como site no Google. O script faz um
GET leve nesse site e procura `instagram.com/<handle>` no HTML. Se o próprio
`website` já for um link de Instagram, pega direto. Isso resolve boa parte do
cruzamento Google→IG **sem** gastar chamada de Apify.

## Custo aproximado

- Google Places: ~USD 0,007 por place.
- Instagram (details): ~USD 0,002–0,003 por perfil.
- Uma lista de 20 leads pela fonte Google, com ~15 buscas de IG de reforço,
  fica na casa de **USD 0,10–0,30**. Buscas de 50+ multiplicam proporcional —
  confirme com o usuário antes.
