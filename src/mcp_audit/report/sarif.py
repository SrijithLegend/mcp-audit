"""SARIF 2.1.0, so GitHub code scanning can show a scan like any other finding.

There is no source file to point at -- the "location" of a poisoned tool
description is the server, not a line in the repo. We emit a synthetic location
(the target) so GitHub has somewhere to hang the result, and put the real detail in
the message.
"""

from __future__ import annotations

import json

from ..models import Report, Verdict

SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
LEVEL = {
    Verdict.CONFIRMED: "error",
    Verdict.SUSPECTED: "warning",
    Verdict.CLEAN: "note",
    Verdict.INCONCLUSIVE: "note",
}


def to_sarif(report: Report, artifact: str = "mcp-server") -> str:
    reported = [f for f in report.findings if f.verdict is not Verdict.CLEAN]
    rules = {}
    results = []
    for f in reported:
        rule_id = f"mcp-audit/{f.signal.kind}" + (f"/{f.signal.detail}" if f.signal.detail else "")
        rules[rule_id] = {
            "id": rule_id,
            "name": f.signal.kind,
            "shortDescription": {"text": f"Behaviour change: {f.signal.kind}"},
            "fullDescription": {
                "text": (
                    "The model behaved differently when the server's prose was present, "
                    "measured over repeated trials against a sanitized copy of the same tools."
                )
            },
            "defaultConfiguration": {"level": LEVEL[f.verdict]},
            "help": {"text": "https://github.com/SrijithLegend/mcp-audit#how-it-works"},
        }
        s = f.signal
        results.append(
            {
                "ruleId": rule_id,
                "level": LEVEL[f.verdict],
                "message": {
                    "text": (
                        f"{f.verdict.value}: tool '{s.tool}' — {s.kind}"
                        + (f" [{s.detail}]" if s.detail else "")
                        + f" fired in {s.real_hits}/{s.n_real} real trials vs "
                        f"{s.san_hits}/{s.n_san} sanitized (p_adj={s.p_adj:.4f}, "
                        f"direction={s.direction})."
                    )
                },
                "partialFingerprints": {"mcpAuditSignal": f"{report.inventory_sha256[:16]}:{s.label()}"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": artifact, "uriBaseId": "%SRCROOT%"},
                            "region": {"startLine": 1},
                        }
                    }
                ],
            }
        )
    sarif = {
        "$schema": SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "mcp-audit",
                        "informationUri": "https://github.com/SrijithLegend/mcp-audit",
                        "version": report.engine_version or "0.0.0",
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
                "properties": {
                    "target": report.target,
                    "inventorySha256": report.inventory_sha256,
                    "model": report.model,
                    "trials": report.trials,
                    "verdict": report.verdict.value,
                },
            }
        ],
    }
    return json.dumps(sarif, indent=2, ensure_ascii=False)
