"""Database models for deployment tracking and audit logs.

This module provides SQLAlchemy models for:
- Deployment history
- Container metadata
- Audit logs
"""
from datetime import datetime
from typing import Optional

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
)
from sqlalchemy.orm import relationship, sessionmaker

from sqlalchemy.orm import DeclarativeBase


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
    """Database connection and session management."""
    
    def __init__(self, database_url: str):
        """Initialize database connection.
        
        Args:
            database_url: SQLAlchemy database URL
        """
        self.engine = create_engine(database_url, echo=False)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
    
    def create_tables(self):
        """Create all tables."""
        Base.metadata.create_all(bind=self.engine)
    
    def drop_tables(self):
        """Drop all tables (use with caution)."""
        Base.metadata.drop_all(bind=self.engine)
    
    def get_session(self):
        """Get database session."""
        return self.SessionLocal()


# Singleton instance
_db_manager: Optional[DatabaseManager] = None


def get_db_manager(database_url: Optional[str] = None) -> DatabaseManager:
    """Get or create database manager singleton.
    
    Args:
        database_url: Database URL (required on first call)
        
    Returns:
        DatabaseManager instance
    """
    global _db_manager
    
    if _db_manager is None:
        if database_url is None:
            import os
            database_url = os.getenv("DATABASE_URL")
            if not database_url:
                raise ValueError("DATABASE_URL not configured")
        
        _db_manager = DatabaseManager(database_url)
        _db_manager.create_tables()
    
    return _db_manager