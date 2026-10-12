"""Security profiles: committed YAML, validated, with stricter fallbacks and overrides."""

import logging

import pytest

from openepw.agent.policy_config import (
    PROFILE_NAMES,
    load_policy,
    profile_for_serve,
    requires_moderation_key,
    weakened,
)


def write(tmp_path, text, name="override.local.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_the_packaged_profiles_differ_only_where_the_plan_says():
    hosted, local = load_policy("hosted"), load_policy("local")
    assert PROFILE_NAMES == ("hosted", "local")
    assert (hosted.strikes.action, hosted.strikes.reopen, hosted.moderation.on_error) == ("end_session", "deny", "block")
    assert (local.strikes.action, local.strikes.reopen, local.moderation.on_error) == ("warn", "allow", "allow")
    assert hosted.moderation.enabled and local.moderation.enabled
    assert "model_output" not in hosted.moderation.check and "model_output" not in local.moderation.check
    assert hosted.strikes.limit == 3 and hosted.strikes.warn_at == 2 and hosted.strikes.show_count
    assert hosted.strikes.counting == "session"
    assert "nrel.gov" in hosted.links.allowlist and hosted.links.policy == "allowlist"
    differences = {key for key in hosted.settings() if hosted.settings()[key] != local.settings()[key]}
    assert differences == {"profile", "strikes", "moderation"}


def test_profiles_report_their_source_and_a_stable_digest():
    first, again = load_policy("hosted"), load_policy("hosted")
    assert first.digest == again.digest and len(first.digest) == 12
    assert first.source.endswith("hosted.yaml") and first.digest != load_policy("local").digest


def test_an_override_extends_a_profile_and_changes_only_its_keys(tmp_path):
    path = write(tmp_path, "extends: hosted\nstrikes:\n  limit: 10\n")
    policy = load_policy(file=path)
    assert policy.strikes.limit == 10 and policy.strikes.action == "end_session"
    assert policy.profile == "hosted+override" and policy.source == str(path)


def test_bad_values_and_unknown_keys_fall_back_to_the_stricter_value(tmp_path, caplog):
    path = write(tmp_path, "extends: local\nstrikes:\n  action: maybe\n  limit: -4\n"
                           "moderation:\n  on_error: shrug\nmystery: 1\n")
    with caplog.at_level(logging.WARNING, logger="openepw.security"):
        policy = load_policy(file=path)
    # Each bad value takes the hosted (strictest shipped) value.
    assert (policy.strikes.action, policy.strikes.limit, policy.moderation.on_error) == ("end_session", 3, "block")
    assert policy.strikes.reopen == "allow"                   # untouched local values stay
    text = caplog.text
    assert "strikes.action" in text and "mystery" in text and "moderation.on_error" in text


def test_a_missing_file_falls_back_to_the_hosted_profile(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="openepw.security"):
        policy = load_policy(file=tmp_path / "nope.yaml")
    assert policy.profile == "hosted" and "not found" in caplog.text


def test_an_unknown_profile_name_is_an_error():
    with pytest.raises(ValueError):
        load_policy("lenient")


def test_serve_uses_local_on_localhost_and_hosted_when_remote():
    assert profile_for_serve("127.0.0.1") == "local" and profile_for_serve("localhost") == "local"
    assert profile_for_serve("0.0.0.0") == "hosted" and profile_for_serve("example.org") == "hosted"


def test_weakened_profiles_and_key_requirements_are_named(tmp_path):
    assert weakened(load_policy("hosted")) == []
    local = weakened(load_policy("local"))
    assert "strikes.action is warn" in local and "moderation.on_error is allow" in local
    off = load_policy(file=write(tmp_path, "extends: hosted\nmoderation:\n  enabled: false\n"))
    assert "moderation is off" in weakened(off)
    assert requires_moderation_key(load_policy("hosted")) and not requires_moderation_key(load_policy("local"))
    assert not requires_moderation_key(off)


def run_cli(monkeypatch, tmp_path, argv):
    """Run `openepw` with the chat loop, eval and web server replaced by recorders."""
    import uvicorn

    import openepw.agent.cli as agent_cli
    import openepw.agent.evals.command as eval_command
    import openepw.api.app as app_module
    from openepw.cli.main import main

    seen = {}

    async def fake_chat(service, **options):
        seen["chat"] = options
        return 0

    async def fake_eval(**options):
        seen["eval"] = options
        return 0

    monkeypatch.setattr(agent_cli, "main_chat", fake_chat)
    monkeypatch.setattr(agent_cli, "prepare_console", lambda: None)
    monkeypatch.setattr(agent_cli, "chat_model", lambda mode, **options: (None, None))
    monkeypatch.setattr(agent_cli, "chat_tracer", lambda env_file: (agent_cli.NullTracer(), None))
    monkeypatch.setattr(eval_command, "main_run", fake_eval)
    monkeypatch.setattr(app_module, "create_app", lambda service, **options: seen.setdefault("serve", options))
    monkeypatch.setattr(uvicorn, "run", lambda app, **options: None)
    assert main(["--data-root", str(tmp_path), *argv]) == 0
    return seen


def test_chat_eval_and_serve_choose_their_profiles(monkeypatch, tmp_path, capsys):
    assert run_cli(monkeypatch, tmp_path, ["chat"])["chat"]["security"].profile == "local"
    assert run_cli(monkeypatch, tmp_path, ["chat", "--security-profile", "hosted", "--reopen"])["chat"][
        "security"].profile == "hosted"
    assert run_cli(monkeypatch, tmp_path, ["eval"])["eval"]["security"].profile == "local"
    assert run_cli(monkeypatch, tmp_path, ["serve"])["serve"]["security_policy"].profile == "local"
    remote = run_cli(monkeypatch, tmp_path, ["serve", "--host", "0.0.0.0"])["serve"]
    assert remote["security_policy"].profile == "hosted" and remote["remote"] is True
    assert "Security profile: hosted" in capsys.readouterr().out


def test_a_weakened_profile_warns_when_serving_remotely(monkeypatch, tmp_path, capsys):
    run_cli(monkeypatch, tmp_path, ["serve", "--host", "0.0.0.0", "--security-profile", "local"])
    out = capsys.readouterr().out
    assert "WARNING: serving remotely with a weakened security profile" in out and "strikes.action is warn" in out
    run_cli(monkeypatch, tmp_path, ["serve", "--security-profile", "local"])
    assert "WARNING" not in capsys.readouterr().out                # local serving does not warn


def test_a_security_file_is_used_by_path(monkeypatch, tmp_path):
    path = write(tmp_path, "extends: hosted\nstrikes:\n  limit: 7\n")
    policy = run_cli(monkeypatch, tmp_path, ["chat", "--security-file", str(path)])["chat"]["security"]
    assert policy.strikes.limit == 7 and policy.profile == "hosted+override"


def test_the_example_override_loads_cleanly(caplog):
    from pathlib import Path

    example = Path(__file__).parents[2] / "config" / "security" / "example.local.yaml"
    with caplog.at_level(logging.WARNING, logger="openepw.security"):
        policy = load_policy(file=example)
    assert policy.strikes.limit == 10 and caplog.text == ""


def test_an_override_is_labelled_as_one_whatever_name_it_claims(tmp_path):
    spoof = load_policy(file=write(tmp_path, "extends: local\nprofile: hosted\n"))
    assert spoof.profile == "local+override" and spoof.strikes.action == "warn"
    lenient = load_policy(file=write(tmp_path, "profile: lenient\nstrikes:\n  limit: 9\n"))
    assert lenient.profile == "hosted+override"


def test_weakened_names_every_relaxation_of_the_hosted_profile(tmp_path):
    relaxed = load_policy(file=write(tmp_path, """extends: hosted
strikes:
  sources: [moderation]
  limit: 9
  counting: consecutive
moderation:
  check: [input]
scope:
  offtopic_clamp:
    min_chars: 2000
links:
  allowlist: [nrel.gov, evil.example]
external_text:
  max_chars: 900
"""))
    notes = " | ".join(weakened(relaxed))
    for expected in ("strike sources", "strikes.limit", "consecutive", "form_text", "upload_text",
                     "min_chars", "evil.example", "external_text.max_chars"):
        assert expected in notes, expected


def test_bad_keys_and_list_items_are_repaired_and_the_label_kept(tmp_path, caplog):
    path = write(tmp_path, "extends: local\nlimits: {1: 2}\nlinks:\n  allowlist: [nrel.gov, 5]\n"
                           "moderation:\n  check: [input, 7]\n")
    policy = load_policy(file=path)
    hosted = load_policy("hosted")
    assert policy.profile == "local+override" and policy.limits == {}
    assert policy.links.allowlist == hosted.links.allowlist
    assert policy.moderation.check == hosted.moderation.check
    assert len(caplog.records) < 10


def test_weakened_names_extra_domain_terms_and_a_hidden_count(tmp_path):
    path = write(tmp_path, "extends: hosted\nscope:\n  extra_domain_terms: [the]\nstrikes:\n  show_count: false\n")
    notes = " ".join(weakened(load_policy(file=path)))
    assert "extra domain terms" in notes and "strike count is not shown" in notes


def test_profiles_set_the_short_message_threshold_and_weakening_is_named(tmp_path):
    assert load_policy("hosted").strikes.unrelated_min_words == 4 == load_policy("local").strikes.unrelated_min_words
    path = write(tmp_path, "extends: hosted\nstrikes:\n  unrelated_min_words: 12\n")
    assert any("under 12 words" in note for note in weakened(load_policy(file=path)))
