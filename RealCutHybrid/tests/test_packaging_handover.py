import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"


class HandoverPackagingTests(unittest.TestCase):
    def test_smoke_check_precedes_hash_freeze_and_disables_bytecode(self):
        build_script = (PACKAGING / "build_handover.ps1").read_text(encoding="utf-8-sig")
        deploy_script = (PACKAGING / "deploy_env.bat").read_text(encoding="utf-8-sig")

        smoke = build_script.index('& (Join-Path $BinDir "realcut_hybrid.exe") check')
        hash_freeze = build_script.index(
            '$HashFile = Join-Path $PackageRoot "SHA256SUMS.txt"'
        )
        self.assertLess(smoke, hash_freeze)
        self.assertIn('PYTHONDONTWRITEBYTECODE = "1"', build_script)
        self.assertIn('PYTHONDONTWRITEBYTECODE=1', deploy_script)

    def test_runtime_optimizer_removes_editable_metadata_and_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            runtime = parent / "package" / "runtime" / "python"
            site_packages = runtime / "Lib" / "site-packages"
            editable_info = site_packages / "ai_edit_studio-0.1.0.dist-info"
            cache = site_packages / "keep_package" / "__pycache__"
            editable_info.mkdir(parents=True)
            cache.mkdir(parents=True)
            (editable_info / "direct_url.json").write_text("{}", encoding="utf-8")
            (site_packages / "__editable__.ai_edit_studio-0.1.0.pth").write_text(
                "local path", encoding="utf-8"
            )
            (site_packages / "__editable___ai_edit_studio_0_1_0_finder.py").write_text(
                "MAPPING = {}", encoding="utf-8"
            )
            (cache / "module.pyc").write_bytes(b"cache")
            keep = site_packages / "keep_package" / "module.py"
            keep.write_text("VALUE = 1", encoding="utf-8")

            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-File",
                    str(PACKAGING / "optimize_python_runtime.ps1"),
                    "-RuntimePath",
                    str(runtime),
                    "-AllowedParent",
                    str(parent / "package"),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(editable_info.exists())
            self.assertFalse(
                (site_packages / "__editable__.ai_edit_studio-0.1.0.pth").exists()
            )
            self.assertFalse(
                (
                    site_packages
                    / "__editable___ai_edit_studio_0_1_0_finder.py"
                ).exists()
            )
            self.assertFalse(cache.exists())
            self.assertTrue(keep.is_file())

    def test_external_runtime_never_writes_bytecode_when_launched_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime" / "python"
            library = runtime / "Lib"
            library.mkdir(parents=True)
            (library / "cache_probe.py").write_text("VALUE = 42\n", encoding="utf-8")
            runtime_deps = (
                ROOT / "vendor" / "experimental" / "scripts" / "_runtime_deps.py"
            )
            copied_runtime_deps = root / "_runtime_deps.py"
            copied_runtime_deps.write_bytes(runtime_deps.read_bytes())

            script = "\n".join(
                [
                    "import os, sys",
                    f"sys.path.insert(0, {str(root)!r})",
                    "sys.dont_write_bytecode = False",
                    "import _runtime_deps",
                    "_runtime_deps.configure_external_runtime()",
                    "import cache_probe",
                    "assert cache_probe.VALUE == 42",
                    "assert sys.dont_write_bytecode is True",
                    "assert os.environ['PYTHONDONTWRITEBYTECODE'] == '1'",
                ]
            )
            env = dict(os.environ)
            env["REALCUT_PYTHON_RUNTIME"] = str(runtime)
            env.pop("PYTHONDONTWRITEBYTECODE", None)
            completed = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse((library / "__pycache__").exists())

    def test_installer_verifier_accepts_valid_hashes_and_reports_unsigned_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            setup = output / "RealCutHybrid-test-Setup.exe"
            data = output / "RealCutHybrid-test-Setup-1.bin"
            setup.write_bytes(b"not-a-real-pe")
            data.write_bytes(b"payload")
            self._write_installer_manifest(output, [setup, data])

            completed = self._run_installer_verifier(output)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Verified 2 files", completed.stdout)
            self.assertIn("SmartScreen may warn", completed.stdout)
            self.assertNotIn("SignatureStatus Valid", completed.stdout)

    def test_installer_verifier_rejects_tampering_and_unlisted_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            setup = output / "RealCutHybrid-test-Setup.exe"
            setup.write_bytes(b"setup")
            self._write_installer_manifest(output, [setup])
            setup.write_bytes(b"tampered")

            tampered = self._run_installer_verifier(output)

            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("SHA-256 mismatch", tampered.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            setup = output / "RealCutHybrid-test-Setup.exe"
            setup.write_bytes(b"setup")
            self._write_installer_manifest(output, [setup])
            (output / "unlisted.bin").write_bytes(b"unexpected")

            unlisted = self._run_installer_verifier(output)

            self.assertNotEqual(unlisted.returncode, 0)
            self.assertIn("Unlisted file", unlisted.stderr)

    def test_installer_verifier_can_require_authenticode(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            setup = output / "RealCutHybrid-test-Setup.exe"
            setup.write_bytes(b"unsigned")
            self._write_installer_manifest(output, [setup])

            completed = self._run_installer_verifier(
                output, require_signature=True
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Authenticode signature is required", completed.stderr)

    def test_release_build_has_rotation_and_signing_guards(self):
        build_script = (PACKAGING / "build_handover.ps1").read_text(
            encoding="utf-8-sig"
        )
        setup_sign = build_script.index(
            "Invoke-CodeSigning $setupFiles[0].FullName $SigningCertificate"
        )
        installer_hash = build_script.index(
            '$installerHashFile = Join-Path $InstallerOutput "SHA256SUMS.txt"'
        )

        self.assertLess(setup_sign, installer_hash)
        self.assertIn("-ConfirmCredentialsRotated", build_script)
        self.assertIn("-RequireSignature:$Release", build_script)
        self.assertIn("REALCUT_SIGNING_CERT_THUMBPRINT", build_script)

        missing_rotation = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-File",
                str(PACKAGING / "build_handover.ps1"),
                "-Release",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertNotEqual(missing_rotation.returncode, 0)
        self.assertIn("rotate the previously exposed", missing_rotation.stderr)

    @staticmethod
    def _write_installer_manifest(directory: Path, files: list[Path]) -> None:
        lines = [
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
            for path in files
        ]
        (directory / "SHA256SUMS.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    @staticmethod
    def _run_installer_verifier(
        directory: Path, *, require_signature: bool = False
    ) -> subprocess.CompletedProcess[str]:
        command = [
            "pwsh",
            "-NoProfile",
            "-File",
            str(PACKAGING / "verify_installer.ps1"),
            "-InstallerDirectory",
            str(directory),
        ]
        if require_signature:
            command.append("-RequireSignature")
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
