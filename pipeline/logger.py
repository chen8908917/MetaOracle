import os
from typing import Optional


def log_message(message: str, log_file: Optional[str] = None) -> None:
    print(message)
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(message + "\n")
