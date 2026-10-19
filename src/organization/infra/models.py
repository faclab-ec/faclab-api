from datetime import datetime

from sqlalchemy import ForeignKeyConstraint, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped


class BranchModel(TenantScoped, Base):
    __tablename__ = "branches"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "establishment_code",
            name="uq_branches_tenant_establishment_code",
        ),
        # Target of the composite foreign keys from warehouses, emission points,
        # terminals and user branch accesses
        UniqueConstraint("tenant_id", "id", name="uq_branches_tenant_id_id"),
        # One main branch (matriz) per tenant
        Index(
            "uq_branches_tenant_main",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_main"),
            sqlite_where=text("is_main"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    establishment_code: Mapped[str] = mapped_column(String(3), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    address: Mapped[str | None] = mapped_column(String(300))
    is_main: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime | None] = mapped_column(default=datetime.now)


class EmissionPointModel(TenantScoped, Base):
    __tablename__ = "emission_points"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "branch_id",
            "code",
            name="uq_emission_points_tenant_branch_code",
        ),
        # Target of the composite foreign key from terminals
        UniqueConstraint("tenant_id", "id", name="uq_emission_points_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_emission_points_branch_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(3), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime | None] = mapped_column(default=datetime.now)


class PosTerminalModel(TenantScoped, Base):
    __tablename__ = "pos_terminals"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "branch_id", "code", name="uq_pos_terminals_tenant_branch_code"
        ),
        # Target of the composite foreign key from shifts (S2.6)
        UniqueConstraint("tenant_id", "id", name="uq_pos_terminals_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_pos_terminals_branch_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "emission_point_id"],
            ["emission_points.tenant_id", "emission_points.id"],
            name="fk_pos_terminals_emission_point_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "default_location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_pos_terminals_default_location_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(nullable=False, index=True)
    emission_point_id: Mapped[int] = mapped_column(nullable=False, index=True)
    default_location_id: Mapped[int] = mapped_column(nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime | None] = mapped_column(default=datetime.now)
