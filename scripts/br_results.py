#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
br_results.py — robot LOTERIA AI : écrit br_results.json (30 derniers concursos Mega-Sena et Lotofácil avec
le vrai prêmio et le nombre de ganhadores de chaque faixa, + date du prochain concurso annoncée par la Caixa).

Sources :
  1. API officielle Caixa  servicebus2.caixa.gov.br/portaldeloterias/api/{jeu}[/{n}]   (principale)
  2. Miroir public         loteriascaixa-api.herokuapp.com/api/{jeu}/{n}               (recoupement / secours)
Recoupement : pour chaque concurso présent dans les deux, dezenas, ganhadores et prêmios doivent être
identiques, sinon le robot échoue (rien n'est publié). Si la Caixa ne répond pas, le miroir est utilisé seul.

Format : {"updated", "megasena": [{date, draw, numbers[6], payouts{"6","5","4"}, winners{...}, estimate}],
          "lotofacil": [{... numbers[15], payouts{"15","14","13","12","11"} ...}], "next": {"megasena", "lotofacil"}}
payouts[k] = null quand personne n'a gagné cette faixa ; concursos du plus récent au plus ancien.
"""
import json, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "br_results.json"
KEEP = 30
CAIXA = "https://servicebus2.caixa.gov.br/portaldeloterias/api"
MIRROR = "https://loteriascaixa-api.herokuapp.com/api"
GAMES = {"megasena": dict(n=6, pool=60, ranks=["6", "5", "4"]),
         "lotofacil": dict(n=15, pool=25, ranks=["15", "14", "13", "12", "11"])}


def get(url, tries=4, pause=2.0):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (LOTERIA AI results robot)", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(pause * (i + 1))
    print(f"  {url} : {last}", file=sys.stderr)
    return None


def day(s):
    d, m, y = map(int, s.split("/"))
    return date(y, m, d)


def from_caixa(x, g):
    ks = GAMES[g]["ranks"]
    payouts = {k: None for k in ks}; winners = {k: 0 for k in ks}
    for r in x.get("listaRateioPremio") or []:
        f = r.get("faixa")
        if f and 1 <= f <= len(ks):
            winners[ks[f - 1]] = int(r.get("numeroDeGanhadores") or 0)
            v = float(r.get("valorPremio") or 0)
            payouts[ks[f - 1]] = v if v > 0 else None
    return dict(date=day(x["dataApuracao"]).isoformat(), draw=int(x["numero"]), numbers=sorted(int(v) for v in x["listaDezenas"]),
                payouts=payouts, winners=winners, estimate=float(x.get("valorEstimadoProximoConcurso") or 0) or None)


def from_mirror(x, g):
    ks = GAMES[g]["ranks"]
    payouts = {k: None for k in ks}; winners = {k: 0 for k in ks}
    for p in x.get("premiacoes") or []:
        f = p.get("faixa")
        if f and 1 <= f <= len(ks):
            winners[ks[f - 1]] = int(p.get("ganhadores") or 0)
            v = float(p.get("valorPremio") or 0)
            payouts[ks[f - 1]] = v if v > 0 else None
    return dict(date=day(x["data"]).isoformat(), draw=int(x["concurso"]), numbers=sorted(int(v) for v in x["dezenas"]),
                payouts=payouts, winners=winners, estimate=float(x.get("valorEstimadoProximoConcurso") or 0) or None)


def check(g, d):
    c = GAMES[g]
    if len(d["numbers"]) != c["n"] or len(set(d["numbers"])) != c["n"] or not all(1 <= v <= c["pool"] for v in d["numbers"]):
        raise SystemExit(f"{g} {d['draw']} : dezenas invalides {d['numbers']}")


def build(g):
    latest = get(f"{CAIXA}/{g}")
    source = "caixa"
    if latest is None:
        latest = get(f"{MIRROR}/{g}/latest")
        source = "mirror"
        if latest is None:
            raise SystemExit(f"{g} : aucune source ne répond")
    top = int(latest["numero"] if source == "caixa" else latest["concurso"])
    nxt = latest.get("dataProximoConcurso")
    out = []
    for n in range(top, top - KEEP, -1):
        x = latest if n == top else (get(f"{CAIXA}/{g}/{n}") if source == "caixa" else get(f"{MIRROR}/{g}/{n}"))
        if x is None and source == "caixa":
            x = get(f"{MIRROR}/{g}/{n}"); d = from_mirror(x, g) if x else None
        else:
            d = (from_caixa(x, g) if source == "caixa" else from_mirror(x, g)) if x else None
        if d is None:
            raise SystemExit(f"{g} {n} : concurso introuvable")
        # Le numéro du concurso doit être celui demandé, et chaque concurso doit précéder le suivant dans le temps
        if d["draw"] != n:
            raise SystemExit(f"{g} : concurso {n} demandé, {d['draw']} reçu")
        if out and d["date"] > out[-1]["date"]:
            raise SystemExit(f"{g} {n} : date {d['date']} après celle du concurso {n + 1} ({out[-1]['date']})")
        check(g, d); out.append(d)
        if source == "caixa": time.sleep(1.2)
    # Recoupement avec le miroir sur les 3 derniers concursos (le miroir peut avoir un peu de retard)
    agreed = 0
    if source == "caixa":
        for d in out[:3]:
            m = get(f"{MIRROR}/{g}/{d['draw']}", tries=2)
            if not m or int(m.get("concurso", -1)) != d["draw"]:
                continue
            md = from_mirror(m, g)
            for k in ("draw", "date", "numbers", "payouts", "winners"):
                if md[k] != d[k]:
                    raise SystemExit(f"{g} {d['draw']} : Caixa et miroir divergent sur {k} : {d[k]} ≠ {md[k]}")
            agreed += 1
    print(f"{g} : {len(out)} concursos (source {source}), {agreed} recoupés avec le miroir", file=sys.stderr)
    nxt_iso = day(nxt).isoformat() if nxt else None
    if (datetime.now(timezone.utc).date() - date.fromisoformat(out[0]["date"])).days > 14:
        raise SystemExit(f"{g} : dernier concurso {out[0]['date']} trop ancien")
    return out, nxt_iso


def main():
    data = {"megasena": None, "lotofacil": None, "next": {}}
    for g in GAMES:
        data[g], data["next"][g] = build(g)
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if {k: old.get(k) for k in data} == data:
        print("Aucun changement."); return
    data = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **data}
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"br_results.json : Mega-Sena {data['megasena'][0]['draw']} ({data['megasena'][0]['date']}), Lotofácil {data['lotofacil'][0]['draw']} ({data['lotofacil'][0]['date']}), next {data['next']}")


if __name__ == "__main__":
    main()
