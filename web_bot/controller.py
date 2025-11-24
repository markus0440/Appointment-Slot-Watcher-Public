import asyncio
import contextlib
import threading
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from web_bot.web_bot import BotThread 
from db.data_access import JobActions, UserActions 

import os, random
from dotenv import load_dotenv

load_dotenv()

EMAIL = str(os.getenv("EMAIL", "0"))
PASSWORD = str(os.getenv("PASSWORD", "0"))
ALLOWED_CITIES = os.getenv("ALLOWED_CITIES", "")
ALLOWED_CITIES = [c.strip() for c in ALLOWED_CITIES.split(",") if c.strip()]

# ==== Контроллер жизненного цикла внешнего веб-бота ====
class Controller():
    def __init__(self) -> None:
        self.bot: Optional[BotThread] = None
        self.stop_event: Optional[asyncio.Event] = None
        self.running: bool = False
        self.job_actions = JobActions()

        # планировщик
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.user_actions = UserActions()

        # для создания пауз в работе бота и обращения к админу
        self._loop: Optional[asyncio.AbstractEventLoop] = None # ссылка на event loop, в котором всё запускается
        self._send_admin_coro = None  # async callable(dict)
        self._notify_users = None # async callable(list[int], bool)
        self._resume_evt = threading.Event() # событие паузы
        self._resume_evt.set()

    async def _process_next_user(self):
        
        row = await self.user_actions.next_user_to_apply()
        if not row:
            return {"ok": False, "message": "no users in queue"}, ""  # (dict, None)

        user_id, login, password, _, _ = row
        city = random.choice(ALLOWED_CITIES)

        try:
            fut = self.bot.submit("test_vfs", form_data={"login": login, "password": password, "city": city})
            # не даём таймауту отменять исходный future:
            result = await asyncio.wait_for(asyncio.shield(fut), timeout=120)

            await self.job_actions.save_result(
                status="ok" if result.get("ok") else "fail",
                user_id=user_id,
                url=result.get("url"),
                payload={**result},
            )
            return result, city

        except asyncio.TimeoutError:
            await self.job_actions.save_result(status="fail", user_id=user_id, url=None, payload={"error": "timeout"})
            await self.user_actions.change_user_status(user_id=user_id, apply_status='0_waiting')
            return {"ok": False, "error": "timeout"}, city

        except Exception as e:
            await self.job_actions.save_result(status="fail", user_id=user_id, url=None, payload={"error": str(e)})
            await self.user_actions.change_user_status(user_id=user_id, apply_status='0_waiting')
            return {"ok": False, "error": str(e)}, city
            
    async def _scheduled_job(self):
        # рандомная задержка перед выполнением (костыль)
        await asyncio.sleep(random.randint(0, 60))
        
        if not self.running or not self.bot:
            return
        result, city = await self._process_next_user()

        if result.get('ok'):
            chat_ids = await self.user_actions.get_chat_ids_by_status()
            await self._notify_users(chat_ids, city, True)

        if not result.get('ok'): # это для отладки
            chat_ids = await self.user_actions.get_chat_ids_by_status()
            await self._notify_users(chat_ids, city, False)

        if self._send_admin_coro:
            await self._send_admin_coro({"type":"scheduler", "message": str(result), "url": result.get("url",""), "city": city})


    async def start(self, loop: asyncio.AbstractEventLoop, send_admin_coro=None, notify_users=None):
        if self.running:
            return "Уже запущен."
        
        self._loop = loop
        self._send_admin_coro = send_admin_coro # сообщения для админа
        self._notify_users = notify_users # сообщения для пользователей

        # коллбек из потока веб-бота в event loop
        def notify(event: dict):
            if self._send_admin_coro:
                loop.call_soon_threadsafe(asyncio.create_task, self._send_admin_coro(event))

        self.bot = BotThread(loop, notify=notify, resume_evt=self._resume_evt)
        self.bot.start()

        self.stop_event = asyncio.Event()

        # интервал можно вынести в .env
        interval_seconds = int(os.getenv("SCHED_INTERVAL_SEC", "30"))  # по умолчанию каждые 5 минут

        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(
            self._scheduled_job,
            IntervalTrigger(seconds=interval_seconds),
            id="vfsglobal_job",
            max_instances=1,        # чтобы не было параллельных накладок
            coalesce=True,          # объединять пропуски
            misfire_grace_time=60
        )
        self.scheduler.start()

        self.running = True
        return "Запущено: bot + scheduler."
    
    async def resume(self) -> bool:
        """Команда /continue от админа: снять паузу, если она активна."""
        if not self._resume_evt.is_set():
            self._resume_evt.set()
            return True
        return False

    async def stop(self):
        if not self.running:
            return "И так остановлено."
        
        # попросим остановиться
        if self.stop_event:
            self.stop_event.set()

        # стопаем APScheduler
        if self.scheduler:
            try:
                self.scheduler.remove_all_jobs()
                self.scheduler.shutdown(wait=False)
            except Exception:
                pass
            self.scheduler = None

        # остановим поток с ботом
        if self.bot:
            self.bot.stop()

        # очистка
        self.bot = None
        self.stop_event = None
        self.running = False
        return "Остановлено: bot + scheduler."

    async def run_once(self):
        if not self.running or not self.bot:
            return {"ok": False, "error": "Не запущено. Сначала /start_job"}
        result, city = await self._process_next_user()

        if result.get('ok'):
            chat_ids = await self.user_actions.get_chat_ids_by_status()
            await self._notify_users(chat_ids, city, True)

        if not result.get('ok'): # это для отладки
            chat_ids = await self.user_actions.get_chat_ids_by_status()
            await self._notify_users(chat_ids, city, False)

        return result