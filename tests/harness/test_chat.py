"""Console conversation controls keep execution and artifact IDs explicit."""

import asyncio

from openepw.harness.agent import AgentIntent, AgentResult
from openepw.harness.chat import ChatSession, load_model_key


class Model:
    def __init__(self):
        self.prompts = []
        self.intent = AgentIntent(kind="weather", lat=42.44, lon=-76.5,
                                  product="historical", years=[2024])

    def parse(self, prompt):
        self.prompts.append(prompt)
        return self.intent


class Port:
    def __init__(self):
        self.calls = []
        self.uploaded = []

    async def call(self, name, **arguments):
        self.calls.append((name, arguments))
        if name == "artifact_inspect":
            return {"artifact_id": arguments["artifact_id"], "role": "weather",
                    "bytes": 123, "sha256": "a" * 64,
                    "simulation_ready": False,
                    "qc_issue_codes": ["MISSING_CRITICAL_VARIABLE"]}
        if name == "plan_inspect":
            return {"kind": "weather"}
        if name == "job_cancel":
            return {"state": "running", "cancellation_requested": True}
        if name == "job_retry_failed":
            return {"id": "r" * 32}
        raise AssertionError(name)

    async def upload_file(self, path):
        self.uploaded.append(str(path))
        return "u" * 32

    async def read_artifact(self, artifact_id):
        assert artifact_id == "w" * 32
        return b"EPW bytes"


class Agent:
    def __init__(self, model):
        self.model = model
        self.plan_hash = None
        self.job_id = None
        self.calls = []

    async def run(self, prompt, *, auto_submit=False, baseline_override=None):
        intent = self.model.parse(prompt)
        self.calls.append(("run", auto_submit, baseline_override, intent.kind))
        self.plan_hash = "p" * 64
        if auto_submit:
            self.job_id = "j" * 32
            return AgentResult("completed", "Job completed; simulation_ready=false.",
                               self.plan_hash, self.job_id, ("w" * 32,))
        return AgentResult("review_required", "Review the plan.", self.plan_hash)

    async def submit_plan(self, kind):
        self.calls.append(("submit", kind))
        self.job_id = "j" * 32
        return AgentResult("completed", "Job completed.", self.plan_hash,
                           self.job_id, ("w" * 32,))

    async def resume(self, job_id=None):
        self.calls.append(("resume", job_id))
        return AgentResult("completed", "Job completed; simulation_ready=false.",
                           self.plan_hash, job_id or self.job_id, ("w" * 32,))


def session():
    model = Model()
    agent = Agent(model)
    port = Port()
    return ChatSession(agent, port, model), agent, model, port


def test_default_chat_auto_submits_and_followup_uses_only_confirmed_context():
    chat, agent, model, _ = session()

    async def exercise():
        first = await chat.handle("Get Ithaca 2024 historical weather")
        assert "completed" in first
        assert agent.calls[0] == ("run", True, None, "weather")
        model.intent = AgentIntent(kind="future", method="morph",
                                   climate_scenario="ssp245",
                                   climate_period=(2036, 2065))
        second = await chat.handle("Use that EPW for SSP245 morph in 2036-2065")
        assert "completed" in second
        assert agent.calls[1][2] == "w" * 32
        assert "Prior confirmed context" in model.prompts[1]
        assert "w" * 32 in model.prompts[1]
        assert "Get Ithaca 2024 historical weather" not in model.prompts[1]

    asyncio.run(exercise())


def test_manual_toggle_submit_status_and_retry():
    chat, agent, _, port = session()

    async def exercise():
        assert "manual" in await chat.handle("/auto off")
        assert "review_required" in await chat.handle("Ithaca 2024")
        assert agent.calls[0][1] is False
        assert "completed" in await chat.handle("/submit")
        assert ("plan_inspect", {"plan_hash": "p" * 64}) in port.calls
        assert "completed" in await chat.handle("/status")
        assert "Cancellation requested" in await chat.handle("/cancel")
        assert "completed" in await chat.handle("/retry")
        assert agent.calls[-1] == ("resume", "r" * 32)

    asyncio.run(exercise())


def test_upload_select_inspect_and_save_without_model_paths(tmp_path):
    chat, agent, model, port = session()
    epw = tmp_path / "my baseline.epw"
    epw.write_bytes(b"fixture")
    saved = tmp_path / "result.epw"

    async def exercise():
        assert "u" * 32 in await chat.handle(f"/upload {epw}")
        assert port.uploaded == [str(epw)]
        model.intent = AgentIntent(kind="future", method="morph",
                                   climate_scenario="ssp245",
                                   climate_period=(2036, 2065))
        await chat.handle("Make future weather from my uploaded baseline")
        assert agent.calls[-1][2] == "u" * 32
        assert str(epw) not in model.prompts[-1]
        assert "MISSING_CRITICAL_VARIABLE" in await chat.handle("/inspect last")
        assert "saved" in await chat.handle(f"/save last {saved}")
        assert saved.read_bytes() == b"EPW bytes"
        assert "exists" in await chat.handle(f"/save last {saved}")

    asyncio.run(exercise())


def test_ambiguous_artifact_reference_requires_selection():
    chat, agent, model, _ = session()
    chat.weather_artifacts = ("a" * 32, "b" * 32)
    model.intent = AgentIntent(kind="future", method="morph",
                               climate_scenario="ssp245", climate_period=(2036, 2065))
    result = asyncio.run(chat.handle("Use that EPW for future weather"))
    assert "/baseline" in result
    assert not agent.calls


def test_key_loader_reads_env_without_modifying_it(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    original = b'# local\nOPENAI_API_KEY="sk-local-test"\nANOTHER=untouched\n'
    path.write_bytes(original)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert load_model_key(path) == "sk-local-test"
    assert path.read_bytes() == original
    monkeypatch.setenv("OPENAI_API_KEY", "sk-shell-test")
    assert load_model_key(path) == "sk-shell-test"
    assert path.read_bytes() == original
