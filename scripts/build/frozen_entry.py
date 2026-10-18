"""PyInstaller entry point; one executable serves UI, CLI, MCP and job workers."""
import multiprocessing
import runpy
import sys

from dataforge.launcher import application_root, default_home, main, windows_instance


def dispatch():
    multiprocessing.freeze_support()
    if sys.argv[1:2] == ['--render-graph-image']:
        from dataforge.image_worker import main as render_image
        render_image()
    elif sys.argv[1:2] == ["--worker"]:
        sys.argv = ["dataforge.agent.worker", *sys.argv[2:]]
        runpy.run_module("dataforge.agent.worker", run_name="__main__")
    elif sys.argv[1:2] == ["--cli"]:
        import os

        os.environ.setdefault("DATAFORGE_HOME", str(default_home(source=False)))
        sys.path.insert(0, str(application_root()))
        from dataforge.cli import app

        sys.argv = ["gravetrail", *sys.argv[2:]]
        app()
    else:
        main()


if __name__ == "__main__":
    with windows_instance():
        dispatch()
