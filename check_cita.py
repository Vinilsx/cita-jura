import argparse
import asyncio
import csv
import json
import os
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from playwright.async_api import Browser, Error as PlaywrightError, Page, TimeoutError, async_playwright


BASE_URL = "https://www.juntadeandalucia.es/justicia/citaprevia/?idCliente=4"
TIMEZONE = ZoneInfo("Europe/Madrid")
TOTAL_TIMEOUT_SECONDS = 120
MAX_MONTHS_TO_CHECK = 6

DATA_DIR = Path("data")
SCREENSHOTS_DIR = Path("screenshots")
DEBUG_HTML_DIR = Path("debug/html")
DEBUG_SCREENSHOTS_DIR = Path("debug/screenshots")
DEBUG_ELEMENTS_PATH = Path("debug/elements.json")
RESULTS_CSV = DATA_DIR / "results.csv"

CSV_FIELDS = [
    "timestamp",
    "run_id",
    "status",
    "message",
    "url",
    "visible_months_checked",
    "available_dates",
    "screenshot",
]

STATUS_NO_CITA = "no_cita"
STATUS_POSSIBLE_CITA = "possible_cita"
STATUS_CAPTCHA = "captcha_or_blocked"
STATUS_SITE_ERROR = "site_error"
STATUS_SCRIPT_ERROR = "script_error"
STATUS_UNKNOWN = "unknown"

CAPTCHA_PATTERNS = [
    re.compile(r"captcha", re.I),
    re.compile(r"no soy un robot", re.I),
    re.compile(r"robot", re.I),
    re.compile(r"verificaci[oó]n", re.I),
    re.compile(r"verificacion", re.I),
]

JURA_PATTERNS = [
    re.compile(r"jura|juramento|promesa", re.I),
    re.compile(r"nacionalidad", re.I),
]

SEVILLA_OFFICE_PATTERNS = [
    re.compile(r"registro civil exclusivo", re.I),
    re.compile(r"sevilla", re.I),
]

MONTH_PATTERN = re.compile(
    r"\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+\d{4}\b",
    re.I,
)

SPANISH_MONTHS = {
    "ene": "Enero",
    "feb": "Febrero",
    "mar": "Marzo",
    "abr": "Abril",
    "may": "Mayo",
    "jun": "Junio",
    "jul": "Julio",
    "ago": "Agosto",
    "sep": "Septiembre",
    "oct": "Octubre",
    "nov": "Noviembre",
    "dic": "Diciembre",
}

UNAVAILABLE_PATTERNS = [
    re.compile(r"no hay citas", re.I),
    re.compile(r"sin citas", re.I),
    re.compile(r"no existen citas", re.I),
    re.compile(r"no quedan citas", re.I),
    re.compile(r"no hay huecos libres", re.I),
]


@dataclass
class CheckResult:
    status: str
    message: str
    url: str
    visible_months_checked: list[str] = field(default_factory=list)
    available_dates: list[str] = field(default_factory=list)
    screenshot: str = ""


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def now_madrid() -> datetime:
    return datetime.now(TIMEZONE)


def make_run_id(timestamp: datetime) -> str:
    return timestamp.strftime("%Y%m%d-%H%M%S")


def ensure_directories() -> None:
    for path in [DATA_DIR, SCREENSHOTS_DIR, DEBUG_HTML_DIR, DEBUG_SCREENSHOTS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def csv_cell(value: str) -> str:
    return " ".join(value.split())


def append_csv(timestamp: datetime, run_id: str, result: CheckResult) -> None:
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not RESULTS_CSV.exists() or RESULTS_CSV.stat().st_size == 0
    with RESULTS_CSV.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": timestamp.isoformat(timespec="seconds"),
                "run_id": run_id,
                "status": result.status,
                "message": csv_cell(result.message),
                "url": result.url,
                "visible_months_checked": "|".join(result.visible_months_checked),
                "available_dates": "|".join(result.available_dates),
                "screenshot": result.screenshot,
            }
        )


async def random_delay() -> None:
    await asyncio.sleep(random.uniform(1, 3))


async def screenshot(page: Page, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(path), full_page=True)
    return str(path).replace("\\", "/")


async def visible_text(page: Page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=5000)
    except PlaywrightError:
        return ""


def has_captcha(text: str) -> bool:
    return any(pattern.search(text) for pattern in CAPTCHA_PATTERNS)


def find_visible_months(text: str) -> list[str]:
    months: list[str] = []
    for match in MONTH_PATTERN.finditer(text):
        month = match.group(0)
        normalized = month[:1].upper() + month[1:].lower()
        if normalized not in months:
            months.append(normalized)
    return months


def text_says_unavailable(text: str) -> bool:
    return any(pattern.search(text) for pattern in UNAVAILABLE_PATTERNS)


async def calendar_is_visible(page: Page) -> bool:
    try:
        return await page.locator("#datepicker, .ui-datepicker-calendar").first.is_visible(timeout=500)
    except PlaywrightError:
        return False


async def current_calendar_month(page: Page) -> str:
    try:
        month_raw = await page.locator("#cal_select_month option:checked").inner_text(timeout=500)
        year = await page.locator("#cal_select_year option:checked").inner_text(timeout=500)
    except PlaywrightError:
        return ""
    month = SPANISH_MONTHS.get(month_raw.strip().lower()[:3], month_raw.strip())
    return f"{month} {year.strip()}".strip()


async def collect_elements(page: Page) -> list[dict[str, str]]:
    return await page.evaluate(
        """
        () => Array.from(document.querySelectorAll('button,a,select,input,textarea')).map((el) => ({
          tag: el.tagName.toLowerCase(),
          text: (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim(),
          type: el.getAttribute('type') || '',
          name: el.getAttribute('name') || '',
          id: el.id || '',
          href: el.getAttribute('href') || '',
          disabled: String(el.disabled || el.getAttribute('aria-disabled') === 'true'),
          visible: String(!!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)),
        }))
        """
    )


async def save_discovery_step(page: Page, run_id: str, step: int, label: str, elements: list[dict]) -> None:
    safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "-", label).strip("-").lower() or "step"
    prefix = f"{run_id}-{step:02d}-{safe_label}"
    await screenshot(page, DEBUG_SCREENSHOTS_DIR / f"{prefix}.png")
    html = await page.content()
    (DEBUG_HTML_DIR / f"{prefix}.html").write_text(html, encoding="utf-8")
    elements.append(
        {
            "step": step,
            "label": label,
            "url": page.url,
            "visible_text": (await visible_text(page))[:8000],
            "elements": await collect_elements(page),
        }
    )


async def click_first_matching(page: Page, patterns: Iterable[re.Pattern], timeout_ms: int = 2500) -> bool:
    elements = page.locator("button,a,input[type=button],input[type=submit]")
    count = await elements.count()
    for index in range(count):
        element = elements.nth(index)
        try:
            if not await element.is_visible(timeout=500):
                continue
        except Exception:
            continue

        label = ""
        try:
            label = (await element.inner_text(timeout=500)).strip()
        except Exception:
            pass
        try:
            label = label or (await element.get_attribute("value", timeout=500) or "").strip()
        except Exception:
            pass
        try:
            label = label or (await element.get_attribute("aria-label", timeout=500) or "").strip()
        except Exception:
            pass
        if any(pattern.search(label) for pattern in patterns):
            await random_delay()
            await element.click(timeout=timeout_ms)
            await page.wait_for_load_state("networkidle", timeout=10000)
            return True
    return False


async def select_jura_options(page: Page) -> bool:
    changed = False
    selects = page.locator("select")
    count = await selects.count()
    for index in range(count):
        select = selects.nth(index)
        try:
            if not await select.is_visible(timeout=300) or not await select.is_enabled(timeout=300):
                continue
            options = await select.locator("option").evaluate_all(
                """
                options => options.map((option) => ({
                  value: option.value,
                  text: option.textContent || ''
                }))
                """
            )
        except PlaywrightError:
            continue

        for option in options:
            text = option["text"]
            if all(pattern.search(text) for pattern in JURA_PATTERNS):
                try:
                    current = await select.input_value(timeout=500)
                    if current == option["value"]:
                        break
                    await random_delay()
                    await select.select_option(value=option["value"])
                    changed = True
                except PlaywrightError:
                    pass
                break
    if changed:
        await page.wait_for_load_state("networkidle", timeout=10000)
    return changed


async def select_option_matching(page: Page, select_selector: str, patterns: Iterable[re.Pattern]) -> bool:
    select = page.locator(select_selector).first
    try:
        await select.wait_for(state="attached", timeout=5000)
        options = await select.locator("option").evaluate_all(
            """
            options => options.map((option) => ({
              value: option.value,
              text: option.textContent || ''
            }))
            """
        )
    except PlaywrightError:
        return False

    for option in options:
        text = option["text"]
        if all(pattern.search(text) for pattern in patterns):
            await random_delay()
            await select.select_option(value=option["value"])
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightError:
                pass
            await asyncio.sleep(2)
            return True
    return False


async def advance_month(page: Page) -> bool:
    next_button = page.locator("#cal_next_month, .ui-datepicker-next").first
    try:
        if not await next_button.is_visible(timeout=500):
            return False
        disabled = await next_button.get_attribute("class", timeout=500) or ""
        if "disabled" in disabled:
            return False
        await random_delay()
        await next_button.click(timeout=2500)
        await page.wait_for_load_state("networkidle", timeout=10000)
        await asyncio.sleep(1)
        return True
    except PlaywrightError:
        return False


async def available_calendar_dates(page: Page) -> list[str]:
    jquery_dates = await page.evaluate(
        """
        () => {
          const monthSelect = document.querySelector('#cal_select_month');
          const yearSelect = document.querySelector('#cal_select_year');
          if (!monthSelect || !yearSelect) return [];
          const month = Number(monthSelect.value) + 1;
          const year = Number(yearSelect.value);
          return Array.from(document.querySelectorAll(
            '.ui-datepicker-calendar td:not(.ui-datepicker-unselectable):not(.ui-state-disabled) a'
          )).map((day) => {
            const value = Number((day.textContent || '').trim());
            if (!value) return '';
            return `${year}-${String(month).padStart(2, '0')}-${String(value).padStart(2, '0')}`;
          }).filter(Boolean);
        }
        """
    )
    if jquery_dates:
        return list(dict.fromkeys(jquery_dates))

    selectors = [
        "td a",
        "td button",
        "[role=gridcell] a",
        "[role=gridcell] button",
        ".ui-datepicker-calendar a",
    ]
    dates: list[str] = []
    for selector in selectors:
        loc = page.locator(selector)
        count = await loc.count()
        for index in range(count):
            item = loc.nth(index)
            try:
                if not await item.is_visible(timeout=300):
                    continue
                label = (await item.inner_text(timeout=300)).strip()
                aria = (await item.get_attribute("aria-label", timeout=300)) or ""
                title = (await item.get_attribute("title", timeout=300)) or ""
                candidate = " ".join(part for part in [label, aria, title] if part).strip()
                if candidate and candidate not in dates:
                    dates.append(candidate)
            except PlaywrightError:
                continue
    return dates


async def navigate_toward_jura(page: Page, discovery: bool, run_id: str) -> tuple[str, list[dict]]:
    elements: list[dict] = []
    await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
    if discovery:
        await save_discovery_step(page, run_id, 1, "initial", elements)

    text = await visible_text(page)
    if has_captcha(text):
        return STATUS_CAPTCHA, elements

    await select_option_matching(page, "#comboOficinas", SEVILLA_OFFICE_PATTERNS)
    if discovery:
        await save_discovery_step(page, run_id, 2, "after-office", elements)

    await select_jura_options(page)
    if discovery:
        await save_discovery_step(page, run_id, 3, "after-jura-selects", elements)

    action_patterns = [
        re.compile(r"aceptar|continuar|siguiente|solicitar|iniciar|pedir|nueva cita", re.I),
    ]
    for step in range(4, 8):
        text = await visible_text(page)
        if has_captcha(text):
            return STATUS_CAPTCHA, elements
        if await calendar_is_visible(page) or "calend" in text.lower() or find_visible_months(text):
            break
        changed = await select_jura_options(page)
        clicked = await click_first_matching(page, action_patterns)
        if discovery:
            await save_discovery_step(page, run_id, step, f"navigation-{step}", elements)
        if not changed and not clicked:
            break

    return STATUS_UNKNOWN, elements


async def run_discovery(page: Page, run_id: str) -> CheckResult:
    status, elements = await navigate_toward_jura(page, True, run_id)
    text = await visible_text(page)
    if has_captcha(text):
        status = STATUS_CAPTCHA
    DEBUG_ELEMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_ELEMENTS_PATH.write_text(json.dumps(elements, ensure_ascii=False, indent=2), encoding="utf-8")
    return CheckResult(
        status=status if status == STATUS_CAPTCHA else STATUS_UNKNOWN,
        message="Discovery concluido; veja debug/html, debug/screenshots e debug/elements.json",
        url=page.url,
        visible_months_checked=find_visible_months(text),
        screenshot=str(DEBUG_SCREENSHOTS_DIR).replace("\\", "/"),
    )


async def run_check(page: Page, run_id: str, save_all_screenshots: bool) -> CheckResult:
    status, _ = await navigate_toward_jura(page, False, run_id)
    text = await visible_text(page)
    if status == STATUS_CAPTCHA or has_captcha(text):
        path = await screenshot(page, SCREENSHOTS_DIR / f"{run_id}.png")
        return CheckResult(STATUS_CAPTCHA, "Captcha ou bloqueio detectado", page.url, screenshot=path)

    months_checked: list[str] = []
    for _ in range(MAX_MONTHS_TO_CHECK):
        text = await visible_text(page)
        if has_captcha(text):
            path = await screenshot(page, SCREENSHOTS_DIR / f"{run_id}.png")
            return CheckResult(STATUS_CAPTCHA, "Captcha ou bloqueio detectado", page.url, months_checked, screenshot=path)

        for month in find_visible_months(text):
            if month not in months_checked:
                months_checked.append(month)
        calendar_month = await current_calendar_month(page)
        if calendar_month and calendar_month not in months_checked:
            months_checked.append(calendar_month)

        dates = await available_calendar_dates(page)
        if dates:
            path = await screenshot(page, SCREENSHOTS_DIR / f"{run_id}.png")
            return CheckResult(
                STATUS_POSSIBLE_CITA,
                "Datas clicaveis encontradas",
                page.url,
                months_checked,
                dates,
                path,
            )

        if text_says_unavailable(text) and not months_checked:
            break
        if not await advance_month(page):
            break

    screenshot_path = ""
    if save_all_screenshots:
        screenshot_path = await screenshot(page, SCREENSHOTS_DIR / f"{run_id}.png")
    return CheckResult(
        STATUS_NO_CITA,
        "No hay citas disponibles",
        page.url,
        months_checked,
        [],
        screenshot_path,
    )


async def run_with_browser(discovery: bool, headful: bool, run_id: str, save_all_screenshots: bool) -> CheckResult:
    async with async_playwright() as playwright:
        browser: Browser = await playwright.chromium.launch(headless=not headful)
        context = await browser.new_context(
            locale="es-ES",
            timezone_id="Europe/Madrid",
            viewport={"width": 1365, "height": 900},
        )
        page = await context.new_page()
        page.set_default_timeout(10000)
        try:
            try:
                if discovery:
                    return await run_discovery(page, run_id)
                return await run_check(page, run_id, save_all_screenshots)
            except TimeoutError as exc:
                path = await screenshot(page, SCREENSHOTS_DIR / f"{run_id}.png")
                return CheckResult(STATUS_SITE_ERROR, f"Timeout do site: {exc}", page.url or BASE_URL, screenshot=path)
            except PlaywrightError as exc:
                path = await screenshot(page, SCREENSHOTS_DIR / f"{run_id}.png")
                return CheckResult(STATUS_SITE_ERROR, f"Erro do site/browser: {exc}", page.url or BASE_URL, screenshot=path)
        finally:
            await context.close()
            await browser.close()


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Monitor de cita para Jura de Nacionalidad em Sevilla.")
    parser.add_argument("--discovery", action="store_true", help="Salva HTML, screenshots e elementos para mapear o portal.")
    parser.add_argument("--headful", action="store_true", help="Executa Chromium com janela visivel.")
    args = parser.parse_args()

    load_dotenv()
    ensure_directories()

    timestamp = now_madrid()
    run_id = make_run_id(timestamp)
    save_all_screenshots = env_flag("SAVE_ALL_SCREENSHOTS", False)

    try:
        result = await asyncio.wait_for(
            run_with_browser(args.discovery, args.headful, run_id, save_all_screenshots),
            timeout=TOTAL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        result = CheckResult(STATUS_SITE_ERROR, "Timeout total de 2 minutos excedido", BASE_URL)
    except Exception as exc:
        result = CheckResult(STATUS_SCRIPT_ERROR, f"Erro no script: {type(exc).__name__}: {exc}", BASE_URL)

    if result.status in {STATUS_SITE_ERROR, STATUS_UNKNOWN, STATUS_SCRIPT_ERROR} and not result.screenshot:
        result.screenshot = ""

    append_csv(timestamp, run_id, result)

    print(f"Run ID: {run_id}")
    print(f"Status: {result.status}")
    print(f"Message: {result.message}")
    print(f"CSV updated: {RESULTS_CSV}")
    if result.screenshot:
        print(f"Screenshot: {result.screenshot}")
    return 0 if result.status in {STATUS_NO_CITA, STATUS_POSSIBLE_CITA, STATUS_CAPTCHA, STATUS_UNKNOWN} else 1


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
