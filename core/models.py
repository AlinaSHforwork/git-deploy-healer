"""Database models for deployment tracking and audit logs.

This module provides SQLAlchemy models for:
- Deployment history
- Container metadata
- Audit logs
"""
from datetime import datetime
from typing import Optional
from venv import logger

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class DeploymentStatus(str, Enum):
    """Deployment status enum."""

    QUEUED = "queued"
    BUILDING = "building"
    DEPLOYING = "deploying"
    RUNNING = "running"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class Deployment(Base):
    """Deployment history tracking."""

    __tablename__ = "deployments"

    id = Column(Integer, primary_key=True)
    app_name = Column(String(255), nullable=False, index=True)
    image_tag = Column(String(255), nullable=False)
    commit_hash = Column(String(64), nullable=True)
    status = Column(String(50), nullable=False, default=DeploymentStatus.QUEUED)
    error_message = Column(Text, nullable=True)

    # Metadata
    repo_url = Column(String(512), nullable=True)
    deployed_by = Column(String(255), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    containers = relationship("Container", back_populates="deployment")

    def __repr__(self):
        return f"<Deployment {self.app_name}:{self.image_tag} ({self.status})>"


class Container(Base):
    """Container metadata and health tracking."""

    __tablename__ = "containers"

    id = Column(Integer, primary_key=True)
    container_id = Column(String(128), unique=True, nullable=False, index=True)
    app_name = Column(String(255), nullable=False, index=True)
    deployment_id = Column(Integer, ForeignKey("deployments.id"), nullable=True)

    # Network config
    host_port = Column(Integer, nullable=True)
    container_port = Column(Integer, nullable=True)
    domain = Column(String(255), nullable=True)

    # Health status
    status = Column(String(50), nullable=False, default="running")
    health_check_failures = Column(Integer, default=0)
    last_health_check = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    stopped_at = Column(DateTime, nullable=True)

    # Relationships
    deployment = relationship("Deployment", back_populates="containers")

    def __repr__(self):
        return f"<Container {self.container_id[:12]} ({self.app_name})>"


class AuditLog(Base):
    """Audit log for all system actions."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(255), nullable=True)

    # Actor information
    user = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True)  # IPv6 compatible

    # Action details
    details = Column(Text, nullable=True)
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<AuditLog {self.action} on {self.resource_type} at {self.created_at}>"


class DatabaseManager:
    """Database connection and session management with proper pooling."""

    def __init__(
        self,
        database_url: str,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
        echo: bool = False,
    ):
        """Initialize database connection with production-ready pooling.

        Args:
            database_url: SQLAlchemy database URL
            pool_size: Number of connections to maintain in the pool
            max_overflow: Max number of connections above pool_size
            pool_timeout: Seconds to wait before giving up on getting a connection
            pool_recycle: Recycle connections after this many seconds (prevents stale connections)
            echo: Echo SQL statements (for debugging)
        """
        # Parse URL to determine if SQLite (which doesn't support pooling)
        is_sqlite = database_url.startswith("sqlite:")

        if is_sqlite:
            # SQLite doesn't support connection pooling
            self.engine = create_engine(
                database_url,
                echo=echo,
                connect_args={"check_same_thread": False},  # Required for SQLite
            )
        else:
            # PostgreSQL/MySQL with connection pooling
            self.engine = create_engine(
                database_url,
                echo=echo,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
                pool_recycle=pool_recycle,
                pool_pre_ping=True,  # Verify connections before using
            )

        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
            expire_on_commit=False,  # Prevent lazy loading errors after commit
        )

    def create_tables(self):
        """Create all tables."""
        Base.metadata.create_all(bind=self.engine)

    def drop_tables(self):
        """Drop all tables (use with caution)."""
        Base.metadata.drop_all(bind=self.engine)

    def get_session(self):
        """Get database session.

        IMPORTANT: Caller must close the session when done.
        Better to use get_session_context() context manager.
        """
        return self.SessionLocal()

    def get_session_context(self):
        """Get database session as context manager (recommended).

        Usage:
            with db_manager.get_session_context() as session:
                session.add(obj)
                session.commit()
        """
        from contextlib import contextmanager

        @contextmanager
        def _session_scope():
            session = self.SessionLocal()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        return _session_scope()

    def dispose(self):
        """Dispose of the connection pool.

        Should be called on application shutdown.
        """
        self.engine.dispose()

    def health_check(self) -> bool:
        """Check if database connection is healthy.

        Returns:
            True if database is accessible
        """
        try:
            with self.get_session_context() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False


# Singleton instance with proper lifecycle management
_db_manager: Optional[DatabaseManager] = None
_db_manager_lock = None  # Will be initialized on first use


def get_db_manager(
    database_url: Optional[str] = None,
    reset: bool = False,
    **kwargs,
) -> DatabaseManager:
    """Get or create database manager singleton with thread-safe initialization.

    Args:
        database_url: Database URL (required on first call)
        reset: Force recreation of the singleton (for testing)
        **kwargs: Additional arguments passed to DatabaseManager

    Returns:
        DatabaseManager instance
    """
    global _db_manager, _db_manager_lock

    # Lazy import to avoid issues at module load time
    import threading

    if _db_manager_lock is None:
        _db_manager_lock = threading.Lock()

    # Thread-safe singleton creation
    with _db_manager_lock:
        if _db_manager is None or reset:
            # Dispose old manager if resetting
            if _db_manager is not None and reset:
                try:
                    _db_manager.dispose()
                except Exception as e:
                    logger.warning(f"Error disposing old db_manager: {e}")

            # Get database URL
            if database_url is None:
                import os

                database_url = os.getenv("DATABASE_URL")
                if not database_url:
                    raise ValueError(
                        "DATABASE_URL not configured. "
                        "Set DATABASE_URL environment variable or pass database_url parameter."
                    )

            # Create new manager
            _db_manager = DatabaseManager(database_url, **kwargs)
            _db_manager.create_tables()

    return _db_manager


def dispose_db_manager():
    """Dispose of the database manager singleton.

    Should be called on application shutdown.
    """
    global _db_manager
    if _db_manager is not None:
        try:
            _db_manager.dispose()
        except Exception as e:
            logger.error(f"Error disposing db_manager: {e}")
        finally:
            _db_manager = None
