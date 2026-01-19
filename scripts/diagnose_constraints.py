"""Quick feasibility diagnosis by toggling constraints.

This script runs short CP-SAT feasibility attempts while disabling one constraint at a time.
It's intended to help identify which constraint(s) make the model hard/infeasible.

Example:
  python scripts/diagnose_constraints.py --config config/scheduler.yaml --time-limit 60

Notes:
- This is a heuristic: "no solution" within a short limit can still mean feasible-but-hard.
- Use it to narrow down suspects, then validate by longer runs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))

from src.config.manager import ConfigManager
from src.pipeline.orchestrator import PipelineOrchestrator


def _iter_enabled_constraints(raw: Dict[str, Any]) -> List[Tuple[str, str]]:
	constraints = raw.get("constraints", {}) or {}
	pairs: List[Tuple[str, str]] = []
	for domain in ("lab", "theory", "cross_system"):
		domain_map = constraints.get(domain, {}) or {}
		for name, setting in domain_map.items():
			if not isinstance(setting, dict):
				continue
			if bool(setting.get("enabled", False)):
				pairs.append((domain, name))
	return pairs


def _filter_constraints(
	pairs: List[Tuple[str, str]],
	*,
	domains: List[str] | None,
	match: str | None,
	limit: int | None,
) -> List[Tuple[str, str]]:
	filtered = pairs
	if domains:
		allowed = {d.strip() for d in domains if d.strip()}
		filtered = [(d, n) for (d, n) in filtered if d in allowed]
	if match:
		pattern = re.compile(match)
		filtered = [(d, n) for (d, n) in filtered if pattern.search(f"{d}.{n}")]
	if limit is not None:
		filtered = filtered[: max(0, int(limit))]
	return filtered


def _make_overrides(
	base_raw: Dict[str, Any],
	*,
	time_limit: int,
	disable: Tuple[str, str] | None = None,
) -> Dict[str, Any]:
	raw = deepcopy(base_raw)
	raw.setdefault("runtime", {})
	raw["runtime"]["time_limit_sec"] = int(time_limit)
	raw["runtime"]["stop_after_first_solution"] = True
	raw["runtime"]["enable_trace"] = False
	raw["runtime"]["enable_lns"] = False

	if disable is not None:
		domain, name = disable
		raw.setdefault("constraints", {}).setdefault(domain, {}).setdefault(name, {})
		raw["constraints"][domain][name]["enabled"] = False

	return raw


def _attempt(config_path: Path, overrides: Dict[str, Any]) -> Dict[str, Any]:
	try:
		orchestrator = PipelineOrchestrator(config_path=config_path)
		# We want speed: run only through solve.
		orchestrator.load_config(overrides=overrides, strict=True)
		orchestrator.load_data()
		orchestrator.load_preprocessed_data()
		orchestrator.build_model()
		res = orchestrator.solve()
		return {
			"ok": True,
			"status": res.status,
			"status_code": res.status_code,
			"solution_count": res.solution_count,
			"wall_time": res.wall_time,
			"best_bound": res.best_bound,
			"objective_value": res.objective_value,
		}
	except Exception as e:  # noqa: BLE001
		return {
			"ok": False,
			"error": repr(e),
		}


def main() -> None:
	parser = argparse.ArgumentParser(description="Diagnose feasibility by disabling constraints")
	parser.add_argument("--config", type=str, default="config/scheduler.yaml")
	parser.add_argument("--time-limit", type=int, default=60, help="Seconds per attempt")
	parser.add_argument(
		"--domains",
		nargs="*",
		default=None,
		help="Only test constraints from these domains: lab theory cross_system",
	)
	parser.add_argument(
		"--match",
		type=str,
		default=None,
		help="Regex to select constraints by full name, e.g. 'teacher|overlap'",
	)
	parser.add_argument(
		"--limit",
		type=int,
		default=None,
		help="Only test the first N enabled constraints (after filtering)",
	)
	parser.add_argument(
		"--skip-baseline",
		action="store_true",
		help="Skip the baseline attempt (only run toggled constraints)",
	)
	parser.add_argument(
		"--output",
		type=str,
		default=None,
		help="Where to write the JSON report",
	)
	args = parser.parse_args()

	config_path = Path(args.config)
	manager = ConfigManager(base_dir=Path.cwd())
	manager.load(config_path, strict=True)
	base_raw = manager.raw_dict

	enabled_all = _iter_enabled_constraints(base_raw)
	enabled = _filter_constraints(
		enabled_all,
		domains=args.domains,
		match=args.match,
		limit=args.limit,
	)

	if args.output is None:
		ts = datetime.now().strftime("%Y%m%d_%H%M%S")
		args.output = f"output/diagnose_constraints_report_{ts}.json"

	report: Dict[str, Any] = {
		"config": str(config_path),
		"time_limit_sec": args.time_limit,
		"enabled_constraints_total": [f"{d}.{n}" for d, n in enabled_all],
		"enabled_constraints_tested": [f"{d}.{n}" for d, n in enabled],
		"baseline": None,
		"runs": [],
	}

	print(f"Enabled constraints (total): {len(enabled_all)}")
	print(f"Enabled constraints (tested): {len(enabled)}")
	if not args.skip_baseline:
		print("Running baseline...")
		baseline_overrides = _make_overrides(base_raw, time_limit=args.time_limit)
		report["baseline"] = _attempt(config_path, baseline_overrides)
		print("Baseline:", report["baseline"])

	for domain, name in enabled:
		label = f"{domain}.{name}"
		print(f"\nDisabling {label}...")
		overrides = _make_overrides(base_raw, time_limit=args.time_limit, disable=(domain, name))
		result = _attempt(config_path, overrides)
		entry = {"disabled": label, "result": result}
		report["runs"].append(entry)
		print(entry)

	out_path = Path(args.output)
	out_path.parent.mkdir(parents=True, exist_ok=True)
	out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
	print(f"\nWrote report to: {out_path}")


if __name__ == "__main__":
	main()
