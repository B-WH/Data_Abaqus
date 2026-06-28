class MeshConversionError(RuntimeError):
    """Base class for conversion failures that should be shown to users."""

    exit_code = 2


class UnsupportedFormatError(MeshConversionError):
    """Raised when the input format cannot be recognized reliably."""


class GmshUnavailableError(MeshConversionError):
    """Raised when the gmsh Python package is not available."""

    exit_code = 3


class GeometryImportError(MeshConversionError):
    """Raised when Gmsh cannot import or classify geometry."""


class MeshGenerationError(MeshConversionError):
    """Raised when the generated mesh violates the requested policy."""
