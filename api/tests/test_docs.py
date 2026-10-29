"""docs/LESSONS.md maps each workshop lesson to the test that proves it: every test it names must exist."""

import re

from pheri.config import REPO_ROOT


def test_every_test_named_in_lessons_exists():
    text = (REPO_ROOT / "docs" / "LESSONS.md").read_text(encoding="utf-8")
    named = set(re.findall(r"(test_\w+\.py)::(test_\w+)", text))
    assert len(named) >= 30
    for file, name in sorted(named):
        source = (REPO_ROOT / "api" / "tests" / file).read_text(encoding="utf-8")
        assert re.search(rf"^def {name}\(", source, re.M), f"{file}::{name} is named in LESSONS.md but does not exist"
