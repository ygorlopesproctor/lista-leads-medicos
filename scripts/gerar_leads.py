#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_leads.py — motor da skill `lista-leads-medicos`.

Gera uma lista de leads de medicos para prospeccao ativa do time de SDR.
Duas fontes possiveis (--fonte):
  - google     : parte do Google Maps (compass/crawler-google-places) e tenta
                 achar o Instagram de cada medico.
  - instagram  : parte do Instagram (apify/instagram-scraper) e tenta achar a
                 ficha do Google (GMB) / Total Score / avaliacoes de cada um.

Em ambos os casos o cruzamento e best-effort e honesto: a coluna
"Match Google<->IG" diz de onde veio o vinculo (site / busca / -) e nunca
inventa dado. Saida = CSV UTF-8 (com BOM) pronto para virar Google Sheets.

Uso:
  python gerar_leads.py --especialidade "endocrinologista" --cidade "Rio de Janeiro" \
      --estado "RJ" --bairro "Tijuca" --quantidade 20 --fonte google --out leads.csv

Sem dependencias externas (usa apenas a stdlib).
"""
import argparse, csv, json, os, re, sys, time, unicodedata, urllib.request, urllib.parse, urllib.error

# ---------------------------------------------------------------------------
# Tokens Apify — NUNCA hardcode aqui (o codigo vai pro GitHub). As fontes, em
# ordem de prioridade:
#   1. env APIFY_TOKEN  -> um unico token, usado direto.
#   2. env APIFY_TOKENS -> lista separada por virgula; escolhe o de maior saldo.
#   3. arquivo local `apify_tokens.local` (ao lado deste script, NAO versionado)
#      -> um token por linha; escolhe o de maior saldo.
# Quando ha varios candidatos, o script usa o que ainda tem orcamento no mes
# (a conta do time `blacksalesmed` costuma estourar o limite de 5 USD).
# ---------------------------------------------------------------------------
API = "https://api.apify.com/v2"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) leads-sdr/1.0"
LOCAL_TOKENS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apify_tokens.local")


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(url, payload, timeout=60):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _candidate_tokens():
    """(lista_de_tokens, forcado) — forcado=True quando veio de APIFY_TOKEN."""
    env = os.environ.get("APIFY_TOKEN")
    if env and env.strip():
        return [env.strip()], True
    toks = []
    multi = os.environ.get("APIFY_TOKENS", "")
    if multi:
        toks += [t.strip() for t in multi.split(",") if t.strip()]
    if os.path.exists(LOCAL_TOKENS_FILE):
        with open(LOCAL_TOKENS_FILE, encoding="utf-8") as f:
            toks += [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    seen, out = set(), []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out, False


def pick_token():
    toks, forced = _candidate_tokens()
    if not toks:
        sys.stderr.write(
            "[erro] Nenhum token Apify encontrado. Defina a variavel de ambiente "
            "APIFY_TOKEN (ou APIFY_TOKENS separada por virgula), ou crie o arquivo "
            f"{os.path.basename(LOCAL_TOKENS_FILE)} ao lado do script com um token por linha.\n")
        sys.exit(2)
    if forced or len(toks) == 1:
        return toks[0]
    best, best_left = toks[0], -1
    for t in toks:
        try:
            d = _get(f"{API}/users/me/limits?token={t}", timeout=30)["data"]
            used = d.get("current", {}).get("monthlyUsageUsd", 0) or 0
            cap = d.get("limits", {}).get("maxMonthlyUsageUsd", 5) or 5
            left = cap - used
            if left > best_left:
                best, best_left = t, left
        except Exception:
            continue
    sys.stderr.write(f"[token] usando ...{best[-6:]} (~${best_left:.2f} livres no mes)\n")
    return best


# ---------------------------------------------------------------------------
# Runner assincrono: start -> poll -> fetch dataset. Robusto para buscas
# grandes que estourariam o run-sync (aprendido na pratica).
# ---------------------------------------------------------------------------

def start_run(token, actor, payload):
    actor = actor.replace("/", "~")
    d = _post(f"{API}/acts/{actor}/runs?token={token}", payload, timeout=60)["data"]
    return d["id"], d["defaultDatasetId"]


def wait_and_fetch(token, run_id, dataset_id, timeout=420, interval=6):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            st = _get(f"{API}/actor-runs/{run_id}?token={token}", timeout=30)["data"]["status"]
        except Exception:
            st = "RUNNING"
        if st in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break
        time.sleep(interval)
    try:
        return _get(f"{API}/datasets/{dataset_id}/items?token={token}&clean=true", timeout=90)
    except Exception:
        return []


def run_actor(token, actor, payload, timeout=420):
    rid, did = start_run(token, actor, payload)
    return wait_and_fetch(token, rid, did, timeout=timeout)


def run_actor_batch(token, actor, payloads, timeout=420):
    """Dispara varios runs do mesmo actor em paralelo e coleta cada dataset."""
    handles = []
    for p in payloads:
        try:
            handles.append(start_run(token, actor, p))
        except Exception:
            handles.append(None)
    out = []
    for h in handles:
        out.append([] if h is None else wait_and_fetch(token, h[0], h[1], timeout=timeout))
    return out


# ---------------------------------------------------------------------------
# Helpers de parsing
# ---------------------------------------------------------------------------

def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def norm_name(s):
    s = strip_accents((s or "").lower())
    s = re.sub(r"\b(dr|dra|drs|dro)\b\.?", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return set(w for w in s.split() if len(w) > 2)


def name_match(a, b):
    ta, tb = norm_name(a), norm_name(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


ROLE_RE = re.compile(
    r"(?i)\b(endocrinologista|endocrino|endócrino|metabologista|clinica geral|"
    r"clínica geral|ginecologista|dermatologista|nutrologo|nutrólogo|medic[oa]|"
    r"consultorio|consultório|clinica|clínica|dr|dra|drs|dro)\b\.?")


def clean_person_name(title):
    """Extrai o nome da pessoa de um título de ficha do Google, que costuma vir
    poluído: 'Dra Larissa Garcia ׀ Endocrinologista', 'Dr. Alberto Gomes -
    Endocrinologista - Tijuca'. Sem isso a busca de IG por nome não casa."""
    t = title or ""
    for sep in ["|", "׀", "•", "·", " - ", " – ", " — ", ",", "/"]:
        if sep in t:
            t = t.split(sep)[0]
    t = ROLE_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" -·|,.")
    return t


IG_RE = re.compile(r"instagram\.com/(?!p/|reel/|explore/|accounts/)([A-Za-z0-9_.]+)")


def ig_from_url(url):
    if not url:
        return ""
    m = IG_RE.search(url)
    return m.group(1).strip("/").lower() if m else ""


def ig_from_website(website):
    """Tenta achar o @ do medico a partir do 'site' do GMB (que muitas vezes
    e um linktree/beacons) fazendo um GET leve e procurando instagram.com/<handle>."""
    if not website:
        return ""
    direct = ig_from_url(website)
    if direct:
        return direct
    try:
        req = urllib.request.Request(website, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read(300000).decode("utf-8", "ignore")
        return ig_from_url(html)
    except Exception:
        return ""


def wa_from_ig(rec):
    for e in (rec.get("externalUrls") or []):
        blob = (e.get("lynx_url", "") or "") + " " + (e.get("url", "") or "")
        m = re.search(r"wa\.me%2F(\d+)|wa\.me/(\d+)|phoneNumber%3D(\d+)|phoneNumber=(\d+)", blob)
        if m:
            return next(g for g in m.groups() if g)
    m = re.search(r"(\+?55\s?\d{2}\s?9?\d{4}[-\s]?\d{4})", rec.get("biography", "") or "")
    return m.group(1) if m else ""


COLUMNS = [
    "Nome", "Categoria", "Instagram", "Seguidores IG", "Site",
    "WhatsApp/Telefone", "Endereco", "Rua", "Cidade", "Estado",
    "Google Maps", "Total Score", "Qtd Avaliacoes", "Match Google<->IG",
]


def ig_url(handle):
    return f"https://instagram.com/{handle}" if handle else ""


# Separadores/pontuações exóticas que aparecem em títulos do Google e sujam a
# planilha (e atrapalham a reprodução do CSV na hora de subir pro Sheets).
_WEIRD = {
    "׀": "|", "❘": "|", "｜": "|", "•": "-", "·": "-",
    "–": "-", "—": "-", "‹": "", "›": "", "​": "",
    "‎": "", "‏": "", "﻿": "",
}


def clean_field(v):
    if v is None:
        return ""
    s = str(v)
    for k, r in _WEIRD.items():
        s = s.replace(k, r)
    # remove chars de controle
    s = "".join(ch for ch in s if ch == "\t" or ord(ch) >= 32)
    return re.sub(r"[ \t]+", " ", s).strip()


# ---------------------------------------------------------------------------
# FONTE = GOOGLE  (Maps -> acha Instagram)
# ---------------------------------------------------------------------------

def source_google(token, args):
    partes = [args.especialidade]
    if args.nicho:
        partes.append(args.nicho)
    if args.bairro:
        partes.append(args.bairro)
    partes.append(args.cidade)
    if args.estado:
        partes.append(args.estado)
    query = " ".join(p for p in partes if p)
    sys.stderr.write(f"[google] buscando: {query}\n")
    payload = {
        "searchStringsArray": [query],
        "maxCrawledPlacesPerSearch": args.quantidade,
        "language": "pt-BR",
        "scrapePlaceDetailPage": True,
        "includeReviews": False,
        "includeImages": False,
        "maxReviews": 0,
    }
    places = run_actor(token, "compass/crawler-google-places", payload, timeout=args.timeout)
    places = [p for p in places if p.get("title")][: args.quantidade]
    sys.stderr.write(f"[google] {len(places)} fichas retornadas\n")

    rows, faltando_ig = [], []
    for p in places:
        website = p.get("website", "") or ""
        handle = ig_from_website(website)
        rows.append({
            "Nome": p.get("title", ""),
            "Categoria": p.get("categoryName", "") or args.especialidade,
            "Instagram": ig_url(handle),
            "Seguidores IG": "",
            "Site": website,
            "WhatsApp/Telefone": p.get("phone", "") or "",
            "Endereco": p.get("address", "") or "",
            "Rua": p.get("street", "") or "",
            "Cidade": p.get("city", "") or args.cidade,
            "Estado": p.get("state", "") or (args.estado or ""),
            "Google Maps": p.get("url", "") or "",
            "Total Score": p.get("totalScore", "") if p.get("totalScore") is not None else "",
            "Qtd Avaliacoes": p.get("reviewsCount", "") if p.get("reviewsCount") is not None else "",
            "Match Google<->IG": "site" if handle else "",
        })
        if not handle:
            faltando_ig.append(len(rows) - 1)

    # Para quem ficou sem IG, roda buscas de usuario no Instagram em paralelo (capado).
    cap = min(len(faltando_ig), args.max_ig_lookup)
    alvos = faltando_ig[:cap]
    if alvos:
        sys.stderr.write(f"[google->ig] tentando achar IG de {len(alvos)} medicos via busca...\n")
        nomes = {i: clean_person_name(rows[i]["Nome"]) for i in alvos}
        payloads = [{
            "search": f"{nomes[i]} {args.especialidade}".strip(),
            "searchType": "user", "searchLimit": 5, "resultsType": "details", "resultsLimit": 1,
        } for i in alvos]
        results = run_actor_batch(token, "apify/instagram-scraper", payloads, timeout=args.timeout)
        for i, res in zip(alvos, results):
            best, best_sc = None, 0.0
            for rec in (res or []):
                sc = name_match(nomes[i], rec.get("fullName", ""))
                if sc > best_sc:
                    best, best_sc = rec, sc
            if best and best_sc >= 0.34:
                rows[i]["Instagram"] = ig_url(best.get("username", ""))
                rows[i]["Seguidores IG"] = best.get("followersCount", "") or ""
                rows[i]["Match Google<->IG"] = "busca"
                if not rows[i]["WhatsApp/Telefone"]:
                    rows[i]["WhatsApp/Telefone"] = wa_from_ig(best)
    return rows


# ---------------------------------------------------------------------------
# FONTE = INSTAGRAM  (perfil -> acha ficha do Google)
# ---------------------------------------------------------------------------

def source_instagram(token, args):
    termos = [args.especialidade]
    if args.nicho:
        termos.append(args.nicho)
    if args.bairro:
        termos.append(args.bairro)
    else:
        termos.append(args.cidade)
    query = " ".join(termos)
    sys.stderr.write(f"[instagram] buscando: {query}\n")
    payload = {
        "search": query, "searchType": "user",
        "searchLimit": max(args.quantidade * 2, 20),
        "resultsType": "details", "resultsLimit": 1,
    }
    recs = run_actor(token, "apify/instagram-scraper", payload, timeout=args.timeout)

    esp_key = strip_accents(args.especialidade.lower()).split()[0][:6]  # ex: 'endocr'
    local_key = strip_accents((args.bairro or args.cidade).lower())
    filtrados = []
    for r in recs:
        u = r.get("username")
        if not u:
            continue
        blob = strip_accents(((r.get("fullName", "") or "") + " " + (r.get("biography", "") or "")).lower())
        if esp_key and esp_key not in blob:
            continue
        r["_local"] = local_key in blob
        filtrados.append(r)
    # prioriza quem cita o local na bio, depois por seguidores
    filtrados.sort(key=lambda r: (0 if r.get("_local") else 1, -(r.get("followersCount") or 0)))
    filtrados = filtrados[: args.quantidade]
    sys.stderr.write(f"[instagram] {len(filtrados)} perfis apos filtro\n")

    # Cruzamento com Google: 1 unico run com varias queries (searchStringsArray).
    queries = [f"{r.get('fullName','')} {args.especialidade} {args.cidade}" for r in filtrados]
    gmb_by_query = {}
    if queries:
        sys.stderr.write("[instagram->google] cruzando com Google Maps (1 run)...\n")
        payload_g = {
            "searchStringsArray": queries,
            "maxCrawledPlacesPerSearch": 1,
            "language": "pt-BR",
            "scrapePlaceDetailPage": True,
            "includeReviews": False,
            "includeImages": False,
        }
        places = run_actor(token, "compass/crawler-google-places", payload_g, timeout=args.timeout)
        for p in places:
            gmb_by_query.setdefault(p.get("searchString", ""), p)

    rows = []
    for r, q in zip(filtrados, queries):
        g = gmb_by_query.get(q)
        # fallback: casa por nome se a chave da query nao bateu
        if not g:
            for p in gmb_by_query.values():
                if name_match(r.get("fullName", ""), p.get("title", "")) >= 0.5:
                    g = p
                    break
        matched = bool(g and name_match(r.get("fullName", ""), g.get("title", "")) >= 0.34)
        rows.append({
            "Nome": r.get("fullName", "") or r.get("username", ""),
            "Categoria": (g.get("categoryName") if g else "") or args.especialidade,
            "Instagram": ig_url(r.get("username", "")),
            "Seguidores IG": r.get("followersCount", "") or "",
            "Site": r.get("externalUrl", "") or (g.get("website", "") if g else ""),
            "WhatsApp/Telefone": wa_from_ig(r) or (g.get("phone", "") if g else ""),
            "Endereco": (g.get("address", "") if g else ""),
            "Rua": (g.get("street", "") if g else ""),
            "Cidade": (g.get("city", "") if g else args.cidade),
            "Estado": (g.get("state", "") if g else (args.estado or "")),
            "Google Maps": (g.get("url", "") if g else ""),
            "Total Score": (g.get("totalScore", "") if g and g.get("totalScore") is not None else ""),
            "Qtd Avaliacoes": (g.get("reviewsCount", "") if g and g.get("reviewsCount") is not None else ""),
            "Match Google<->IG": "busca" if matched else "",
        })
    return rows


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--especialidade", required=True)
    ap.add_argument("--nicho", default="")
    ap.add_argument("--cidade", required=True)
    ap.add_argument("--bairro", default="")
    ap.add_argument("--estado", default="")
    ap.add_argument("--quantidade", type=int, default=20)
    ap.add_argument("--fonte", choices=["google", "instagram"], required=True)
    ap.add_argument("--out", default="leads.csv")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--max-ig-lookup", type=int, default=15,
                    help="teto de buscas de IG na fonte google (custo/tempo)")
    args = ap.parse_args()

    token = pick_token()
    rows = source_google(token, args) if args.fonte == "google" else source_instagram(token, args)

    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: clean_field(r.get(k, "")) for k in COLUMNS})

    com_ig = sum(1 for r in rows if r["Instagram"])
    com_gmb = sum(1 for r in rows if r["Total Score"] != "")
    sys.stderr.write(
        f"\n[ok] {len(rows)} leads -> {args.out}\n"
        f"     com Instagram: {com_ig}/{len(rows)} | com ficha Google: {com_gmb}/{len(rows)}\n")
    print(json.dumps({"total": len(rows), "com_instagram": com_ig,
                      "com_google": com_gmb, "arquivo": args.out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
