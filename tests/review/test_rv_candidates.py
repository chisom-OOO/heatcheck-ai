"""Run the reviewer's semantic checks against the actual Research / Experience bundles.

Skipped (= NOT_RUN) unless the bundle exists. Set HEATCHECK_REVIEW_RESEARCH_BUNDLE,
HEATCHECK_REVIEW_RESEARCH_SYN_BUNDLE and/or HEATCHECK_REVIEW_EXPERIENCE_BUNDLE.
"""

from __future__ import annotations

import subprocess
import sys

from tests.review.review_checks import experience_problems, research_problems
from tests.review.review_support import (
    ENV_EXPERIENCE_BUNDLE,
    ENV_RESEARCH_BUNDLE,
    ENV_RESEARCH_SYN_BUNDLE,
    ROOT,
    env_path,
    no_network,  # noqa: F401
    require_bundle,
    stale_seconds,
)

E001_DEFAULT = ROOT / "tests" / "fixtures" / "quotes" / "e001"


def _report(problems: list[str]) -> str:
    return "EXPECTED no problems; ACTUAL:\n  " + "\n  ".join(problems)


def test_research_real_bundle(no_network):  # noqa: F811
    manifest, recs = require_bundle(ENV_RESEARCH_BUNDLE)
    problems = research_problems(manifest, recs, real=True)
    assert not problems, _report(problems)


def test_research_synthetic_fixture(no_network):  # noqa: F811
    manifest, recs = require_bundle(ENV_RESEARCH_SYN_BUNDLE)
    problems = research_problems(manifest, recs, real=False)
    assert not problems, _report(problems)


def test_experience_bundle(no_network):  # noqa: F811
    manifest, recs = require_bundle(ENV_EXPERIENCE_BUNDLE, E001_DEFAULT)
    path = env_path(ENV_EXPERIENCE_BUNDLE, E001_DEFAULT)
    problems = experience_problems(path, manifest, recs, stale_s=stale_seconds())
    assert not problems, _report(problems)


def test_experience_bundle_cli_validator():
    """E-001 A1 replayed through the CLI exactly as the task file states."""
    path = env_path(ENV_EXPERIENCE_BUNDLE, E001_DEFAULT)
    if path is None:
        import pytest

        pytest.skip("NOT_RUN: no E-001 bundle")
    out = subprocess.run([sys.executable, "-m", "heatcheck.contracts.bundle", str(path)],
                         capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0 and out.stdout.startswith("PASS"), out.stdout + out.stderr
