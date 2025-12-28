import os
import sys

from loguru import logger

from core.engine import ContainerEngine


def main():
    if len(sys.argv) < 3:
        logger.error("Usage: python main.py <app_name> <path_to_dockerfile_dir>")
        sys.exit(1)

    app_name = sys.argv[1]
    project_path = sys.argv[2]

    if not os.path.exists(project_path):
        logger.error(f"Path {project_path} does not exist")
        sys.exit(1)

    logger.info(f"Starting deployment for {app_name}")
    engine = ContainerEngine()

    try:
        logger.info(f"Building image from {project_path}...")
        tag = engine.build_image(project_path, app_name)
        logger.success(f"Image built: {tag}")

        logger.info("Deploying container...")
        result = engine.deploy(app_name, tag)

        if result.status == "failed":
            logger.critical(f"Deployment Failed: {result.error}")
            sys.exit(1)

        logger.success(f"Deployed {app_name} successfully!")
        logger.success(
            f"Container ID: {result.container_id[:12] if result.container_id else 'N/A'}"
        )
        if result.host_port:
            logger.success(f"Access it at: http://localhost:{result.host_port}")

    except Exception as e:
        logger.exception(f"Fatal error during execution: {e}")
        sys.exit(1)
