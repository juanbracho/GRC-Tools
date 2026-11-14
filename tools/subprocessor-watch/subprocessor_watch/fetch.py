"""Polite fetching: robots.txt respected, generic User-Agent, timeouts, one retry."""

import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "GRC-Tools-SubprocessorWatch/0.1 (once-daily check of public subprocessor lists)"
TIMEOUT = 30.0


class FetchError(Exception):
    pass


class Fetcher:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True)
        self._robots: dict[str, RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            rp = RobotFileParser()
            try:
                resp = self.client.get(f"{host}/robots.txt")
                # No robots.txt (404) means no restrictions; other errors mean be careful.
                rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
                if resp.status_code >= 500:
                    rp.disallow_all = True
            except httpx.HTTPError:
                rp.disallow_all = True
            self._robots[host] = rp
        return self._robots[host].can_fetch(USER_AGENT, url)

    def __call__(self, url: str, render: str | None = None) -> str:
        if not self.allowed(url):
            raise FetchError("blocked by robots.txt")
        if render:
            return self._browser().render(url, render)
        last = None
        for attempt in range(2):
            try:
                resp = self.client.get(url)
                if resp.status_code == 200:
                    return resp.text
                last = f"HTTP {resp.status_code}"
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            if attempt == 0:
                time.sleep(5)
        raise FetchError(last)

    def _browser(self) -> "BrowserRenderer":
        if not hasattr(self, "_renderer"):
            self._renderer = BrowserRenderer()
        return self._renderer

    def close(self) -> None:
        if hasattr(self, "_renderer"):
            self._renderer.close()
        self.client.close()


# Vanta trust centers show each subprocessor in one cell ("Name • Purpose", location below)
# and 10 per page. This rebuilds every page's rows as a plain 3-column table.
_VANTA_ROWS_JS = """
() => Array.from(document.querySelectorAll('table tr')).map(tr => {
  const name = tr.querySelector('[data-variant="Body/L/Medium"]');
  const loc = tr.querySelector('[class*="_location_"]');
  const head = (tr.querySelector('[class*="_header_"]') || tr).innerText.split('\\n')[0];
  const parts = head.split('•');
  return [name ? name.innerText : parts[0], parts.slice(1).join('•'), loc ? loc.innerText : ''];
})
"""


class BrowserRenderer:
    """Headless Chromium for pages drawn by JavaScript. Started only when a vendor needs it."""

    def __init__(self):
        from playwright.sync_api import sync_playwright  # heavy import, only when needed
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()

    def render(self, url: str, mode: str) -> str:
        # Tall window: some pages (Notion) only draw blocks that are on screen.
        page = self._browser.new_page(user_agent=USER_AGENT, viewport={"width": 1400, "height": 4000})
        try:
            page.goto(url, wait_until="load", timeout=60_000)
            page.wait_for_selector("table tr", timeout=45_000)
            if mode == "vanta":
                return self._vanta(page)
            if mode == "browser":
                page.wait_for_timeout(3_000)  # let lazy tables finish drawing
                for _ in range(10):
                    page.mouse.wheel(0, 3_000)
                    page.wait_for_timeout(500)
                self._expand_toggles(page)
                return page.content()
            raise FetchError(f"unknown render mode {mode!r}")
        except FetchError:
            raise
        except Exception as exc:  # timeouts, navigation errors
            raise FetchError(f"browser: {type(exc).__name__}") from None
        finally:
            page.close()

    @staticmethod
    def _expand_toggles(page, rounds: int = 5) -> None:
        """Open collapsed sections (Notion toggles), including toggles nested inside them."""
        for _ in range(rounds):
            closed = page.locator("[role=button][aria-expanded=false]").all()
            if not closed:
                return
            for toggle in closed[:50]:
                try:
                    toggle.click(timeout=1_000)
                except Exception:
                    pass  # hidden or detached; the next round retries
            page.wait_for_timeout(1_500)

    @staticmethod
    def _vanta(page, max_pages: int = 30) -> str:
        from html import escape
        rows = []
        for _ in range(max_pages):
            page.wait_for_timeout(800)
            rows += page.evaluate(_VANTA_ROWS_JS)
            nxt = page.get_by_role("button", name="Next")
            if nxt.count() == 0 or not nxt.first.is_enabled():
                break
            nxt.first.click()
        body = "".join("<tr>" + "".join(f"<td>{escape(c.strip())}</td>" for c in r) + "</tr>" for r in rows)
        return f"<html><body><h2>Subprocessors</h2><table>{body}</table></body></html>"

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()
