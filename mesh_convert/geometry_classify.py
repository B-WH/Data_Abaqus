from dataclasses import dataclass

from .config import DimMode
from .errors import GeometryImportError


@dataclass
class GeometryInfo:
    dim: DimMode
    volumes: list[tuple[int, int]]
    surfaces: list[tuple[int, int]]
    curves: list[tuple[int, int]]


def classify_geometry(gmsh, requested_dim, report):
    volumes = list(gmsh.model.getEntities(3))
    surfaces = list(gmsh.model.getEntities(2))
    curves = list(gmsh.model.getEntities(1))

    report.add_diagnostic(
        "Geometry entities: {} volumes, {} surfaces, {} curves.".format(
            len(volumes), len(surfaces), len(curves)
        )
    )

    if requested_dim == DimMode.AUTO:
        if volumes:
            dim = DimMode.THREE_D
        elif surfaces:
            dim = DimMode.TWO_D
        else:
            raise GeometryImportError("No surfaces or volumes were found in the geometry.")
    elif requested_dim == DimMode.THREE_D:
        if not volumes:
            raise GeometryImportError("3D mode was requested, but no solid volumes were found.")
        dim = DimMode.THREE_D
    else:
        if not surfaces:
            raise GeometryImportError("2D mode was requested, but no surface faces were found.")
        dim = DimMode.TWO_D

    if dim == DimMode.TWO_D and volumes:
        report.add_warning("2D mode will mesh surfaces even though solid volumes are present.")
    if dim == DimMode.THREE_D:
        _diagnose_volume_boundaries(gmsh, volumes, report)
    else:
        _diagnose_surface_boundaries(gmsh, surfaces, report)
    report.dim = dim.value
    return GeometryInfo(dim=dim, volumes=volumes, surfaces=surfaces, curves=curves)


def _diagnose_volume_boundaries(gmsh, volumes, report):
    try:
        boundaries = gmsh.model.getBoundary(volumes, oriented=False, recursive=False)
    except Exception as exc:
        report.add_warning("Could not inspect volume boundaries: {}".format(exc))
        return
    if not boundaries:
        report.add_warning("Solid volume boundary inspection returned no faces.")


def _diagnose_surface_boundaries(gmsh, surfaces, report):
    try:
        boundaries = gmsh.model.getBoundary(surfaces, oriented=False, recursive=False)
    except Exception as exc:
        report.add_warning("Could not inspect surface boundaries: {}".format(exc))
        return
    if not boundaries:
        report.add_warning("Surface boundary inspection returned no edges; geometry may be closed or degenerate.")
