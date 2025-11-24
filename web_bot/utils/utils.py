from selenium.webdriver.common.by import By
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException

# универсальный JS-сканер: собирает элементы по селекторам,
# проходя по документу, открытым shadowRoot и доступным iframe
_JS_SCAN_SELECTORS = r"""
const sels = arguments[0] || [];
const result = [];

// рекурсивный сбор для документа/фрагмента
function collectInRoot(root) {
  for (const sel of sels) {
    try {
      const nodes = root.querySelectorAll(sel);
      for (const n of nodes) result.push(n);
    } catch (e) {}
  }
  // пройти по открытым shadow DOM
  const all = root.querySelectorAll('*');
  for (const el of all) {
    if (el.shadowRoot) {
      collectInRoot(el.shadowRoot);
    }
  }
}

// основной документ
collectInRoot(document);

// доступные (same-origin) iframe
const frames = document.querySelectorAll('iframe, frame');
for (const fr of frames) {
  try {
    const doc = fr.contentDocument;
    if (doc) collectInRoot(doc);
  } catch (e) {
    // cross-origin — пропускаем
  }
}

return result;
"""

def _safe_attr(el, name, default=None):
    try:
        return el.get_attribute(name)
    except (StaleElementReferenceException, WebDriverException):
        return default

def _safe_tag(el, default=""):
    try:
        return el.tag_name
    except (StaleElementReferenceException, WebDriverException):
        return default

def _safe_displayed(el):
    try:
        return el.is_displayed()
    except (StaleElementReferenceException, WebDriverException):
        return False

def _safe_enabled(el):
    try:
        return el.is_enabled()
    except (StaleElementReferenceException, WebDriverException):
        # для некоторых элементов (например, <a>) Selenium всегда True
        return True

def _scan_selectors(driver, selectors):
    """Вернёт уникальные WebElement по списку CSS-селекторов с учётом shadow DOM и iframe."""
    try:
        elements = driver.execute_script(_JS_SCAN_SELECTORS, selectors)
    except WebDriverException:
        elements = []
    # дедупликация по внутреннему id элемента Selenium
    uniq, seen = [], set()
    for el in elements:
        try:
            key = getattr(el, "id", None)
        except Exception:
            key = None
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        uniq.append(el)
    return uniq


def get_inputs(driver):
    """
    вывести все инпуты и их атрибуты
    (теперь ищет и внутри открытых shadow DOM и доступных iframe)
    """
    elements = _scan_selectors(driver, ['input'])
    #print(f"\nНайдено {len(elements)} input'ов")

    inputs_list = []
    for inp in elements:
        # если элемент «устарел», просто пропускаем
        tag = _safe_tag(inp, default="input")
        if tag.lower() != "input":
            # пропустим если что-то пошло не так
            continue

        formatted_input = {
            "tag": tag,
            "type": _safe_attr(inp, "type"),
            "name": _safe_attr(inp, "name"),
            "id": _safe_attr(inp, "id"),
            "placeholder": _safe_attr(inp, "placeholder"),
            "displayed": _safe_displayed(inp),
            "enabled": _safe_enabled(inp),
        }
        inputs_list.append(formatted_input)

    return inputs_list


def get_buttons(driver):
    """
    Найти кнопки шире, чем .btn:
    - <button>
    - <input type=submit|button|image|reset>
    - [role=button]
    - элементы с «кнопочными» классами популярных UI-библиотек
    Также ищет в shadow DOM и доступных iframe.
    """
    button_like_selectors = [
        'button',
        'input[type="button"]',
        'input[type="submit"]',
        'input[type="image"]',
        'input[type="reset"]',
        '[role="button"]',
        # популярные классы (фреймворки)
        '.btn', '[class*="btn"]', '[class*="button"]',
        '.mdc-button',
        '.mat-button', '.mat-raised-button', '.mat-mdc-button', '.mat-mdc-raised-button',
        '.ant-btn',
        '.MuiButton-root',
        '.chakra-button',
        '.v-btn',
        '.uk-button',
        '.btn-primary', '.btn-secondary', '.btn-success', '.btn-danger', '.btn-warning',
    ]

    elements = _scan_selectors(driver, button_like_selectors)
    #print(f"Найдено {len(elements)} кнопок/псевдокнопок")

    button_list = []
    for btn in elements:
        formatted_input = {
            "tag": _safe_tag(btn, default=""),
            "type": _safe_attr(btn, "type"),
            "name": _safe_attr(btn, "name"),
            "id": _safe_attr(btn, "id"),
            "placeholder": _safe_attr(btn, "placeholder"),
            "displayed": _safe_displayed(btn),
            "enabled": _safe_enabled(btn),
        }
        button_list.append(formatted_input)

    return button_list

# Общий JS-сканер DOM (капча + куки)
_JS_SCAN = r"""
return (function () {
  function isVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    const r = el.getBoundingClientRect();
    if ((r.width || 0) === 0 || (r.height || 0) === 0) return false;
    return true;
  }
  function anyVisible(selectors) {
    for (const sel of selectors) {
      let nodes = [];
      try { nodes = document.querySelectorAll(sel); } catch (e) {}
      for (const n of nodes) {
        if (isVisible(n)) return true;
      }
    }
    return false;
  }
  function anyPresent(selectors) {
    for (const sel of selectors) {
      try { if (document.querySelector(sel)) return true; } catch (e) {}
    }
    return false;
  }

  // --- CAPTCHA: reCAPTCHA / hCaptcha / Cloudflare Turnstile ---
  // 1) Turnstile может быть видимым iframe ИЛИ скрытым input с ответом
  const turnstilePresence = anyPresent([
    'input[name="cf-turnstile-response"]',
    'input[id*="cf-chl-widget"][id$="_response"]',
    'div.cf-turnstile',
    'div[id^="cf-chl-widget"]',
    'iframe[src*="challenges.cloudflare.com"]',
    'iframe[src*="turnstile"]',
    'iframe[title*="Cloudflare"]'
  ]);
  if (turnstilePresence) {
    return { captcha: true, cookie: false };
  }

  const captchaSelectors = [
    // reCAPTCHA
    'iframe[src*="google.com/recaptcha"]',
    'iframe[src*="recaptcha"]',
    'iframe[title*="reCAPTCHA"]',
    '.g-recaptcha',
    'div[id^="rc-anchor-container"]',
    // hCaptcha
    'iframe[src*="hcaptcha.com"]',
    '.h-captcha',
    // Cloudflare challenge (дополнительно к presence выше)
    'div.cf-challenge',
    'div[id^="cf-challenge"]'
  ];
  if (anyVisible(captchaSelectors)) {
    return { captcha: true, cookie: false };
  }

  // Текстовые индикаторы (если текст не в iframe)
  const captchaTextRe = /(i'?m not a robot|i am human|verify you are human|select all images|click each image|checking your browser|please stand by|подтвердите, что вы не робот|я не робот|выберите все изображения|подтвердите человечность|пройдите проверку|проверка браузера)/i;
  const textTags = ['label','div','span','p','button','h1','h2','h3'];
  for (const tag of textTags) {
    const els = document.getElementsByTagName(tag);
    for (const el of els) {
      if (!isVisible(el)) continue;
      const t = (el.textContent || '').trim();
      if (t && captchaTextRe.test(t)) {
        return { captcha: true, cookie: false };
      }
    }
  }

  // --- COOKIE banners ---
  const cookieSelectors = [
    '#onetrust-banner-sdk', '#onetrust-consent-sdk', 'button#onetrust-accept-btn-handler',
    '#CybotCookiebotDialog',
    '#cookie-law-info-bar', '.cky-consent-container',
    '#qc-cmp2-container',
    '#truste-consent',
    '.didomi-popup',
    '[id^="sp_message_container"]',
    '[id*="cookie"]','[class*="cookie"]',
    '[id*="consent"]','[class*="consent"]',
    '[id*="gdpr"]','[class*="gdpr"]',
    '[id*="cmp"]','[class*="cmp"]'
  ];
  if (anyVisible(cookieSelectors)) {
    return { captcha: false, cookie: true };
  }

  const cookieTextRe = /(cookies?|cookie settings|accept( all)?|agree|allow|we use cookies|manage preferences|используем.*cookie|файлы cookie|принять|принять все|соглас(ен|ие)|разрешить)/i;
  const clickable = document.querySelectorAll('button, a, [role="button"]');
  for (const b of clickable) {
    if (!isVisible(b)) continue;
    const t = (b.textContent || '').trim();
    if (t && cookieTextRe.test(t)) {
      let el = b;
      for (let i = 0; i < 5 && el; i++) {
        const blob = ((el.textContent || '') + ' ' + (el.className || '') + ' ' + (el.id || ''));
        if (/(cookie|consent|gdpr|cmp)/i.test(blob) && isVisible(el)) {
          return { captcha: false, cookie: true };
        }
        el = el.parentElement;
      }
    }
  }

  return { captcha: false, cookie: false };
})();
"""

def _scan(driver) -> dict:
    """Выполнить быстрый JS-скан дом-дерева и вернуть флаги {'captcha': bool, 'cookie': bool}."""
    try:
        res = driver.execute_script(_JS_SCAN)
        if not isinstance(res, dict):
            return {'captcha': False, 'cookie': False}
        return {'captcha': bool(res.get('captcha')), 'cookie': bool(res.get('cookie'))}
    except Exception:
        # Ничего не нашли/нет доступа — считаем, что блокеров нет
        return {'captcha': False, 'cookie': False}

def has_captcha(driver) -> bool:
    """True, если на странице виден капча-челлендж (reCAPTCHA, hCaptcha, Cloudflare и т.п.)."""
    return _scan(driver)['captcha']

def has_cookie_banner(driver) -> bool:
    """True, если на странице виден баннер согласия с cookies (CMP/ GDPR-диалог)."""
    return _scan(driver)['cookie']
