import sys

from .config import build_parser, config_from_args
from .errors import GmshUnavailableError, MeshConversionError
from .geometry_import import detect_input_format
from .inp_writer import write_inp
from .logging_utils import configure_logging
from .mesh_generator import convert
from .report import ConversionReport


_SENTINEL = object()


def main(argv=None, gmsh_module=_SENTINEL):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        config = config_from_args(args)
        logger = configure_logging(config.log_path)
        detect_input_format(config.input_path)
        gmsh = _load_gmsh(gmsh_module)
        mesh_data, report = convert(config, gmsh)
        write_inp(config.output_path, mesh_data)
        report.output_path = config.output_path
        if config.report_path:
            report.write_json(config.report_path)
        logger.info("Wrote Abaqus INP mesh to %s", config.output_path)
        if report.degraded:
            logger.warning("Mesh was degraded; see report/log for details.")
        return 0
    except MeshConversionError as exc:
        _write_error(exc)
        _write_failure_report_if_possible(argv, exc)
        return getattr(exc, "exit_code", 2)
    except SystemExit as exc:
        return _system_exit_status(exc.code)


def _system_exit_status(code: object | None) -> int:
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1


def _load_gmsh(gmsh_module):
    if gmsh_module is not _SENTINEL:
        if gmsh_module is None:
            raise GmshUnavailableError(
                "The gmsh Python package is required. Install it with: pip install gmsh"
            )
        return gmsh_module
    try:
        import gmsh  # type: ignore
    except ImportError as exc:
        raise GmshUnavailableError(
            "The gmsh Python package is required. Install it with: pip install gmsh"
        ) from exc
    return gmsh


def _write_error(exc):
    sys.stderr.write("mesh_convert: error: {}\n".format(exc))


def _write_failure_report_if_possible(argv, exc):
    if not argv:
        return
    parser = build_parser()
    try:
        args, _ = parser.parse_known_args(argv)
    except SystemExit:
        return
    report_path = getattr(args, "report_path", None)
    if not report_path:
        return
    report = ConversionReport(
        input_path=getattr(args, "input_path", None),
        output_path=getattr(args, "output_path", None),
        status="failed",
    )
    report.add_warning(str(exc))
    try:
        report.write_json(report_path)
    except OSError:
        pass
