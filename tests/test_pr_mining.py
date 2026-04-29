from pathlib import Path

import pytest

from repoagentbench.pr_mining import (
    PRRef,
    detect_framework,
    extract_test_files_from_diff,
    generate_verify_sh,
    split_diff_by_tests,
)


# ---- PRRef.from_url ----

@pytest.mark.parametrize("url,expected", [
    ("https://github.com/octocat/Hello-World/pull/6", ("octocat", "Hello-World", 6)),
    ("https://github.com/pallets/click/pull/3299", ("pallets", "click", 3299)),
    ("http://github.com/encode/httpx/pull/2701", ("encode", "httpx", 2701)),
])
def test_pr_ref_parses_valid_urls(url, expected):
    pr = PRRef.from_url(url)
    assert (pr.owner, pr.repo, pr.number) == expected


def test_pr_ref_rejects_non_pr_urls():
    with pytest.raises(ValueError):
        PRRef.from_url("https://github.com/owner/repo/issues/1")


# ---- extract_test_files_from_diff ----

def test_extract_test_files_python():
    diff = (
        "diff --git a/tests/test_options.py b/tests/test_options.py\n"
        "diff --git a/src/click/core.py b/src/click/core.py\n"
        "diff --git a/tests/conftest.py b/tests/conftest.py\n"
    )
    files = extract_test_files_from_diff(diff)
    assert "tests/test_options.py" in files
    assert "src/click/core.py" not in files
    # conftest doesn't match our test patterns; that's intentional — conftest
    # changes should travel with source, not with the test seed.
    assert "tests/conftest.py" not in files


def test_extract_test_files_polyglot():
    diff = "\n".join(f"diff --git a/{p} b/{p}" for p in [
        "src/foo_test.go",
        "src/foo.go",
        "frontend/Button.test.tsx",
        "frontend/Button.tsx",
        "frontend/__tests__/util.js",
        "tests/integration.rs",
        "src/lib.rs",
        "spec/widget_spec.rb",
    ]) + "\n"
    files = extract_test_files_from_diff(diff)
    assert set(files) == {
        "src/foo_test.go",
        "frontend/Button.test.tsx",
        "frontend/__tests__/util.js",
        "tests/integration.rs",
        "spec/widget_spec.rb",
    }


def test_extract_test_files_dedupes():
    diff = (
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
    )
    assert extract_test_files_from_diff(diff) == ["tests/test_x.py"]


# ---- split_diff_by_tests ----

SAMPLE_DIFF = """diff --git a/src/click/core.py b/src/click/core.py
index abc..def 100644
--- a/src/click/core.py
+++ b/src/click/core.py
@@ -1,3 +1,3 @@
-old source
+new source
 unchanged
diff --git a/tests/test_options.py b/tests/test_options.py
index 111..222 100644
--- a/tests/test_options.py
+++ b/tests/test_options.py
@@ -1,2 +1,3 @@
 existing
+added test
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 333..444 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1 +1,2 @@
+- new entry
"""


def test_split_diff_separates_tests_from_source():
    tests, source = split_diff_by_tests(SAMPLE_DIFF)
    assert "tests/test_options.py" in tests
    assert "src/click/core.py" not in tests
    assert "src/click/core.py" in source
    assert "tests/test_options.py" not in source
    assert "CHANGELOG.md" in source  # non-test = source


def test_split_diff_preserves_full_hunks():
    tests, source = split_diff_by_tests(SAMPLE_DIFF)
    assert "+added test" in tests
    assert "+new source" in source
    assert "+- new entry" in source


def test_split_diff_empty_input():
    assert split_diff_by_tests("") == ("", "")


def test_split_diff_no_tests():
    diff = (
        "diff --git a/src/foo.py b/src/foo.py\n"
        "@@ -1 +1 @@\n"
        "-old\n+new\n"
    )
    tests, source = split_diff_by_tests(diff)
    assert tests == ""
    assert "src/foo.py" in source


# ---- detect_framework ----

def test_detect_framework_pytest_via_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert detect_framework(tmp_path) == "pytest"


def test_detect_framework_pytest_via_python_files(tmp_path):
    # No standard config files but has .py files → pytest fallback
    (tmp_path / "main.py").write_text("print('hi')\n")
    assert detect_framework(tmp_path) == "pytest"


def test_detect_framework_go(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/x\n")
    assert detect_framework(tmp_path) == "go"


def test_detect_framework_cargo(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    assert detect_framework(tmp_path) == "cargo"


def test_detect_framework_npm(tmp_path):
    (tmp_path / "package.json").write_text("{}\n")
    assert detect_framework(tmp_path) == "npm"


def test_detect_framework_priority_cargo_over_pytest(tmp_path):
    # Mixed-language repo: Cargo wins over a stray Python file
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    (tmp_path / "scripts" / "build.py").parent.mkdir()
    (tmp_path / "scripts" / "build.py").write_text("\n")
    assert detect_framework(tmp_path) == "cargo"


def test_detect_framework_none(tmp_path):
    (tmp_path / "README.md").write_text("only docs\n")
    assert detect_framework(tmp_path) is None


# ---- generate_verify_sh ----

def test_generate_verify_pytest_with_specific_files(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    script = generate_verify_sh(["tests/test_a.py"], "pytest", tmp_path)
    assert script is not None
    assert "python -m pytest -x --tb=short tests/test_a.py" in script
    assert "pip install -e '.[dev]'" in script


def test_generate_verify_pytest_picks_up_requirements_txt(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "requirements.txt").write_text("pytest\n")
    script = generate_verify_sh(["tests/t.py"], "pytest", tmp_path)
    assert "pip install -r requirements.txt" in script


def test_generate_verify_pytest_picks_up_pep735_groups(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='x'\n[dependency-groups]\ntests = ['pytest']\n"
    )
    script = generate_verify_sh(["tests/t.py"], "pytest", tmp_path)
    assert "pip install --group tests" in script
    assert "pip install --group dev" in script


def test_generate_verify_pytest_no_test_files_runs_full_suite(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    script = generate_verify_sh([], "pytest", tmp_path)
    # Without specific files, the runner is bare pytest
    assert "python -m pytest -x --tb=short\n" in script


def test_generate_verify_go(tmp_path):
    script = generate_verify_sh(["foo_test.go"], "go", tmp_path)
    assert script == (
        "#!/bin/bash\n# Auto-generated by `repoagentbench infer`.\n"
        "set -uo pipefail\ngo test ./...\n"
    )


def test_generate_verify_cargo(tmp_path):
    script = generate_verify_sh(["tests/lib.rs"], "cargo", tmp_path)
    assert "cargo test\n" in script


def test_generate_verify_npm(tmp_path):
    script = generate_verify_sh(["foo.test.ts"], "npm", tmp_path)
    assert "npm install" in script
    assert "npm test" in script


def test_generate_verify_unknown_framework_returns_none(tmp_path):
    assert generate_verify_sh([], "ruby-rspec", tmp_path) is None
