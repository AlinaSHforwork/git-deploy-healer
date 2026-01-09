"""Tests for database models and DatabaseManager - SQLAlchemy compatible."""

from datetime import datetime

import pytest
from sqlalchemy import inspect

from core.models import (
    AuditLog,
    Container,
    DatabaseManager,
    Deployment,
    DeploymentStatus,
    get_db_manager,
)


@pytest.fixture
def db_manager():
    """Create temporary in-memory database for testing."""
    db_url = "sqlite:///:memory:"
    manager = DatabaseManager(db_url)
    manager.create_tables()
    yield manager
    manager.drop_tables()


@pytest.fixture
def db_session(db_manager):
    """Create database session for testing."""
    session = db_manager.get_session()
    yield session
    session.close()


class TestDeploymentModel:
    """Test Deployment model."""

    def test_create_deployment(self, db_session):
        """Test creating a deployment record."""
        deployment = Deployment(
            app_name="test-app",
            image_tag="test-app:latest",
            commit_hash="abc123",
            status=DeploymentStatus.QUEUED,
            repo_url="https://github.com/test/app.git",
            deployed_by="user@example.com",
        )

        db_session.add(deployment)
        db_session.commit()

        assert deployment.id is not None
        assert deployment.app_name == "test-app"
        assert deployment.created_at is not None

    def test_deployment_status_transition(self, db_session):
        """Test deployment status transitions."""
        deployment = Deployment(
            app_name="test-app",
            image_tag="test-app:v1",
            status=DeploymentStatus.QUEUED,
        )
        db_session.add(deployment)
        db_session.commit()

        # Transition to building
        deployment.status = DeploymentStatus.BUILDING
        deployment.started_at = datetime.utcnow()
        db_session.commit()

        # Transition to running
        deployment.status = DeploymentStatus.RUNNING
        deployment.completed_at = datetime.utcnow()
        db_session.commit()

        assert deployment.status == DeploymentStatus.RUNNING
        assert deployment.started_at is not None
        assert deployment.completed_at is not None

    def test_deployment_with_error(self, db_session):
        """Test deployment with error message."""
        deployment = Deployment(
            app_name="failing-app",
            image_tag="failing-app:v1",
            status=DeploymentStatus.FAILED,
            error_message="Build failed: missing Dockerfile",
        )
        db_session.add(deployment)
        db_session.commit()

        assert deployment.error_message == "Build failed: missing Dockerfile"

    def test_deployment_repr(self, db_session):
        """Test deployment string representation."""
        deployment = Deployment(
            app_name="test-app",
            image_tag="test-app:latest",
            status=DeploymentStatus.RUNNING,
        )

        repr_str = repr(deployment)
        assert "test-app" in repr_str
        assert "running" in repr_str.lower()


class TestContainerModel:
    """Test Container model."""

    def test_create_container(self, db_session):
        """Test creating a container record."""
        container = Container(
            container_id="abc123def456",
            app_name="test-app",
            host_port=8080,
            container_port=80,
            domain="test-app.localhost",
            status="running",
        )

        db_session.add(container)
        db_session.commit()

        assert container.id is not None
        assert container.container_id == "abc123def456"
        assert container.host_port == 8080

    def test_container_with_deployment(self, db_session):
        """Test container linked to deployment."""
        deployment = Deployment(
            app_name="test-app",
            image_tag="test-app:v1",
            status=DeploymentStatus.RUNNING,
        )
        db_session.add(deployment)
        db_session.commit()

        container = Container(
            container_id="xyz789",
            app_name="test-app",
            deployment_id=deployment.id,
            status="running",
        )
        db_session.add(container)
        db_session.commit()

        # Test relationship
        assert container.deployment.app_name == "test-app"
        assert deployment.containers[0].container_id == "xyz789"

    def test_container_health_tracking(self, db_session):
        """Test container health check tracking."""
        container = Container(
            container_id="health123",
            app_name="test-app",
            status="running",
            health_check_failures=0,
            last_health_check=datetime.utcnow(),
        )
        db_session.add(container)
        db_session.commit()

        # Simulate failed health check
        container.health_check_failures += 1
        container.last_health_check = datetime.utcnow()
        db_session.commit()

        assert container.health_check_failures == 1

    def test_container_stopped(self, db_session):
        """Test container stop tracking."""
        container = Container(
            container_id="stop123",
            app_name="test-app",
            status="running",
        )
        db_session.add(container)
        db_session.commit()

        # Stop container
        container.status = "stopped"
        container.stopped_at = datetime.utcnow()
        db_session.commit()

        assert container.stopped_at is not None


class TestAuditLogModel:
    """Test AuditLog model."""

    def test_create_audit_log(self, db_session):
        """Test creating audit log entry."""
        log = AuditLog(
            action="deploy",
            resource_type="container",
            resource_id="abc123",
            user="admin@example.com",
            ip_address="192.168.1.1",
            details="Deployed test-app:v1",
            success=True,
        )

        db_session.add(log)
        db_session.commit()

        assert log.id is not None
        assert log.action == "deploy"
        assert log.success is True

    def test_audit_log_failure(self, db_session):
        """Test audit log for failed action."""
        log = AuditLog(
            action="deploy",
            resource_type="container",
            resource_id="xyz789",
            user="user@example.com",
            ip_address="10.0.0.1",
            success=False,
            error_message="Deployment failed: timeout",
        )

        db_session.add(log)
        db_session.commit()

        assert log.success is False
        assert "timeout" in log.error_message


class TestDatabaseManager:
    """Test DatabaseManager functionality."""

    def test_create_tables(self):
        """Test table creation - SQLAlchemy 2.0 compatible."""
        db_url = "sqlite:///:memory:"
        manager = DatabaseManager(db_url)
        manager.create_tables()

        # Use inspect() function correctly
        inspector = inspect(manager.engine)
        tables = inspector.get_table_names()

        assert "deployments" in tables
        assert "containers" in tables
        assert "audit_logs" in tables

    def test_get_session(self, db_manager):
        """Test session creation."""
        session = db_manager.get_session()
        assert session is not None
        session.close()

    def test_drop_tables(self):
        """Test table dropping - SQLAlchemy 2.0 compatible."""
        db_url = "sqlite:///:memory:"
        manager = DatabaseManager(db_url)
        manager.create_tables()
        manager.drop_tables()

        # Use inspect() function correctly
        inspector = inspect(manager.engine)
        tables = inspector.get_table_names()

        assert len(tables) == 0


class TestGetDBManager:
    """Test get_db_manager singleton function."""

    def test_get_db_manager_with_url(self, monkeypatch):
        """Test get_db_manager with explicit URL."""
        # Reset singleton
        import core.models

        core.models._db_manager = None

        db_url = "sqlite:///:memory:"
        manager = get_db_manager(db_url)

        assert manager is not None
        assert isinstance(manager, DatabaseManager)

    def test_get_db_manager_from_env(self, monkeypatch):
        """Test get_db_manager reads from environment."""
        # Reset singleton
        import core.models

        core.models._db_manager = None

        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

        manager = get_db_manager()
        assert manager is not None

    def test_get_db_manager_no_url(self, monkeypatch):
        """Test get_db_manager raises when no URL available."""
        # Reset singleton
        import core.models

        core.models._db_manager = None

        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(ValueError, match="DATABASE_URL not configured"):
            get_db_manager()

    def test_get_db_manager_singleton(self, monkeypatch):
        """Test get_db_manager returns same instance."""
        # Reset singleton
        import core.models

        core.models._db_manager = None

        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

        manager1 = get_db_manager()
        manager2 = get_db_manager()

        assert manager1 is manager2


class TestIntegration:
    """Integration tests for models."""

    def test_full_deployment_lifecycle(self, db_session):
        """Test complete deployment lifecycle with all models."""
        # Create deployment
        deployment = Deployment(
            app_name="production-app",
            image_tag="production-app:v2.1.0",
            commit_hash="abc123def456",
            status=DeploymentStatus.QUEUED,
            repo_url="https://github.com/company/prod-app.git",
            deployed_by="deploy-bot@company.com",
        )
        db_session.add(deployment)
        db_session.commit()

        # Log deployment start
        audit_start = AuditLog(
            action="deployment_start",
            resource_type="deployment",
            resource_id=str(deployment.id),
            user="deploy-bot@company.com",
            ip_address="10.0.1.50",
            success=True,
        )
        db_session.add(audit_start)

        # Update deployment status
        deployment.status = DeploymentStatus.BUILDING
        deployment.started_at = datetime.utcnow()
        db_session.commit()

        # Create container
        container = Container(
            container_id="prod-container-12345",
            app_name="production-app",
            deployment_id=deployment.id,
            host_port=8080,
            container_port=80,
            domain="app.company.com",
            status="running",
        )
        db_session.add(container)

        # Complete deployment
        deployment.status = DeploymentStatus.RUNNING
        deployment.completed_at = datetime.utcnow()

        # Log success
        audit_complete = AuditLog(
            action="deployment_complete",
            resource_type="deployment",
            resource_id=str(deployment.id),
            user="deploy-bot@company.com",
            ip_address="10.0.1.50",
            details=f"Container {container.container_id} running on port {container.host_port}",
            success=True,
        )
        db_session.add(audit_complete)
        db_session.commit()

        # Verify everything is linked
        assert deployment.containers[0].container_id == "prod-container-12345"
        assert container.deployment.app_name == "production-app"

        # Query audit logs
        logs = (
            db_session.query(AuditLog).filter_by(resource_id=str(deployment.id)).all()
        )
        assert len(logs) == 2
