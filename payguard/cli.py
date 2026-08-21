"""payguard CLI — Phase 2: scan command (static analysis only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from payguard.detector.discovery import discover_payment_units
from payguard.detector.static_rules import run_static_rules
from payguard.shared.enums import DefectClass


@click.group()
def main() -> None:
    """PayGuard — payment integration defect detector."""


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
@click.option("--min-confidence", type=float, default=0.0)
def scan(path: str, fmt: str, min_confidence: float) -> None:
    """Scan a repository for payment integration defects (static analysis)."""
    repo = Path(path)
    units = discover_payment_units(repo)

    if not units:
        click.echo(f"No payment-relevant code found in {path}", err=True)
        sys.exit(0)

    all_hits = []
    for unit in units:
        hits = run_static_rules(unit)
        for hit in hits:
            if hit.confidence >= min_confidence:
                all_hits.append({
                    "rule_id": hit.rule_id,
                    "defect_class": hit.defect_class.value,
                    "severity": hit.severity.value,
                    "confidence": round(hit.confidence, 3),
                    "file": unit.file,
                    "start_line": unit.start_line,
                    "end_line": unit.end_line,
                    "scenario_ids": hit.scenario_ids,
                    "evidence_lines": hit.evidence_lines,
                    "explanation": hit.explanation,
                    "detector_source": "STATIC",
                    "verified": False,
                })

    if fmt == "json":
        click.echo(json.dumps(all_hits, indent=2))
    else:
        if not all_hits:
            click.echo("No findings.")
            return

        _severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        all_hits.sort(key=lambda h: (_severity_order.get(h["severity"], 9), -h["confidence"]))

        click.echo(f"\nPayGuard static scan — {len(all_hits)} finding(s)\n")
        for h in all_hits:
            sev_color = {
                "CRITICAL": "red", "HIGH": "yellow", "MEDIUM": "blue", "LOW": "white"
            }.get(h["severity"], "white")
            click.echo(
                f"  [{click.style(h['severity'], fg=sev_color)}] "
                f"{h['rule_id']} · {h['defect_class']} · "
                f"confidence={h['confidence']:.0%} · UNVERIFIED"
            )
            click.echo(f"    {Path(h['file']).name}:{h['start_line']}-{h['end_line']}")
            if h["evidence_lines"]:
                for ev in h["evidence_lines"][:2]:
                    click.echo(f"      → {ev}")
            click.echo(f"    {h['explanation'][:120]}...")
            click.echo()
