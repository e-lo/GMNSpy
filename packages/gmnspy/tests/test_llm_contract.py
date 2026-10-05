"""Contract tests: recorded provider replies, through the real adapters and LLMParser.

Each fixture under ``tests/fixtures/llm/`` holds one provider exchange (response JSON plus the
request's top-level body keys). Every shipped fixture is hand-authored from the provider's public
API reference, not a real recording (see its ``"_recorded": false`` and ``"source"``); re-record
with ``scripts/record_llm_fixtures.py`` once you have real keys, and re-check "expected" before
committing.

The contract test uses a bare :class:`~gmnspy.select.parse.LLMParser`: no prompt context and
provider-default temperature, so ``request_keys`` describe the minimal request each adapter sends.
"""

import json
from pathlib import Path

import pytest
from gmnspy.llm.providers import ADAPTERS
from gmnspy.select.parse import LLMParser

pytestmark = pytest.mark.usefixtures("no_network")

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "llm").glob("*_select.json"))


def test_every_provider_has_a_fixture() -> None:
    """Every adapter the registry can build has exactly one recorded (or hand-authored) fixture."""
    assert {json.loads(p.read_text())["provider"] for p in FIXTURES} == set(ADAPTERS)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_recorded_reply_parses_to_the_expected_intent(path: Path, fake_api) -> None:
    """Replaying ``path``'s recorded reply through the real adapter yields the expected intent."""
    fixture = json.loads(path.read_text())
    method, endpoint = fixture["endpoint"].split(" ", 1)
    fake_api.add(method, endpoint, body=fixture["response"])
    adapter = ADAPTERS[fixture["provider"]](api_key="test-key", transport=fake_api.transport())
    intent = LLMParser(adapter, fixture["model"]).parse(fixture["utterance"])
    expected = fixture["expected"]
    got = (intent.facility.ref, intent.facility.direction, intent.from_anchor, intent.to_anchor)
    assert got == (expected["ref"], expected["direction"], expected["from_anchor"], expected["to_anchor"])
    assert sorted(fake_api.body()) == fixture["request_keys"]
