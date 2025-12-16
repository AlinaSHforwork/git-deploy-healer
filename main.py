import sys
import os
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

    engine = ContainerEngine()

    try:
        tag = engine.build_image(project_path, app_name)
        result = engine.deploy(app_name, tag)
        
        if result.status == "failed":
            logger.critical(f"Deployment Failed: {result.error}")
            sys.exit(1)
            
        logger.success(f"Deployed {app_name} successfully!")
        logger.success(f"Container ID: {result.container_id[:12]}")
        logger.success(f"Access it at: http://localhost:{result.host_port}")

    except Exception as e:
        logger.exception("Fatal error during execution")
        sys.exit(1)

if __name__ == "__main__":
    main()