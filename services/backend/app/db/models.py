"""T40 - Tables SQLAlchemy. Les saisies variables (sol, eau, priorités, instantanés) sont en JSON."""
import datetime as dt
import secrets

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def maintenant() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def nouvel_id(prefixe: str) -> str:
    return f"{prefixe}_{secrets.token_hex(5)}"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=lambda: nouvel_id("usr"))
    full_name: Mapped[str] = mapped_column(String(120))
    identifier: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(5), default="fr")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=maintenant)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    token: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class ResetToken(Base):
    __tablename__ = "reset_tokens"
    token: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Farm(Base):
    __tablename__ = "farms"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=lambda: nouvel_id("frm"))
    name: Mapped[str] = mapped_column(String(120))
    region: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=maintenant)


class Member(Base):
    __tablename__ = "members"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=lambda: nouvel_id("mbr"))
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    identifier: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(12))                  # owner | co_farmer | advisor
    status: Mapped[str] = mapped_column(String(10))                # active | pending
    invitation_token: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    invitation_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class Parcel(Base):
    __tablename__ = "parcels"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=lambda: nouvel_id("pcl"))
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    geometry: Mapped[dict] = mapped_column(JSON)
    area_ha: Mapped[float] = mapped_column(Float)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    slope_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometry_version: Mapped[int] = mapped_column(Integer, default=1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=maintenant)


class ParcelData(Base):
    """Une ligne par (parcelle, sorte) : local_inputs | history | preferences."""
    __tablename__ = "parcel_data"
    parcel_id: Mapped[str] = mapped_column(ForeignKey("parcels.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=maintenant, onupdate=maintenant)


class Computation(Base):
    __tablename__ = "computations"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=lambda: nouvel_id("cmp"))
    parcel_id: Mapped[str] = mapped_column(ForeignKey("parcels.id", ondelete="CASCADE"), index=True)
    result: Mapped[dict] = mapped_column(JSON)
    request: Mapped[dict] = mapped_column(JSON)
    geometry_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=maintenant)


class SavedStrategy(Base):
    __tablename__ = "saved_strategies"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=lambda: nouvel_id("hist"))
    parcel_id: Mapped[str] = mapped_column(ForeignKey("parcels.id", ondelete="CASCADE"), index=True)
    strategy_id: Mapped[str] = mapped_column(String(12))
    snapshot: Mapped[dict] = mapped_column(JSON)
    saved_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    saved_role: Mapped[str] = mapped_column(String(12))
    geometry_version: Mapped[int] = mapped_column(Integer)
    saved_at: Mapped[dt.datetime] = mapped_column(DateTime, default=maintenant)
    # T65 : la rotation « choisie » est surveillée (une seule active par parcelle)
    monitoring_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    monitoring_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=lambda: nouvel_id("note"))
    saved_id: Mapped[str] = mapped_column(ForeignKey("saved_strategies.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    author_role: Mapped[str] = mapped_column(String(12))
    kind: Mapped[str] = mapped_column(String(12))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=maintenant)


class Notification(Base):
    """T65 : une notification par destinataire (chaque membre lit les siennes)."""
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=lambda: nouvel_id("ntf"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"))
    parcel_id: Mapped[str] = mapped_column(ForeignKey("parcels.id", ondelete="CASCADE"), index=True)
    saved_id: Mapped[str | None] = mapped_column(ForeignKey("saved_strategies.id", ondelete="CASCADE"), nullable=True)
    code: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))             # info | warning | critical
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    dedup_key: Mapped[str] = mapped_column(String(200), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=maintenant, index=True)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
