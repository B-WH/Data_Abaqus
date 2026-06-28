import os

from .errors import GeometryImportError, UnsupportedFormatError


STEP_EXTENSIONS = {".stp", ".step"}


def detect_input_format(path):
    extension = os.path.splitext(path)[1].lower()
    if extension in STEP_EXTENSIONS:
        return "step"
    if extension == ".ins":
        if _looks_like_step(path):
            return "step"
        raise UnsupportedFormatError(
            ".ins is not a reliable CAD exchange format here. This program only "
            "accepts .ins files whose content is recognizable as STEP/ISO-10303."
        )
    raise UnsupportedFormatError(
        "Unsupported input extension {!r}. Use .stp, .step, or STEP-like .ins.".format(
            extension or "<none>"
        )
    )


def _looks_like_step(path):
    try:
        with open(path, "rb") as handle:
            prefix = handle.read(4096).decode("latin-1", errors="ignore").upper()
    except OSError as exc:
        raise UnsupportedFormatError("Cannot read input file {!r}: {}".format(path, exc)) from exc
    return "ISO-10303" in prefix or "ISO-10303-21" in prefix


def import_geometry(gmsh, path, report):
    detect_input_format(path)
    if not os.path.isfile(path):
        raise GeometryImportError("Input file does not exist: {}".format(path))
    report.input_path = path
    try:
        gmsh.model.add("mesh_convert")
        imported = gmsh.model.occ.importShapes(path)
        try:
            gmsh.model.occ.healShapes(imported)
            report.add_diagnostic("Attempted OpenCASCADE shape healing.")
        except Exception as exc:
            report.add_warning("OpenCASCADE shape healing was skipped or failed: {}".format(exc))
        gmsh.model.occ.synchronize()
    except Exception as exc:
        raise GeometryImportError("Gmsh failed to import geometry: {}".format(exc)) from exc
