#!/usr/bin/env python3
"""Read-only diagnostics pairing saved model responses with their actual transcript."""
import argparse
import difflib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def ids_in(obj):
    result = set()
    if isinstance(obj, dict):
        if isinstance(obj.get("id"), str):
            result.add(obj["id"])
        for value in obj.values():
            result.update(ids_in(value))
    elif isinstance(obj, list):
        for item in obj:
            result.update(ids_in(item))
    return result


def diagnose(folder, last=2):
    meta = read(folder / "manifest.json")
    segments = read(folder / "segments.json")
    source = {s["id"]: s["text"] for s in segments}
    lines = [f"Source: {meta.get('source_filename')}", f"Script: {meta.get('version')}; run state: {meta.get('status')}",
             f"Source SHA256: {meta.get('source_sha256')}"]
    for response_path in sorted(folder.glob("response_[0-9]*.json"))[-last:]:
        suffix = response_path.stem.split("_", 1)[1]
        answer = read(response_path)
        request = read(folder / f"request_{suffix}.json")
        prompt = request["messages"][1]["content"]
        data = json.loads(prompt.rsplit("DATA:\n", 1)[1])
        allowed = ids_in(data)
        lines += ["", f"Response {suffix}; supplied source IDs: {', '.join(sorted(allowed))}",
                  f"Completion: {(answer.get('metrics') or {}).get('done_reason')}"]
        try:
            payload = json.loads(answer["content"])
            if "paragraphs" in payload:
                lines.append("Readable-report writing stage (fact references, not new transcript extraction):")
                for paragraph in payload["paragraphs"]:
                    lines.append(f"  {paragraph.get('section')}: {paragraph.get('text')} [facts {paragraph.get('facts')}]")
                continue
            facts = payload["facts"]
        except (ValueError, KeyError, TypeError):
            lines.append("Invalid JSON/facts array. Raw response retained in archive.")
            continue
        for index, fact in enumerate(facts, 1):
            if not isinstance(fact, dict):
                lines.append(f"Finding {index}: invalid object")
                continue
            lines.append(f"Finding {index}: {fact.get('kind')!r}: {fact.get('text')!r}")
            for evidence in fact.get("evidence", []):
                if isinstance(evidence, int):
                    lines.append(f"  Evidence ref {evidence}: version 2.2.2 resolves source text in Python; inspect request_meta_{suffix}.json.")
                    continue
                if not isinstance(evidence, dict):
                    lines.append("  Invalid evidence object")
                    continue
                sid, quote = evidence.get("id"), evidence.get("quote")
                original = source.get(sid)
                if sid not in allowed:
                    lines.append(f"  {sid}: ID WAS NOT SUPPLIED IN THIS REQUEST")
                if original is not None and isinstance(quote, str) and quote in original:
                    lines.append(f"  {sid}: exact quote matches the cited source")
                else:
                    lines += [f"  {sid}: QUOTE MISMATCH", f"    Model quote: {quote!r}", f"    Cited source: {original!r}"]
                    if isinstance(quote, str) and quote:
                        elsewhere = [key for key, text in source.items() if quote in text]
                        if elsewhere:
                            lines.append("    Exact quote found in: " + ", ".join(elsewhere[:5]))
                        else:
                            nearest = max(source, key=lambda key: difflib.SequenceMatcher(None, quote, source[key]).ratio())
                            lines.append(f"    Closest source (diagnostic only, not an accepted citation): {nearest}: {source[nearest]!r}")
            interp = fact.get("interpretation")
            if interp:
                lines.append(f"  Interpretation: {interp!r}")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("--last", type=int, default=2)
    args = p.parse_args()
    if args.last < 1:
        p.error("--last must be positive")
    try:
        print(diagnose(args.archive.expanduser(), args.last))
    except (OSError, ValueError, KeyError, TypeError) as e:
        p.exit(1, f"Cannot inspect archive: {e}\n")


if __name__ == "__main__":
    main()
