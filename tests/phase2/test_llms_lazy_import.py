"""Regression test for the memory fix in chinatravel/agent/llms.py (Phase 2 plan Step 1).

``init_llm("TPCLLM")`` is on the hot path for every Phase 2 solve (deterministic
orchestrator wires a stub backbone LLM). It must not pull in transformers/vllm/torch
(~0.5-1 GB RSS) since Phase 2 never uses a local-model backend.
"""

from __future__ import annotations

import subprocess
import sys


def test_tpcllm_init_does_not_import_torch_stack():
    code = (
        "import sys\n"
        "from chinatravel.agent.load_model import init_llm\n"
        "init_llm('TPCLLM')\n"
        "heavy = {m for m in ('torch', 'vllm', 'transformers') if m in sys.modules}\n"
        "assert not heavy, f'unexpectedly imported: {heavy}'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
