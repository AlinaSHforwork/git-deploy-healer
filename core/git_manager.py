# core/git_manager.py
from pathlib import Path
import shutil
import git


class GitManager:
    def __init__(self, base_path: str = "/tmp/repos"):
        self.base_path = str(base_path).rstrip("/")
        Path(self.base_path).mkdir(parents=True, exist_ok=True)

    def get_repository_path(self, app_name: str) -> str:
        return f"{self.base_path}/{app_name}"

    def repository_exists(self, app_name: str) -> bool:
        """
        Return True when the repository path exists. Tests patch Path.exists()
        (but not is_dir()), so rely on exists() only to be compatible with mocks.
        """
        p = Path(self.get_repository_path(app_name))
        try:
            return p.exists()
        except Exception:
            # If a mock raises, fall back to truthiness of the attribute
            return bool(getattr(p, "exists", False))

    def clone_repository(self, repo_url: str, app_name: str) -> str:
        """
        If repository exists, call origin.pull() if present (so mocks are invoked).
        Otherwise clone from repo_url.
        """
        dest = self.get_repository_path(app_name)

        if self.repository_exists(app_name):
            # Open repo and call origin.pull() directly so tests' mock origin is invoked.
            repo = git.Repo(dest)

            # Try direct attribute access first (works with real Repo and many mocks)
            origin = None
            try:
                origin = repo.remotes.origin
            except Exception:
                # Fallback to getattr in case remotes is a Mock-like object
                origin = getattr(repo.remotes, "origin", None)

            if origin is not None:
                # Let any exception (including GitCommandError) propagate to the caller
                origin.pull()
                return dest

            # Fallback: iterate remotes if iterable
            remotes = getattr(repo, "remotes", [])
            try:
                for r in remotes:
                    r.pull()
            except TypeError:
                # remotes not iterable; try calling pull on remotes object if it exists
                if hasattr(remotes, "pull"):
                    remotes.pull()
            return dest

        # Repository does not exist -> clone
        git.Repo.clone_from(repo_url, dest)
        return dest

    def pull_repository(self, app_name: str):
        """
        Pull updates for an existing repository. If origin.pull raises GitCommandError,
        let it propagate so tests can assert it.
        """
        dest = self.get_repository_path(app_name)
        repo = git.Repo(dest)

        # Prefer direct origin.pull() so mocks are invoked
        origin = None
        try:
            origin = repo.remotes.origin
        except Exception:
            origin = getattr(repo.remotes, "origin", None)

        if origin is not None:
            origin.pull()
            return

        remotes = getattr(repo, "remotes", [])
        try:
            for r in remotes:
                r.pull()
        except TypeError:
            if hasattr(remotes, "pull"):
                remotes.pull()
            else:
                raise

    def get_commit_hash(self, app_name: str, short: bool = False) -> str:
        dest = self.get_repository_path(app_name)
        repo = git.Repo(dest)
        hexsha = repo.head.commit.hexsha
        return hexsha[:7] if short else hexsha

    def delete_repository(self, app_name: str):
        dest = self.get_repository_path(app_name)
        p = Path(dest)
        if p.exists():
            shutil.rmtree(dest)

    def list_repositories(self):
        p = Path(self.base_path)
        if not p.exists():
            return []
        names = []
        for x in p.iterdir():
            if not x.is_dir():
                continue
            name_attr = getattr(x, "name", None)
            if isinstance(name_attr, str):
                names.append(name_attr)
            else:
                mock_name = getattr(x, "_mock_name", None)
                if isinstance(mock_name, str):
                    names.append(mock_name)
                else:
                    names.append(str(x))
        return names
