from __future__ import annotations

import ast
from pathlib import Path

import git

from drift_agent.patch_generator.code_patch import apply_code_patch
from drift_agent.patch_generator.spec_patch import apply_spec_patches
from drift_agent.types import AgentFinding, PatchReport, PatchSpec


class PatchGenerator:
    def __init__(
        self,
        spec_path: str | Path,
        project_root: str | Path,
        output_dir: str | Path,
        patch_mode: str = "preview",
    ):
        self.spec_path = Path(spec_path)
        self.project_root = Path(project_root)
        self.output_dir = Path(output_dir)
        self.patch_mode = patch_mode
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, findings: list[AgentFinding]) -> PatchReport:
        spec_patches: list[PatchSpec] = []
        code_patches: list[PatchSpec] = []
        ambiguous: list[AgentFinding] = []
        files_written: list[str] = []
        errors: list[str] = []
        seen_locations: set[tuple[str, str]] = set()
        conflicts = 0
        for finding in findings:
            if finding.source_of_truth == "AMBIGUOUS" or finding.patch is None:
                ambiguous.append(finding)
                continue
            key = (finding.patch.target, finding.patch.location)
            if key in seen_locations:
                ambiguous.append(finding)
                conflicts += 1
                continue
            seen_locations.add(key)
            if finding.patch.target == "spec":
                spec_patches.append(finding.patch)
            else:
                code_patches.append(finding.patch)
        if spec_patches:
            spec_output = self.output_dir / "spec_patched.yaml"
            spec_output.write_text(apply_spec_patches(self.spec_path, spec_patches, errors), encoding="utf-8")
            files_written.append(str(spec_output))
        if code_patches:
            summary_path = self.output_dir / "code_patch_summary.md"
            summary_path.write_text(self._render_code_summary(code_patches), encoding="utf-8")
            files_written.append(str(summary_path))
            if self.patch_mode == "apply":
                applied_files = self._apply_code_patches(code_patches, errors)
                files_written.extend(applied_files)
        ambiguous_path = self.output_dir / "ambiguous.md"
        ambiguous_path.write_text(self._render_ambiguous(ambiguous), encoding="utf-8")
        files_written.append(str(ambiguous_path))
        return PatchReport(
            spec_patches_applied=len(spec_patches),
            code_patches_applied=len(code_patches) if self.patch_mode == "apply" else 0,
            ambiguous_count=len(ambiguous),
            patch_conflicts=conflicts,
            output_dir=str(self.output_dir),
            files_written=files_written,
            errors=errors,
        )

    def _apply_code_patches(self, code_patches: list[PatchSpec], errors: list[str]) -> list[str]:
        files_written: list[str] = []
        backups_dir = self.output_dir / "backups"
        backups_dir.mkdir(exist_ok=True)
        for patch in code_patches:
            file_path = self.project_root / patch.location.split("::", 1)[0]
            if not file_path.exists():
                errors.append(f"Code patch target not found: {file_path}")
                continue
            if self._has_uncommitted_changes(file_path):
                errors.append(f"Uncommitted changes detected in {file_path}; patch skipped")
                continue
            backup_path = backups_dir / file_path.name
            original = file_path.read_text(encoding="utf-8")
            backup_path.write_text(original, encoding="utf-8")
            updated = apply_code_patch(original, patch)
            try:
                ast.parse(updated)
            except SyntaxError:
                errors.append(f"Patched file became invalid Python: {file_path}")
                file_path.write_text(original, encoding="utf-8")
                continue
            file_path.write_text(updated, encoding="utf-8")
            files_written.append(str(file_path))
        return files_written

    def _has_uncommitted_changes(self, file_path: Path) -> bool:
        try:
            repo = git.Repo(self.project_root, search_parent_directories=True)
        except git.InvalidGitRepositoryError:
            return False
        return bool(repo.index.diff(None, paths=[str(file_path.relative_to(repo.working_tree_dir))]))

    def _render_code_summary(self, code_patches: list[PatchSpec]) -> str:
        lines = ["# Code Patch Summary", ""]
        for patch in code_patches:
            lines.extend(
                [
                    f"- `{patch.location}`",
                    f"  - patch type: `{patch.patch_type}`",
                    f"  - content: `{patch.content.strip()}`",
                ]
            )
        return "\n".join(lines) + "\n"

    def _render_ambiguous(self, ambiguous: list[AgentFinding]) -> str:
        lines = ["# Ambiguous Drift Items - Manual Review Required", ""]
        for index, finding in enumerate(ambiguous, start=1):
            lines.extend(
                [
                    f"## {index}. {finding.drift_item.endpoint} - {finding.drift_item.category.value}",
                    "",
                    f"**Location:** {finding.drift_item.location}",
                    f"**Spec evidence:** {finding.drift_item.spec_evidence or '(absent)'}",
                    f"**Code evidence:** {finding.drift_item.code_evidence or '(absent)'}",
                    f"**Why ambiguous:** {finding.reasoning}",
                    "",
                    "---",
                    "",
                ]
            )
        return "\n".join(lines)
