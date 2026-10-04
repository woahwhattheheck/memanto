"""Bounded PEM normalizer comparison using the installed Memanto package."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

BASELINE_SHA = "8934ad1a7bbdf01c75d82feba5092e8ee23eadcc"
SOURCE_PATH = "memanto/app/services/conversation_memory_extraction_service.py"
output_dir = Path(os.environ["RUNNER_TEMP"])
baseline_source = subprocess.check_output(
    ["git", "show", f"{BASELINE_SHA}:{SOURCE_PATH}"], text=True
)
candidate_sha = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], text=True
).strip()
candidate_source = Path(SOURCE_PATH).read_text(encoding="utf-8")
blocked_events = []


def no_network(event, args):
    if event in {
        "socket.connect",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyaddr",
    }:
        blocked_events.append(event)
        raise RuntimeError("Network access disabled during PEM product execution")


sys.addaudithook(no_network)
from memanto.app.services import conversation_memory_extraction_service as candidate

baseline = types.ModuleType("memanto_pem_baseline")
exec(compile(baseline_source, f"{BASELINE_SHA}:{SOURCE_PATH}", "exec"), baseline.__dict__)
old_service = baseline.ConversationMemoryExtractionService(None)
new_service = candidate.ConversationMemoryExtractionService(None)


def deadline(signum, frame):
    raise TimeoutError("One bounded normalizer invocation exceeded 8 seconds")


signal.signal(signal.SIGALRM, deadline)


def normalize(service, content):
    signal.setitimer(signal.ITIMER_REAL, 8)
    try:
        started = time.perf_counter()
        result = service._normalize_candidates(
            [{"type": "fact", "content": content}], max_memories=1
        )
        return result, time.perf_counter() - started
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


# Warm imports/caches once; all subsequent numbers cover the full normalizer.
normalize(old_service, "Ordinary memory.")
normalize(new_service, "Ordinary memory.")
measurements = []
for shape in ("unclosed_lines", "uppercase_header_run"):
    for count in (250, 500, 1000, 2000):
        if shape == "unclosed_lines":
            content = "-----BEGIN PRIVATE KEY-----\n" * count
        else:
            content = "-----BEGIN " * count + "-----END PRIVATE KEY-----"
        old_output, old_seconds = normalize(old_service, content)
        new_output, new_seconds = normalize(new_service, content)
        assert old_output == new_output, (shape, count)
        measurements.append(
            {
                "shape": shape,
                "markers": count,
                "input_chars": len(content),
                "baseline_seconds": old_seconds,
                "candidate_seconds": new_seconds,
                "output_chars": len(new_output[0]["content"]),
                "outputs_identical": True,
            }
        )

import pytest

cases = [
    "tests/test_conversation_memory_extraction.py::test_redact_sensitive_data_helper",
    "tests/test_conversation_memory_extraction.py"
    "::test_redact_private_keys_preserves_header_boundaries",
    "tests/test_conversation_memory_extraction.py"
    "::test_extract_bounds_work_for_unclosed_private_key_headers",
]
pytest_args = [
    "-c", "pytest.ini", "-vv", "-ra", "-p", "no:cacheprovider",
    "--import-mode=importlib",
    "--junitxml=" + str(output_dir / "memanto-pem-scan.xml"),
    *cases,
]
print("PYTEST_ARGS=" + json.dumps(pytest_args), flush=True)
code = int(pytest.main(pytest_args))
result = {
    "baseline_sha": BASELINE_SHA,
    "candidate_sha": candidate_sha,
    "source_path": SOURCE_PATH,
    "baseline_source_sha256": hashlib.sha256(baseline_source.encode()).hexdigest(),
    "candidate_source_sha256": hashlib.sha256(candidate_source.encode()).hexdigest(),
    "python": sys.version,
    "pytest": pytest.__version__,
    "pytest_exit_code": code,
    "pytest_config": "pytest.ini",
    "selected_paths_and_nodes": cases,
    "blocked_network_events": blocked_events,
    "measurements": measurements,
    "method": (
        "One warmup per version, then one full _normalize_candidates call "
        "per size and shape; 8-second per-call guard. Real package imports. "
        "Extraction regression uses the maintained FakeClient fixture. "
        "No provider calls, hosted attack, full suite, or payout claim."
    ),
}
print("PEM_SCAN_RESULT=" + json.dumps(result, sort_keys=True), flush=True)
(output_dir / "memanto-pem-scan-result.json").write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8"
)
raise SystemExit(code if code else (1 if blocked_events else 0))
