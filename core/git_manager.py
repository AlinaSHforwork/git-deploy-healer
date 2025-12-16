import os
import git
from loguru import logger

class GitManager:
    def __init__(self, root_dir: str = "./repos"):
        self.root_dir = root_dir
        if not os.path.exists(self.root_dir):
            os.makedirs(self.root_dir)

    def update_repo(self, name: str, clone_url: str) -> str:
        """
        Clones or pulls the repository. Returns the local path.
        """
        repo_path = os.path.join(self.root_dir, name)

        if os.path.exists(repo_path):
            logger.info(f"Repository {name} exists. Pulling changes...")
            try:
                repo = git.Repo(repo_path)
                origin = repo.remotes.origin
                origin.pull()
                return repo_path
            except git.Exc as e:
                logger.error(f"Failed to pull repo: {e}")
                raise e
        else:
            logger.info(f"Cloning {name} from {clone_url}...")
            try:
                git.Repo.clone_from(clone_url, repo_path)
                return repo_path
            except git.Exc as e:
                logger.error(f"Failed to clone repo: {e}")
                raise e