"""Readmit exact sources and start the original addon inside an owned FreeCAD GUI.

Original external handlers retain MIT © 2025 Shirokuma (k tanaka), with
Apache-2.0 Qwen additions. No stock launcher or user Mod installation runs.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys


def native_identity(app, gui, session: dict) -> dict:
    """Read documents, active state and selection on the actual native GUI thread."""
    active = app.ActiveDocument
    return {"pid": os.getpid(), "binary": str(Path(sys.executable).resolve()),
            "session": session["session"], "port": session["port"],
            "data": str(Path(app.getUserAppDataDir()).resolve()),
            "documents": sorted(app.listDocuments()), "active": active.Name if active else None,
            "document_path": active.FileName if active else "",
            "selection": sorted({item.DocumentName for item in gui.Selection.getSelectionEx()})}


def configure_native(app, gui, session: dict) -> None:
    """Bind native settings and FEM executables to existing owned paths."""
    if Path(app.getUserAppDataDir()).resolve() != Path(session["data"]).resolve():
        raise ValueError("FreeCAD user data is not the owned preexisting directory")
    if Path(sys.executable).resolve() != Path(session["binary"]).resolve():
        raise ValueError("Actual native interpreter differs from the selected direct binary")
    fem = "User parameter:BaseApp/Preferences/Mod/Fem/"
    app.ParamGet(fem + "Ccx").SetString("ccxBinaryPath", session["solvers"]["ccx"]["path"])
    app.ParamGet(fem + "Ccx").SetInt("AnalysisNumCPUs", 2)
    gmsh = app.ParamGet(fem + "Gmsh")
    gmsh.SetString("gmshBinaryPath", session["solvers"]["gmsh"]["path"])
    gmsh.SetInt("NumOfThreads", 1)
    general = app.ParamGet(fem + "General")
    general.SetBool("OverwriteSolverWorkingDirectory", False)
    general.SetBool("UseCustomDirectory", True)
    general.SetBool("UseTempDirectory", False)
    general.SetBool("UseBesideDirectory", False)
    general.SetString("CustomDirectoryPath", str(Path(session["output"]) / "cwd"))
    gui.activateWorkbench("PartWorkbench")


def bind_fem_working_directory(ccxtools, session: dict) -> None:
    """Keep installed run()'s directory reset bound to the original reported directory."""
    root = Path(session["output"]).resolve()
    original = ccxtools.FemToolsCcx

    class OwnedSolver(original):
        def setup_working_dir(self, param_working_dir=None, create=False):
            """Admit the selected working path before native setup and retain its lineage."""
            requested = param_working_dir or self.solver.WorkingDir
            if requested and not Path(requested).resolve().is_relative_to(root):
                raise ValueError("Solver working directory must be owned")
            super().setup_working_dir(param_working_dir, create)
            if not Path(self.working_dir).resolve().is_relative_to(root):
                raise ValueError("Actual solver working directory must be owned")
            self.solver.WorkingDir = self.working_dir

    ccxtools.FemToolsCcx = OwnedSolver


def install_owned_rpc(rpc, dispatch, parts, app, gui, session: dict, jobs):
    """Extend identity/jobs and kill the native process on uncancelled GUI timeout."""
    from freecad_jobs import DEADLINE, write_receipt

    original_dispatch = dispatch.dispatch_to_gui

    def bounded_dispatch(task, timeout=DEADLINE):
        result = original_dispatch(task, timeout=min(timeout, DEADLINE))
        if isinstance(result, dict) and "timed out" in str(result.get("error", "")).lower():
            write_receipt(Path(session["output"]) / "native-failure.json",
                          {"session": session["session"], "state": "timed_out", "error": result["error"]})
            os._exit(124)
        return result

    rpc.dispatch_to_gui = bounded_dispatch
    rpc.FreeCADRPC.TIMEOUT = rpc.FreeCADRPC.EXECUTE_CODE_TIMEOUT = DEADLINE

    class OwnedRPC(rpc.FreeCADRPC):
        """Add owned state evidence and completion without changing upstream bytes."""

        def vrm_identity(self):
            """Prove GUI readiness and read native session/document state."""
            result = bounded_dispatch(lambda: native_identity(app, gui, session))
            if not isinstance(result, dict) or "pid" not in result:
                raise RuntimeError(f"Native GUI identity failed: {result}")
            return result

        def vrm_start_job(self, code):
            """Queue trusted background-safe code under the one-job completion contract."""
            return jobs.start(code)

        def get_parts_list(self):
            """Invalidate the stock successful-list cache before each actual library read."""
            parts.get_parts_list.cache_clear()
            return super().get_parts_list()

    rpc.FreeCADRPC = OwnedRPC
    rpc.start_rpc_server(session["port"])
    address = rpc.rpc_server_instance.server_address
    if address != ("127.0.0.1", session["port"]):
        raise ValueError("Native listener is outside the owned loopback endpoint")
    return rpc.rpc_server_instance


def main() -> None:
    """Readmit all selected bytes before addon imports and write actual readiness."""
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from freecad_session import admit_native, admit_sources
    from freecad_jobs import NativeJobs, write_receipt

    session = json.loads(Path(os.environ["VRM_FREECAD_SESSION_FILE"]).read_text())
    data = admit_sources(Path(session["source_root"]), Path(session["manifest"]),
                         session["manifest_sha256"])
    admit_native(data, Path(session["binary"]), session["binary_sha256"])
    import FreeCAD as app
    import FreeCADGui as gui

    configure_native(app, gui, session)
    from femtools import ccxtools

    bind_fem_working_directory(ccxtools, session)
    root = Path(session["source_root"])
    addon = root / "src/capabilities/freecad/qwen_mm_plugins_freecad/vendor/FreeCADMCP"
    sys.path.insert(0, str(addon))
    rpc = importlib.import_module("rpc_server.rpc_server")
    dispatch = importlib.import_module("rpc_server.gui_dispatch")
    parts = importlib.import_module("rpc_server.parts_library")
    jobs = NativeJobs(session, vars(rpc))
    install_owned_rpc(rpc, dispatch, parts, app, gui, session, jobs)
    gui.getMainWindow().destroyed.connect(lambda: jobs.close())
    write_receipt(Path(session["output"]) / "ready.json", native_identity(app, gui, session))


if __name__ == "__main__":
    main()
