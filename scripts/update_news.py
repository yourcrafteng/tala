#!/usr/bin/env python3
"""Refreshes news.json for talatoa.org.

Runs once a day from .github/workflows/update-news.yml. It asks two official,
public U.S. National Institutes of Health services for the newest items on
childhood and congenital acute myeloid leukemia (AML):

  * PubMed            - newly listed research papers
  * ClinicalTrials.gov - newly posted clinical trials open to children

and writes a short list to news.json, which index.html displays.
Uses only the Python standard library. If a source cannot be reached, the
items already in news.json from that source are kept, so the page never
goes blank because of one bad day.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "news.json")
UA = {"User-Agent": "talatoa.org news updater (https://talatoa.org)"}
MAX_PAPERS = 4
MAX_TRIALS = 2

# A title must be about leukemia AND about babies or children to be shown.
ABOUT_AML = re.compile(r"leuk(a)?emia|\bAML\b", re.I)
ABOUT_CHILDREN = re.compile(
    r"p(a)?ediatric|child|infan|congenital|neonat|newborn|adolescen", re.I)
# Headlines with these words are left out. This page is read by grieving
# families and by parents in the NICU.
LEAVE_OUT = re.compile(
    r"death|died|dying|fatal|mortalit|autops|post-?mortem|lethal|end[- ]of[- ]life"
    r"|palliative|hospice|bereave|retract|erratum|correction", re.I)


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip().rstrip(".")


def suitable(title):
    return bool(title and ABOUT_AML.search(title) and ABOUT_CHILDREN.search(title)
                and not LEAVE_OUT.search(title))


def pubmed():
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    term = ('("acute myeloid leukemia"[Title] OR "acute myeloid leukaemia"[Title] '
            'OR "AML"[Title] OR "congenital leukemia"[Title]) AND '
            '(pediatric[Title] OR paediatric[Title] OR childhood[Title] OR children[Title] '
            'OR infant[Title] OR infants[Title] OR congenital[Title] OR neonatal[Title])')
    common = {"db": "pubmed", "retmode": "json", "tool": "talatoa.org"}
    found = get_json(base + "esearch.fcgi?" + urllib.parse.urlencode(
        dict(common, term=term, retmax=25, sort="date")))
    ids = found["esearchresult"]["idlist"]
    if not ids:
        return []
    summ = get_json(base + "esummary.fcgi?" + urllib.parse.urlencode(
        dict(common, id=",".join(ids))))["result"]
    items = []
    for uid in ids:
        rec = summ.get(uid) or {}
        title = clean(rec.get("title"))
        if not suitable(title):
            continue
        date = (rec.get("sortpubdate") or "")[:10].replace("/", "-")
        if not re.match(r"\d{4}-\d{2}-\d{2}$", date):
            continue
        # Journals sometimes list a future issue date; show today's date instead.
        date = min(date, dt.date.today().isoformat())
        items.append({
            "kind": "Research paper",
            "title": title,
            "source": clean(rec.get("fulljournalname") or rec.get("source")) or "PubMed",
            "date": date,
            "url": "https://pubmed.ncbi.nlm.nih.gov/%s/" % uid,
        })
    return items[:MAX_PAPERS]


def trials():
    url = "https://clinicaltrials.gov/api/v2/studies?" + urllib.parse.urlencode({
        "query.cond": "acute myeloid leukemia",
        "aggFilters": "ages:child",
        "filter.overallStatus": "RECRUITING|NOT_YET_RECRUITING",
        "sort": "StudyFirstPostDate:desc",
        "pageSize": 25,
        "fields": "NCTId,BriefTitle,OverallStatus,StudyFirstPostDate",
    })
    items = []
    for study in get_json(url).get("studies", []):
        p = study.get("protocolSection", {})
        ident = p.get("identificationModule", {})
        status = p.get("statusModule", {})
        title = clean(ident.get("briefTitle"))
        date = (status.get("studyFirstPostDateStruct") or {}).get("date", "")
        if not (suitable(title) and re.match(r"\d{4}-\d{2}-\d{2}$", date) and ident.get("nctId")):
            continue
        items.append({
            "kind": "Clinical trial",
            "title": title,
            "source": "ClinicalTrials.gov",
            "date": date,
            "url": "https://clinicaltrials.gov/study/%s" % ident["nctId"],
        })
    return items[:MAX_TRIALS]


def main():
    try:
        with open(OUT, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {"items": []}

    items, status = [], {}
    for name, kind, fetch in (("pubmed", "Research paper", pubmed),
                              ("clinicaltrials", "Clinical trial", trials)):
        try:
            got = fetch()
            status[name] = "ok (%d)" % len(got)
        except Exception as err:  # keep yesterday's items for this source
            got = [i for i in old.get("items", []) if i.get("kind") == kind]
            status[name] = "kept previous: %s" % str(err)[:200]
        print(name, "->", status[name])
        items += got

    items.sort(key=lambda i: i["date"], reverse=True)
    new = {"items": items, "sources": status}
    if new["items"] == old.get("items") and old.get("updated"):
        new["updated"] = old["updated"]  # nothing new: leave the file untouched
    else:
        new["updated"] = dt.date.today().isoformat()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(new, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
