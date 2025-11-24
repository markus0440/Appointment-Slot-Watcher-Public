from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from db.db import SessionLocal
from db.models import JobResult, Users
from typing import Literal

import asyncio # убрать

class JobActions:
    async def save_result(self, *,
                          status: str,
                          user_id: int,
                          url: str | None,
                          payload: dict | None):
        
        async with SessionLocal() as session:
            obj = JobResult(status=status, user_id=user_id, url=url, payload=payload)
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj

    async def get_last(self):
        async with SessionLocal() as session:
            stmt = select(JobResult).order_by(JobResult.id.desc()).limit(1)
            res = await session.execute(stmt)
            return res.scalar_one_or_none()

class UserActions:
    async def register_user(self, *,
                            login: str,
                            password_encrypted: str,
                            telegram_username: str,
                            apply_status: str | None = None) -> Users:
        
        async with SessionLocal() as session:
            user = Users(
                login=login.strip(),
                password=password_encrypted.strip(),
                telegram_username=telegram_username.strip(),
                # если статус не передан или пустой - используем дефолт из модели
                apply_status=(apply_status.strip() if apply_status and apply_status.strip()
                              else "0_waiting")
            )
            session.add(user)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                raise ValueError("Логин или Telegram-ник уже заняты.")
            await session.refresh(user)
            return user
        
    async def register_basic_user(self, *,
                                  telegram_username: str,
                                  chat_id: int) -> Users:
        
        async with SessionLocal() as session:
            # если уже есть запись по chat_id или username — сопоставим/обновим
            res = await session.execute(
                select(Users).where(
                    or_(Users.chat_id == chat_id, Users.telegram_username == telegram_username.strip())
                )
            )
            user = res.scalar_one_or_none()
            if user:
                user.chat_id = chat_id
                user.telegram_username = telegram_username.strip()
                user.apply_status = "3_user"
                await session.commit()
                await session.refresh(user)
                return user

            user = Users(
                telegram_username=telegram_username.strip(),
                chat_id=chat_id,
                apply_status="3_user"
            )
            session.add(user)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                raise ValueError("Пользователь с таким chat_id или ником уже существует.")
            await session.refresh(user)
            return user
        
    async def next_user_to_apply(self) -> tuple[int, str | None, str | None, str | None, bool] | None:
        """
        Карусель по пользователям:
        - Если есть текущий 1_in_progress то ищем следующего 0_waiting с id > current.id,
          иначе переходим к минимальному id.
        - Перекладываем токен: current ставим 0_waiting, next ставим 1_in_progress.
        - Если 0_waiting нет совсем — возвращаем current.
        """
        async with SessionLocal() as session:
            # 1) текущий держатель токена
            res = await session.execute(
                select(Users)
                .where(Users.apply_status == "1_in_progress")
                .order_by(Users.id.asc())
                .limit(1)
            )
            current = res.scalar_one_or_none()

            if current is None:
                # первый запуск: берём самого раннего ожидающего
                res = await session.execute(
                    select(Users)
                    .where(Users.apply_status == "0_waiting")
                    .order_by(Users.id.asc())
                    .limit(1)
                )
                nxt = res.scalar_one_or_none()
                if nxt is None:
                    return None  # пустая очередь
                nxt.apply_status = "1_in_progress"
                await session.commit()
                await session.refresh(nxt)
                return nxt.id, nxt.login, nxt.password, nxt.city, False

            # 2) есть current: ищем следующего после него
            res = await session.execute(
                select(Users)
                .where(Users.apply_status == "0_waiting", Users.id > current.id)
                .order_by(Users.id.asc())
                .limit(1)
            )
            nxt = res.scalar_one_or_none()

            if nxt is None:
                # переходим к самому маленькому ожидающему
                res = await session.execute(
                    select(Users)
                    .where(Users.apply_status == "0_waiting")
                    .order_by(Users.id.asc())
                    .limit(1)
                )
                nxt = res.scalar_one_or_none()
                
            if nxt is None:
                # Никто не ждёт — продолжаем текущего
                await session.refresh(current)
                return current.id, current.login, current.password, current.city, True

            # 3) перекладываем токен
            current.apply_status = "0_waiting"
            nxt.apply_status = "1_in_progress"
            await session.commit()
            await session.refresh(nxt)
            return nxt.id, nxt.login, nxt.password, nxt.city, False

    async def change_user_status(self, *,
                                 user_id: int,
                                 apply_status: Literal['0_waiting', '2_apply_made'] = '2_apply_made') -> bool:
        """
        Меняет статус пользователя тольео если текущий статус == '1_in_progress'.
        По умолчанию переводит в '2_apply_made', опционально в '0_waiting'.
        Возвращает True при успехе, иначе False.
        """
        async with SessionLocal() as session:
            user = await session.get(Users, user_id)
            if user is None:
                return False

            if user.apply_status != '1_in_progress': # TO_DO добавить нормальный raise ошибок
                return False

            user.apply_status = apply_status
            await session.commit()
            return True
        

    async def get_chat_ids_by_status(self,
                                     status: str = "3_user") -> list[int]:
        """
        Вернуть список chat_id всех пользователей с заданным статусом.
        По умолчанию — '3_user'. NULL-значения исключаются.
        """
        async with SessionLocal() as session:
            res = await session.execute(
                select(Users.chat_id).where(
                    Users.apply_status == status,
                    Users.chat_id.is_not(None)
                )
            )
            return [cid for cid in res.scalars().all() if cid is not None]

if __name__ == "__main__":

    async def main():
        ua = UserActions()

        row = await ua.next_user_to_apply()
        print("next_user_to_apply →", row)

        chat_ids = await ua.get_chat_ids_by_status()
        print("users →", chat_ids)

        #if row:
            #user_id, *_ = row
            #ok = await ua.change_user_status(user_id=user_id)
            #print("change_user_status →", ok)

    asyncio.run(main())
"""
async def next_user_to_apply(self) -> tuple[int, str, str, str, bool] | None:

        Возвращает кортеж (user_id, login, password, city, resumed).
        Логика:
        1) Если есть пользователь со статусом '1_in_progress' — отдаем его (resumed=True).
        2) Иначе берём первого со статусом '0_waiting', ставим ему '1_in_progress' и отдаем (resumed=False).
        3) Если никого нет — возвращаем None.

        async with SessionLocal() as session:
            # 1) Продолжить ранее начатого
            res = await session.execute(
                select(Users)
                .where(Users.apply_status == "1_in_progress")
                .order_by(Users.id.asc())
                .limit(1)
            )
            user = res.scalar_one_or_none()

            if user is not None:
                user.apply_status = "0_waiting"
                await session.commit()
                return user.id, user.login, user.password, user.city, True

            # 2) Взять следующего ожидающего
            res = await session.execute(
                select(Users)
                .where(Users.apply_status == "0_waiting")
                .order_by(Users.id.asc())
                .limit(1)
            )
            user = res.scalar_one_or_none()
            if user is None:
                return None

            user.apply_status = "1_in_progress"
            await session.commit()
            return user.id, user.login, user.password, user.city, False
"""