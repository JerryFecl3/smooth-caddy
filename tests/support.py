"""Platform-neutral test utilities; deliberately avoid importing UI classes."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


async def wait_until(predicate, *, description, timeout=10):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.01)
    try:
        await asyncio.wait_for(poll(), timeout)
    except asyncio.TimeoutError as error:
        raise AssertionError(f'Timed out after {timeout}s waiting for {description}') from error


async def wait_for_screen(ui, screen_type, *, controls=(), caption=None):
    def ready():
        screen = ui.screen
        return (isinstance(screen, screen_type) and screen.is_mounted
                and (caption is None or screen.caption == caption)
                and all(any(widget.is_mounted for widget in screen.query(selector))
                        for selector in controls))
    await wait_until(ready, description=f'{screen_type.__name__} mounted with {controls}, caption={caption!r}')
    return ui.screen


def process_output(result):
    def text(value):
        return value.decode('utf-8', errors='backslashreplace') if isinstance(value, bytes) else value or ''
    return f'stdout:\n{text(result.stdout)}\nstderr:\n{text(result.stderr)}'


def run_python(*args, env=None, timeout=60):
    environment = dict(os.environ)
    if env is not None:
        environment.update(env)
    environment.update(PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    command = [sys.executable, *args]
    try:
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
                                text=True, encoding='utf-8', errors='backslashreplace', timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise AssertionError(f'Python subprocess timed out after {timeout}s\n{process_output(error)}') from error
    if result.returncode:
        raise AssertionError(f'Python subprocess exited with {result.returncode}\n{process_output(result)}')
    return result
