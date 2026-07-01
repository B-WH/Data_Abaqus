try:
    from .launcher import main
except ImportError:
    from odb_extract.launcher import main


if __name__ == "__main__":
    raise SystemExit(main())
