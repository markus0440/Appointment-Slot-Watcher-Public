from datetime import datetime
from sqlalchemy import String, DateTime, Integer, BigInteger, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Users(Base):
    __tablename__ = 'Users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    login: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    password: Mapped[str | None] = mapped_column(String(255), nullable=True)  # логины и пароли только админа
    telegram_username: Mapped[str] = mapped_column(String(64), unique=False, nullable=False) # ДЛЯ ОТЛАДКИ unique=False
    city: Mapped[str | None] = mapped_column(String(64), nullable=True)
    apply_status:  Mapped[str] = mapped_column(String(64), nullable=False, default="0_waiting", server_default="0_waiting")

    def __repr__(self):
        return f"<User id={self.id} login={self.login} tg=@{self.telegram_username} apply_status={self.apply_status}>"
    
class JobResult(Base):
    __tablename__ = "job_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, primary_key=False) #Нужно добавить логику в остальном коде под это
    status: Mapped[str] = mapped_column(String(16))
    url: Mapped[str | None] = mapped_column(String(512))
    payload: Mapped[dict | None] = mapped_column(JSON)