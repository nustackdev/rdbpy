"""
Setup script for rdbpy package.

This setup.py handles:
- Cython compilation for the rdbpy package, which provides Python bindings to RocksDB

Package structure:
    src/
    └── rdbpy/     (Cython + C++ - RocksDB bindings)

Build environments:
    - Local development: May or may not have RocksDB installed
    - CI/CD (cibuildwheel): RocksDB built by scripts/build-rocksdb-*.sh
    - Source distribution: Users must have RocksDB installed

Environment variables:
    RDBPY_DEP_DIR: Path to RocksDB and compression libraries (set by build scripts)
"""

import os
import platform
import sys
from pathlib import Path

from setuptools import Extension, setup


# ============================================================================
# Configuration
# ============================================================================
# Detect platform
SYSTEM = platform.system()
IS_LINUX = SYSTEM == "Linux"
IS_MACOS = SYSTEM == "Darwin"
IS_WINDOWS = SYSTEM == "Windows"

# Config for rdbpy
RDBPY_PATH = Path("src/rdbpy")
HAS_RDBPY = RDBPY_PATH.exists() and list(RDBPY_PATH.glob("*.pyx"))

# Get dependency directory from environment (set by build scripts)
DEP_DIR = os.environ.get("RDBPY_DEP_DIR", None)


# ============================================================================
# Helper Functions
# ============================================================================


def find_cython_files(package_path: Path) -> list[Path]:
    """Find all .pyx files in a package directory."""
    return sorted(package_path.rglob("*.pyx"))


def get_include_dirs() -> list[str]:
    """Get include directories for compilation."""
    include_dirs = [
        "src/rdbpy/include",  # Our C++ wrapper headers
    ]

    if DEP_DIR:
        include_dirs.append(f"{DEP_DIR}/include")

    # Platform-specific defaults if DEP_DIR not set
    if not DEP_DIR:
        if IS_LINUX:
            include_dirs.extend(
                [
                    "/usr/include",
                    "/usr/local/include",
                ]
            )
        elif IS_MACOS:
            include_dirs.extend(
                [
                    "/opt/homebrew/include",  # Apple Silicon
                    "/usr/local/include",  # Intel Mac
                ]
            )
        elif IS_WINDOWS:
            vcpkg_path = Path("C:/vcpkg/installed/x64-windows/include")
            if vcpkg_path.exists():
                include_dirs.append(str(vcpkg_path))

    return include_dirs


def get_library_dirs() -> list[str]:
    """Get library directories for linking."""
    library_dirs = []

    if DEP_DIR:
        library_dirs.append(f"{DEP_DIR}/lib")

    # Platform-specific defaults if DEP_DIR not set
    if not DEP_DIR:
        if IS_LINUX:
            library_dirs.extend(
                [
                    "/usr/lib",
                    "/usr/lib64",
                    "/usr/local/lib",
                    "/usr/local/lib64",
                ]
            )
        elif IS_MACOS:
            library_dirs.extend(
                [
                    "/opt/homebrew/lib",  # Apple Silicon
                    "/usr/local/lib",  # Intel Mac
                ]
            )
        elif IS_WINDOWS:
            vcpkg_path = Path("C:/vcpkg/installed/x64-windows/lib")
            if vcpkg_path.exists():
                library_dirs.append(str(vcpkg_path))

    return library_dirs


def get_libraries() -> list[str]:
    """Get libraries to link against."""
    # RocksDB and its compression dependencies
    libraries = [
        "rocksdb",
        "snappy",
        "lz4",
        "zstd",
        "z",
        "bz2",
    ]

    # Platform-specific additions
    if IS_LINUX:
        libraries.extend(
            [
                "pthread",
                "rt",
                "dl",
            ]
        )
    elif IS_MACOS:
        # macOS doesn't need explicit pthread/dl
        pass
    elif IS_WINDOWS:
        libraries.extend(
            [
                "Shlwapi",  # For path operations
            ]
        )

    return libraries


def get_compile_args() -> list[str]:
    """Get compiler arguments."""
    if IS_WINDOWS:
        return [
            "/std:c++17",
            "/O2",
            "/EHsc",  # Exception handling
        ]
    else:
        # Unix-like systems (Linux, macOS)
        args = [
            "-std=c++17",
            "-O3",
            "-Wall",
            "-Wno-unused-function",
            "-fPIC",
        ]

        if IS_MACOS:
            # macOS-specific flags
            args.extend(
                [
                    "-stdlib=libc++",
                    f"-mmacosx-version-min={os.environ.get('MACOSX_DEPLOYMENT_TARGET', '10.14')}",
                ]
            )

        return args


def get_link_args() -> list[str]:
    """Get linker arguments."""
    if IS_WINDOWS:
        return []

    args = []

    if IS_MACOS:
        args.extend(
            [
                "-stdlib=libc++",
                f"-mmacosx-version-min={os.environ.get('MACOSX_DEPLOYMENT_TARGET', '10.14')}",
            ]
        )

        # Add rpath for bundled libraries
        if DEP_DIR:
            args.extend(
                [
                    f"-Wl,-rpath,{DEP_DIR}/lib",
                    "-Wl,-rpath,@loader_path",
                ]
            )
    elif IS_LINUX:
        # Force linking of all specified libraries
        args.append("-Wl,--no-as-needed")

        # Add rpath for bundled libraries
        if DEP_DIR:
            args.extend(
                [
                    f"-Wl,-rpath,{DEP_DIR}/lib",
                    "-Wl,-rpath,$ORIGIN",
                ]
            )

    return args


# ============================================================================
# Extension Building
# ============================================================================


def create_rocksdb_extensions() -> list[Extension]:
    """Create Extension objects for rdbpy Cython files."""
    if not HAS_RDBPY:
        print("No rdbpy package found or no .pyx files - skipping Cython compilation")
        return []

    print("=" * 80)
    print("Building rdbpy RocksDB bindings")
    print("=" * 80)

    # Check if Cython is available
    try:
        from Cython.Build import cythonize
    except ImportError:
        print("ERROR: Cython not found!")
        print("   Install it with: pip install Cython>=3.0")
        sys.exit(1)

    # Find all .pyx files in rdbpy
    pyx_files = find_cython_files(RDBPY_PATH)

    if not pyx_files:
        print("No .pyx files found in rdbpy")
        return []

    print(f"📦 Found {len(pyx_files)} Cython file(s):")
    for pyx in pyx_files:
        print(f"   - {pyx}")

    # Configuration
    include_dirs = get_include_dirs()
    library_dirs = get_library_dirs()
    libraries = get_libraries()
    compile_args = get_compile_args()
    link_args = get_link_args()

    print("\n🔧 Build configuration:")
    print(f"   Platform: {SYSTEM}")
    print(f"   Dependency dir: {DEP_DIR or 'Not set (using system libraries)'}")
    print(f"   Include dirs: {len(include_dirs)} paths")
    print(f"   Library dirs: {len(library_dirs)} paths")
    print(f"   Libraries: {', '.join(libraries)}")

    # Create extensions
    extensions = []

    for pyx_file in pyx_files:
        # Convert path to module name
        # e.g., src/rdbpy/lib_rocksdb.pyx -> rdbpy.lib_rocksdb
        rel_path = pyx_file.relative_to("src")
        module_parts = [*list(rel_path.parts[:-1]), rel_path.stem]
        module_name = ".".join(module_parts)

        print(f"\n   Creating extension: {module_name}")

        ext = Extension(
            name=module_name,
            sources=[str(pyx_file)],
            include_dirs=include_dirs,
            library_dirs=library_dirs,
            libraries=libraries,
            language="c++",
            extra_compile_args=compile_args,
            extra_link_args=link_args,
        )
        extensions.append(ext)

    # Cythonize
    print(f"\n🔨 Cythonizing {len(extensions)} extension(s)...")

    cythonized = cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "embedsignature": True,
            "boundscheck": False,
            "wraparound": False,
            "initializedcheck": False,
            "nonecheck": False,
        },
        annotate=False,
    )

    print(f"Successfully created {len(cythonized)} extension(s)")
    print("=" * 80)

    return cythonized


# ============================================================================
# Main Setup
# ============================================================================


def main() -> None:
    """Main setup function."""
    # Get extensions
    extensions = create_rocksdb_extensions()

    # Check if we're building wheels or installing
    if "bdist_wheel" in sys.argv or "build" in sys.argv or "install" in sys.argv:
        if extensions and not DEP_DIR:
            print("\n" + "=" * 80)
            print("WARNING: Building without RDBPY_DEP_DIR set!")
            print("=" * 80)
            print("This may fail if RocksDB is not installed system-wide.")
            print("For CI/CD builds, ensure build-rocksdb-*.sh scripts run first.")
            print("For local development, install RocksDB:")
            if IS_LINUX:
                print("  - Ubuntu/Debian: sudo apt-get install librocksdb-dev")
                print("  - Fedora/RHEL: sudo dnf install rocksdb-devel")
            elif IS_MACOS:
                print("  - Homebrew: brew install rocksdb")
            elif IS_WINDOWS:
                print("  - vcpkg: vcpkg install rocksdb:x64-windows")
            print("=" * 80 + "\n")

    # Run setup
    setup(
        ext_modules=extensions,
    )

    if extensions:
        print("\nBuild completed successfully!")
        print("   rdbpy RocksDB bindings are ready to use.")
    else:
        print("\nBuild completed (pure Python packages only)")


if __name__ == "__main__":
    main()
