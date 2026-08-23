"""让 `python -m ari` 可用，无需先安装 console script。"""

from .cli import app

if __name__ == "__main__":
    app()
