import threading, queue, traceback, time
from dataclasses import dataclass
from typing import Any, Callable, Optional
import asyncio

# --- selenium импорты ---
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException


from web_bot.utils.utils import get_inputs, get_buttons, has_captcha, has_cookie_banner
from web_bot.utils.actions import input_login, input_password, press_button

import os
from dotenv import load_dotenv
load_dotenv()

WEBDRIVER_URL = os.getenv("WEBDRIVER_URL", "http://localhost:4444")

NO_SLOTS_PHRASES = [
    "no appointment slots are currently available",
    "no appointment slots",
    "no appointments available",
    "no appointment slots available",
    "slots are currently unavailable",
]

@dataclass
class Command:
    name: str
    args: tuple
    kwargs: dict
    future: asyncio.Future  # future из event loop'а async-части

class BotThread:
    def __init__(self, loop: asyncio.AbstractEventLoop,
                 notify: Optional[Callable[[dict], None]] = None,
                 resume_evt: Optional[threading.Event] = None):
        self._loop = loop                      # event loop async-части
        self._q: "queue.Queue[Command]" = queue.Queue()
        self._stop_evt = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._driver: Optional[webdriver.Remote] = None

        # куда отправлять статусы и где хранить события-паузы (задаем в controller)
        self._notify = notify or (lambda e: None) #функция уведомлений
        self._resume_evt = resume_evt or threading.Event()  # NEW

        # обработчики команд
        self._handlers: dict[str, Callable[..., Any]] = {
            "test_vfs": self._handle_test_vfs
        }

    # ---- публичные методы ----
    def start(self):
        self._thread.start()

    def stop(self, timeout: float = 5.0):
        self._stop_evt.set()
        self._q.put(None)  # разморозить get()
        self._thread.join(timeout=timeout)

    def submit(self, name: str, *args, **kwargs) -> asyncio.Future:
        """
        Вызывается из async-кода: кладёт команду и возвращает Future,
        которое можно await-ить, чтобы получить результат/ошибку.
        """
        fut = self._loop.create_future()
        cmd = Command(name=name, args=args, kwargs=kwargs, future=fut)
        self._q.put(cmd)
        return fut

    # ---- внутренняя жизнь потока ----
    def _run(self):
        try:
            self._setup_bot()
            while not self._stop_evt.is_set():
                cmd = self._q.get()
                if cmd is None:  # сигнал остановки
                    break
                self._dispatch(cmd)
        finally:
            self._teardown_bot()

    def _setup_bot(self):
        """Создаём один Remote WebDriver в этом потоке и переиспользуем между задачами."""
        opts = Options()
        opts.add_argument("--disable-blink-features=AutomationControlled")

        self._driver = webdriver.Remote(
            command_executor=WEBDRIVER_URL,
            options=opts,
        )

    def _pause_for_admin(self, kind: str, message: str):
        """Блокирует поток до тех пор, пока контроллер не снимет паузу через /continue)."""
        # чтобы более ранний /continue не считался
        self._resume_evt.clear()

        # отправим уведомление админу
        url = ""
        try:
            if self._driver:
                url = self._driver.current_url
        except Exception:
            pass
        self._notify({"type": kind, "message": message, "url": url})

        # ждём снятия паузы
        self._resume_evt.wait()

    def _teardown_bot(self):
        try:
            if self._driver:
                self._driver.quit()
                pass
        except Exception:
            traceback.print_exc()

    def _dispatch(self, cmd: Command):
        try:
            handler = self._handlers[cmd.name]
            result = handler(*cmd.args, **cmd.kwargs)
        except Exception as e:
            # результат в event loop'е async-части:
            self._loop.call_soon_threadsafe(cmd.future.set_exception, e)
        else:
            self._loop.call_soon_threadsafe(cmd.future.set_result, result)

    # ---- обработчики команд ----
    @staticmethod        
    def _click_if_visible(driver, by, selector, timeout=5):
        try:
            el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, selector)))
            if el.is_displayed() and el.is_enabled():
                el.click()
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _closest_form(driver, element):
        # вернуть ближайший родитель form через JS
        try:
            return driver.execute_script("return arguments[0].closest('form')", element)
        except Exception:
            return None

    @staticmethod
    def _first_visible_enabled(container, by, selector):
        els = container.find_elements(by, selector) if container else []
        for el in els:
            try:
                if el.is_displayed() and el.is_enabled():
                    return el
            except Exception:
                continue
        return None

    @staticmethod
    def _wait_enabled_clickable(driver, element, timeout=10):
        WebDriverWait(driver, timeout).until(lambda d: element.is_displayed() and element.is_enabled())
        # дополнительно ждём исчезновения атрибута disabled, если он есть
        WebDriverWait(driver, timeout).until(lambda d: element.get_attribute("disabled") in (None, "", "false"))

    @staticmethod
    def _fill_visible(el, text):
        el.clear()
        el.send_keys(text)
    
    def _wait_spinners_gone(self, timeout=20):
        """Ждём, пока пропадут оверлеи/спиннеры, которые блокируют клики."""
        d = self._driver
        end = time.time() + timeout
        selectors = [
            ".sk-ball-spin-clockwise",          # то, что перехватывает клик
            ".ngx-spinner-overlay",
            ".block-ui-wrapper.active",
            ".mat-mdc-progress-bar",
            ".mat-mdc-progress-spinner",
            "div[role='progressbar']",
        ]
        while time.time() < end:
            visible = False
            for sel in selectors:
                for el in d.find_elements(By.CSS_SELECTOR, sel):
                    try:
                        if el.is_displayed():
                            visible = True
                            break
                    except Exception:
                        pass
                if visible:
                    break
            if not visible:
                return
            time.sleep(0.2)
        # не падаем с исключением — просто выходим и дадим _safe_click ещё раз попробовать

    def _safe_click(self, el, timeout=10):
        d = self._driver
        self._scroll_into_view(d, el)
        self._wait_spinners_gone(timeout=timeout)
        self._wait_enabled_clickable(d, el, timeout)
        try:
            el.click()
        except ElementClickInterceptedException:
            # если всё ещё перекрыто — пробуем позже и JS-клик
            self._wait_spinners_gone(timeout=timeout)
            try:
                d.execute_script("arguments[0].click();", el)
            except Exception:
                raise

    @staticmethod
    def _scroll_into_view(driver, el):
        """Аккуратно прокрутить к элементу; JS → fallback через ActionChains."""
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        except Exception:
            try:
                ActionChains(driver).move_to_element(el).perform()
            except Exception:
                pass

    def _find_mat_select_by_placeholder_contains(self, contains_text: str, timeout=15):
        d = self._driver
        wait = WebDriverWait(d, timeout)
        ci = contains_text.strip().lower()
        # ищем mat-select, внутри которого виден плейсхолдер с нужным текстом
        xpath = (
            "//mat-select[.//span[contains(@class,'mat-mdc-select-placeholder')]["
            "contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
            f"'{ci}')]]"
        )
        return wait.until(EC.presence_of_element_located((By.XPATH, xpath)))

    def _open_mat_select(self, mat_select_el, timeout=10):
        d = self._driver
        if mat_select_el.get_attribute("aria-expanded") == "true":
            return
        trigger = mat_select_el.find_element(By.CSS_SELECTOR, ".mat-mdc-select-trigger")
        self._safe_click(trigger, timeout=timeout)
        WebDriverWait(d, timeout).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "div.cdk-overlay-pane div.mat-mdc-select-panel")
            )
        )

    def _choose_mat_option_by_text(self, text_contains: str, timeout=10):
        d = self._driver
        wait = WebDriverWait(d, timeout)
        ci = (text_contains or "").strip().lower()

        # панель Angular Material
        panel_xpath = (
            "//div[contains(@class,'cdk-overlay-pane')]"
            "//div[contains(@class,'mat-mdc-select-panel') or contains(@class,'mat-select-panel')]"
        )
        # любой mat-option, внутри которого текст содержит подстроку
        opt_xpath = (
            f"{panel_xpath}//mat-option[.//span["
            "contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
            f"'{ci}')]]"
        )

        # ждём появления панели и нужной опции
        wait.until(EC.presence_of_element_located((By.XPATH, panel_xpath)))
        opt = wait.until(EC.presence_of_element_located((By.XPATH, opt_xpath)))

        # скроллим и кликаем безопасно
        self._safe_click(opt, timeout=timeout)

        # ждём закрытия панели
        wait.until(EC.invisibility_of_element_located(
            (By.XPATH, panel_xpath)
        ))

    def _select_in_mat_by(self, *, formcontrol: str | None = None,
                          placeholder_contains: str | None = None,
                          option_text_contains: str, timeout=20):
        d = self._driver
        wait = WebDriverWait(d, timeout)
        if formcontrol:
            mat = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, f"mat-select[formcontrolname='{formcontrol}']")))
        else:
            mat = self._find_mat_select_by_placeholder_contains(placeholder_contains, timeout=timeout)

        # ждём, пока селект не будет disabled (после автозаполнений)
        wait.until(lambda _ : mat.get_attribute("aria-disabled") == "false")
        self._open_mat_select(mat, timeout=timeout)
        self._choose_mat_option_by_text(option_text_contains, timeout=timeout)

    def _fill_appointment_details(self, *, city: str, subcategory: str = "SEAMEN"):
        if not city:
            raise ValueError("Нужен form_data['city'] — название города")

        # верхняя выпадашка с городом
        self._select_in_mat_by(
            formcontrol="centerCode",
            option_text_contains=city
        )

        # дождаться, пока страница обработает выбор
        self._wait_spinners_gone(timeout=20)

        # нижняя выпадашка с категорией
        self._select_in_mat_by(
            placeholder_contains="sub-category",
            option_text_contains=subcategory
        )

    def _match_no_slots(self, txt: str) -> bool:
        t = (txt or "").strip().lower()
        return any(p in t for p in NO_SLOTS_PHRASES)

    def _has_no_slots_alert(self) -> bool:
        """
        True, если на странице есть информация об отсутствии окон для записи
        """
        d = self._driver
        if not d:
            return False

        def check_current_context() -> bool:
            # 1) подождём рендер (иногда alert грузится ajax'ом)
            try:
                WebDriverWait(d, 3).until(
                    lambda x: x.execute_script("return document.readyState") == "complete"
                )
            except Exception:
                pass

            # 2) сначала попробуем типичные alert-контейнеры
            try:
                candidates = d.find_elements(
                    By.CSS_SELECTOR,
                    "div[role='alert'], .alert, .alert-info, .alert-info-blue"
                )
            except Exception:
                candidates = []

            for el in candidates:
                # a) Selenium .text
                if self._match_no_slots(el.text):
                    return True
                # b) textContent (часто спасает)
                try:
                    if self._match_no_slots(el.get_attribute("textContent")):
                        return True
                except Exception:
                    pass

            # 3) глобальный поиск по всему DOM
            try:
                nodes = d.find_elements(
                    By.XPATH,
                    "//*[contains(translate(normalize-space(string(.)),"
                    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
                    "'no appointment slots')]"
                )
                if nodes:
                    return True
            except Exception:
                pass

            return False

        try:
            # Текущий документ
            if check_current_context():
                return True

            # Проверим все iframe
            frames = d.find_elements(By.CSS_SELECTOR, "iframe")
            for fr in frames:
                try:
                    d.switch_to.frame(fr)
                    if check_current_context():
                        return True
                finally:
                    d.switch_to.parent_frame()
        except Exception:
            pass

        return False

    def _handle_test_vfs(self, *, form_data: dict = {'email': '123', 'password': '123', 'city': 'Moscow'}):
        if self._driver is None:
            raise RuntimeError("WebDriver not initialized")

        def check_cancel():
            if self._stop_evt.is_set():
                raise RuntimeError("Job cancelled")

        driver = self._driver
        wait = WebDriverWait(driver, 30)

        email_or_username = form_data.get("email") or form_data.get("username") or form_data.get("login") or ""
        password = form_data.get("password") or ""

        try:
            LOGIN_URL = "https://visa.vfsglobal.com/rus/en/nld/login"

            # 1) первый заход именно на /login и принятие cookies
            driver.get(LOGIN_URL)
            self._click_if_visible(driver, By.ID, "onetrust-accept-btn-handler", timeout=5)

            self._pause_for_admin("new_tab", "Зайди на сайт через другую вкладку и нажми /continue")

            # после /continue
            for h in driver.window_handles:
                driver.switch_to.window(h)
                try:
                    if "/login" in driver.current_url:
                        break
                except Exception:
                    continue


            # ждём появления хотя бы одного поля из логин-формы
            wait.until(
                EC.any_of(
                    EC.presence_of_element_located((By.ID, "email")),
                    EC.presence_of_element_located((By.ID, "password")),
                    EC.presence_of_element_located((By.ID, "username"))  # не используем, но для надёжности
                )
            )

            # cookie banner закрываем, если есть
            self._click_if_visible(driver, By.ID, "onetrust-accept-btn-handler", timeout=5)

            # если всплыла капча - ставим паузу
            if has_captcha(driver):
                self._pause_for_admin("captcha", "Обнаружена капча — реши её, пришли /continue - вход продолжится и нажмется Login.")

            check_cancel()

            # берём только видимые поля
            email_input = None
            pwd_input = None
            try:
                cand = driver.find_element(By.ID, "email")
                if cand.is_displayed() and cand.is_enabled():
                    email_input = cand
            except Exception:
                pass

            try:
                cand = driver.find_element(By.ID, "password")
                if cand.is_displayed() and cand.is_enabled():
                    pwd_input = cand
            except Exception:
                pass

            # фолбэки (если id поменяли)
            if email_input is None:
                vis_texts = [el for el in driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='email']") if el.is_displayed() and el.is_enabled()]
                email_input = vis_texts[0] if vis_texts else None
            if pwd_input is None:
                vis_pwds = [el for el in driver.find_elements(By.CSS_SELECTOR, "input[type='password']") if el.is_displayed() and el.is_enabled()]
                pwd_input = vis_pwds[0] if vis_pwds else None

            if not email_input or not pwd_input:
                raise RuntimeError("Не нашли видимые поля логина/пароля (возможно, мешает баннер или другая модалка).")
            
            check_cancel()

            # заполняем
            self._fill_visible(email_input, email_or_username)
            self._fill_visible(pwd_input, password)

            # ищем submit-кнопку в ближайшей форме
            form_el = self._closest_form(driver, pwd_input) or self._closest_form(driver, email_input)
            submit_btn = None
            if form_el:
                try:
                    submit_btn = self._first_visible_enabled(form_el, By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
                except Exception:
                    submit_btn = None

            # фолбэк: первый видимый enabled submit на странице
            if submit_btn is None:
                submit_btn = self._first_visible_enabled(driver, By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")

            if submit_btn is None:
                # иногда кнопку активируют только после blur - отдадим enter
                pwd_input.send_keys(Keys.TAB)
                pwd_input.send_keys(Keys.ENTER)

            else:
                # ждём, пока она действительно станет enabled
                self._wait_enabled_clickable(driver, submit_btn, timeout=10)
                submit_btn.click()

            # Можно дождаться смены URL или появления индикатора ошибки
            time.sleep(5)
            # --- нажать кнопку "Start New Booking" после логина ---

            # пробуем наиболее надёжные локаторы по очереди
            clicked = False
            for locator in [
                (By.XPATH, "//a[@id='start_new_booking' or contains(@id,'start_new_booking')]"),
                (By.XPATH, "//button[.//span[normalize-space()='Start New Booking'] or contains(normalize-space(), 'Start New Booking')]"),
                (By.XPATH, "//a[.//span[normalize-space()='Start New Booking'] or contains(normalize-space(), 'Start New Booking')]"),
                (By.XPATH, "//*[self::button or self::a][contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'START NEW BOOKING')]"),
            ]:
                try:
                    el = wait.until(EC.presence_of_element_located(locator))
                    if el.is_displayed() and el.is_enabled():
                        # доводим до кликабельности/активности
                        self._wait_enabled_clickable(driver, el, timeout=10)
                        try:
                            el.click()
                        except Exception:
                            # скролл к элементу и JS-клик как фолбэк
                            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                            try:
                                el.click()
                            except Exception:
                                driver.execute_script("arguments[0].click();", el)
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                raise RuntimeError("Не удалось найти кнопку 'Start New Booking'.")
            
            # ждём перехода на следующий шаг/страницу бронирования
            try:
                wait.until(EC.url_changes("https://visa.vfsglobal.com/rus/en/nld/dashboard"))
            except Exception:
                pass

            # === Appointment Details ===
            city = (form_data or {}).get("city", "")
            self._fill_appointment_details(city=city, subcategory="SEAMEN")

            # ждём перехода на следующий шаг
            try:
                wait.until(EC.url_changes("https://visa.vfsglobal.com/rus/en/nld/application-detail"))
            except Exception:
                pass

            # добавить задержку 5 секунд

            if has_captcha(driver):
                return {
                    "ok": False,
                    "url": driver.current_url,
                    "message": "infinite captcha",
                }

            if self._has_no_slots_alert():
                return {
                    "ok": False,
                    "url": driver.current_url,
                    "message": "no application slots",
                }

            return {
                "ok": True,
                "url": driver.current_url,
                "message": "have application slots!!!",
            }

        except Exception as e:
            info = {
                "ok": False,
                "url": None,
                "message": "job failed",
            }

            try:
                info["url"] = driver.current_url

            except Exception:
                pass

            if "no_application_slots" in str(e):
                info["message"] = "no_application_slots"

            raise