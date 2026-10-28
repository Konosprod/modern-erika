"""Fill in the untranslated messages of a .po file with the DeepL API (free plan included).

Usage:
  export DEEPL_AUTH_KEY=…            # DeepL API key (free keys end with :fx)
  uv run python tools/translate_deepl.py --lang fr [--dry-run] [--rooms 1,2]

- Translates "system" and "room" entries whose msgstr is empty; leaves existing
  translations and the vocabulary (synonyms, written by hand) alone.
- One call per room, with the room's other texts as context (not billed).
- Each translation gets the comment "DeepL, to review"; the file is saved after each
  room, so the run can be interrupted and restarted.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict

import polib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGETS = {"fr": "FR", "en": "EN-US", "de": "DE", "es": "ES", "it": "IT", "pt": "PT-PT",
           "nl": "NL", "pl": "PL", "ru": "RU", "ko": "KO", "zh": "ZH"}
FORMALITY = {"FR", "DE", "ES", "IT", "PT-PT", "NL", "PL", "RU"}  # languages supporting "formality"
BATCH = 50  # texts per request (API limit)
MARK = "DeepL, to review"
CONTEXT = ("Texts from a 1986 Japanese adventure game for the PC-8801 (science fiction, "
           "adult content). The player is an amnesiac pilot. ")


def api_url(key: str, path: str) -> str:
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    return f"https://{host}/v2/{path}"


def call(key: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(api_url(key, path), data=data, method="POST" if data else "GET",
                                 headers={"Authorization": f"DeepL-Auth-Key {key}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"DeepL: error {e.code} — {e.read().decode(errors='replace')}")


def group(entries) -> dict[str, list]:
    """Entries to translate, grouped by room ("system" apart)."""
    groups = defaultdict(list)
    for e in entries:
        kind = e.msgctxt.split()[0]
        if kind == "system":
            groups["system"].append(e)
        elif kind == "room":
            groups[f"room {e.msgctxt.split()[1]}"].append(e)
    return groups


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--lang", default="fr")
    p.add_argument("--dry-run", action="store_true", help="don't call DeepL: only count")
    p.add_argument("--rooms", help="only these rooms, e.g. 2,3,4")
    args = p.parse_args()
    target = TARGETS.get(args.lang)
    if not target:
        raise SystemExit(f"unsupported language: {args.lang} ({', '.join(TARGETS)})")
    path = os.path.join(ROOT, "translations", f"{args.lang}.po")
    po = polib.pofile(path)
    groups = group(po)
    todo = {name: [e for e in es if not e.msgstr] for name, es in groups.items()}
    if args.rooms:
        wanted = {f"room {int(n):02d}" for n in args.rooms.split(",")}
        todo = {k: v for k, v in todo.items() if k in wanted}
    todo = {k: v for k, v in todo.items() if v}
    chars = sum(len(e.msgid) for es in todo.values() for e in es)
    print(f"{sum(map(len, todo.values()))} texts, {chars} characters, {len(todo)} groups -> {target}")
    if args.dry_run:
        return
    key = os.environ.get("DEEPL_AUTH_KEY")
    if not key:
        raise SystemExit("set DEEPL_AUTH_KEY (DeepL API key)")
    usage = call(key, "usage")
    left = usage["character_limit"] - usage["character_count"]
    print(f"DeepL quota: {usage['character_count']} / {usage['character_limit']} characters used")
    if chars > left:
        raise SystemExit(f"not enough quota: {chars} characters to translate, {left} left")
    for name, entries in todo.items():
        context = CONTEXT + "\n".join(e.msgid for e in groups[name])
        for start in range(0, len(entries), BATCH):
            batch = entries[start : start + BATCH]
            payload = {"text": [e.msgid for e in batch], "source_lang": "JA", "target_lang": target,
                       "context": context}
            if target in FORMALITY:
                payload["formality"] = "prefer_more"
            result = call(key, "translate", payload)
            for e, t in zip(batch, result["translations"]):
                e.msgstr = t["text"]
                e.tcomment = MARK
        po.save(path)
        print(f"  {name}: {len(entries)} texts", flush=True)
    print(f"{path}: {po.percent_translated()}% translated")


if __name__ == "__main__":
    sys.exit(main())
