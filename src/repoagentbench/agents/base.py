from abc import ABC, abstractmethod
from pathlib import Path


class Agent(ABC):
    name: str

    @abstractmethod
    def run(
        self,
        workdir: Path,
        goal: str,
        task_path: Path,
        log_path: Path,
    ) -> dict:
        ...
