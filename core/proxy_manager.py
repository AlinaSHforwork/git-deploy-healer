import os
import docker
from jinja2 import Environment, FileSystemLoader
from loguru import logger

class ProxyManager:
    def __init__(self, conf_dir: str = "./nginx_confs"):
        self.client = docker.from_env()
        self.conf_dir = os.path.abspath(conf_dir)
        self.env = Environment(loader=FileSystemLoader("templates"))
        
        if not os.path.exists(self.conf_dir):
            os.makedirs(self.conf_dir)

    def register_app(self, app_name: str, port: int):
        template = self.env.get_template("app.conf.j2")
        config_content = template.render(app_name=app_name, container_port=port)
        
        conf_path = os.path.join(self.conf_dir, f"{app_name}.conf")
        with open(conf_path, "w") as f:
            f.write(config_content)
            
        logger.info(f"Generated Nginx config for {app_name}")
        self._reload_nginx()

    def _reload_nginx(self):
        try:
            container = self.client.containers.get("pypaas-nginx")
            container.exec_run("nginx -s reload")
            logger.success("Nginx reloaded successfully")
        except docker.errors.NotFound:
            logger.warning("Nginx container 'pypaas-nginx' not found. Is it running?")
        except Exception as e:
            logger.error(f"Failed to reload Nginx: {e}")