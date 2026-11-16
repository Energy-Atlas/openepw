"""The web chat on staging in a real browser (Playwright), signed in as the tester (ADR 0006).

The default checks stop at the plan review, so nothing is retrieved; the session is switched to
guided mode first, so no model is called. Install with `pip install -e ".[e2e]"` and
`python -m playwright install chromium`.
"""

import re

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect
TIMEOUT = 60_000


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def signed_in(browser, staging, tmp_path_factory):
    """Sign in once through the landing page's window, as a person would; later pages reuse it."""
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    page.goto(staging.url, timeout=TIMEOUT)
    page.locator(".landing-prompt").click(timeout=TIMEOUT)
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Email").fill(staging.name)
    dialog.get_by_label("Password").fill(staging.password)
    dialog.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("textbox", name="Message")).to_be_enabled(timeout=TIMEOUT)
    state = tmp_path_factory.mktemp("staging") / "state.json"
    context.storage_state(path=str(state))
    context.close()
    return state


@pytest.fixture
def page(browser, signed_in):
    context = browser.new_context(viewport={"width": 1280, "height": 800}, storage_state=str(signed_in))
    page = context.new_page()
    yield page
    context.close()


def _open_guided(page, staging):
    page.goto(staging.url, timeout=TIMEOUT)
    expect(page.get_by_role("textbox", name="Message")).to_be_enabled(timeout=TIMEOUT)
    toggle = page.locator(".mode-toggle")
    if toggle.get_attribute("aria-pressed") == "true":
        expect(toggle).to_be_enabled(timeout=TIMEOUT)
        toggle.click()
        expect(toggle).to_have_text("Guided mode", timeout=TIMEOUT)
        expect(toggle).to_be_enabled(timeout=TIMEOUT)            # the switch has finished


def _say(page, text):
    """Type a message once the chat can take it (Enter does nothing while it is busy)."""
    expect(page.get_by_role("status", name="Working")).to_have_count(0, timeout=TIMEOUT)
    send = page.get_by_role("button", name=re.compile("^(Send|Confirm)$"))
    expect(send).to_be_enabled(timeout=TIMEOUT)
    field = page.get_by_role("textbox", name="Message")
    field.fill(text)
    field.press("Enter")
    expect(field).to_have_value("", timeout=TIMEOUT)          # sent


def _watch_transcript(page):
    """Record, at every change in the chat, how much of the newest message is hidden."""
    page.evaluate("""() => {
      window.__hidden = [];
      new MutationObserver(() => {
        const log = document.querySelector('.chat-transcript');
        window.__hidden.push(Math.round(log.scrollHeight - log.clientHeight - log.scrollTop));
      }).observe(document.querySelector('.chat-rail'), {childList: true, subtree: true, attributes: true});
    }""")


def test_the_header_buttons_take_clicks(page, staging):
    _open_guided(page, staging)
    hits = page.evaluate("""() => [...document.querySelectorAll('.chat-header button')].map(button => {
      const box = button.getBoundingClientRect();
      return document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2) === button;
    })""")
    assert hits and all(hits)


def test_place_preview_products_and_a_typed_plan_correction(page, staging):
    _open_guided(page, staging)
    _say(page, "AMY 2018 for Springfield")
    option = page.locator(".numbered-option").first
    expect(option).to_be_visible(timeout=TIMEOUT)
    option.click()
    popup = page.get_by_role("dialog", name="Selected location")
    expect(popup).to_be_visible(timeout=TIMEOUT)
    popup.get_by_role("button", name="Confirm").click()
    expect(popup).to_be_hidden(timeout=1_000)                 # gone on the click (2026-11-04)
    page.get_by_role("button", name=re.compile("Approve location")).click(timeout=TIMEOUT)
    dialog = page.get_by_role("region", name="Choose weather products")
    expect(dialog).to_be_visible(timeout=TIMEOUT)
    assert dialog.evaluate("node => node.closest('.reply-options') === null")
    dialog.get_by_role("checkbox", name="ERA5 actual year · Open-Meteo").check()
    dialog.get_by_role("button", name=re.compile("Confirm")).click()
    run = page.get_by_role("button", name="Run reviewed plan")
    expect(run).to_be_visible(timeout=TIMEOUT)
    expect(page.get_by_role("button", name="Change years")).to_have_count(0)
    _watch_transcript(page)
    _say(page, "2019 instead")
    card = page.get_by_label("Current question")
    expect(card).to_contain_text("2019", timeout=TIMEOUT)
    hidden = page.evaluate("window.__hidden")
    assert hidden and max(hidden) <= 2, f"the newest message slid behind the dock: {max(hidden)} px"


def test_the_map_asks_nothing_next_to_the_chat(page, staging):
    _open_guided(page, staging)
    requests = []
    page.on("request", lambda request: requests.append(request.url) if "/v1/catalog/point" in request.url else None)
    box = page.locator(".chat-dock").bounding_box()
    page.mouse.move(box["x"] - 8, box["y"] + 10)
    page.mouse.move(box["x"] - 6, box["y"] + 12)
    page.wait_for_timeout(500)
    assert not requests and page.locator(".point-card").count() == 0


@pytest.mark.real
def test_a_new_request_closes_the_results_card(page, staging):
    _open_guided(page, staging)
    _say(page, "AMY 2018 for Ithaca, NY")
    numbered = page.locator(".numbered-option")
    if numbered.count():
        numbered.first.click()
        page.locator(".option-tick").click()
    page.get_by_role("button", name=re.compile("Approve location")).click(timeout=TIMEOUT)
    dialog = page.get_by_role("region", name="Choose weather products")
    dialog.get_by_role("checkbox", name="ERA5 actual year · Open-Meteo").check(timeout=TIMEOUT)
    dialog.get_by_role("button", name=re.compile("Confirm")).click()
    page.get_by_role("button", name="Run reviewed plan").click(timeout=TIMEOUT)
    results = page.get_by_role("region", name="Visualize weather data")
    expect(results).to_be_visible(timeout=900_000)
    page.get_by_role("button", name="Start a new weather request").click(timeout=TIMEOUT)
    expect(results).to_be_hidden(timeout=TIMEOUT)
