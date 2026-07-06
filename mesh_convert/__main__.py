import sys

from .cli import main as cli_main


def main(argv=None, cli_runner=cli_main, gui_runner=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        return cli_runner(argv)
    if gui_runner is None:
        from .gui import run as gui_runner

    return gui_runner()


if __name__ == "__main__":
    raise SystemExit(main())
