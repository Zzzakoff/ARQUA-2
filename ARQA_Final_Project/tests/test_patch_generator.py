from pathlib import Path

from drift_agent.patch_generator import PatchGenerator
from drift_agent.patch_generator.spec_patch import apply_spec_patches
from drift_agent.types import AgentFinding, DriftCategory, DriftItem, PatchSpec


def _finding(tmp_path: Path) -> AgentFinding:
    return AgentFinding(
        drift_item=DriftItem(
            id="abc123",
            endpoint="GET /users",
            category=DriftCategory.ADDITIVE_DRIFT,
            location="response.200.schema.created_at",
            detail="Created at is undocumented",
            spec_evidence=None,
            code_evidence="string/date-time",
            severity="warning",
        ),
        source_of_truth="CODE",
        confidence="high",
        reasoning="Code includes a stable timestamp field and the spec should be updated.",
        evidence=[],
        patch=PatchSpec(
            target="spec",
            patch_type="add_field",
            location="components/schemas/UserResponse/properties",
            content="created_at:\n  type: string\n  format: date-time\n",
        ),
    )


def test_patch_generator_preview(tmp_path: Path):
    spec_path = tmp_path / "openapi.yaml"
    spec_path.write_text(
        "\n".join(
            [
                'openapi: "3.0.3"',
                "info:",
                "  title: Test",
                '  version: "1.0.0"',
                "components:",
                "  schemas:",
                "    UserResponse:",
                "      type: object",
                "      properties:",
                "        id:",
                "          type: integer",
            ]
        ),
        encoding="utf-8",
    )
    report = PatchGenerator(spec_path=spec_path, project_root=tmp_path, output_dir=tmp_path / "patches").generate([_finding(tmp_path)])

    assert report.spec_patches_applied == 1
    assert (tmp_path / "patches" / "spec_patched.yaml").exists()
    assert (tmp_path / "patches" / "ambiguous.md").exists()


def test_spec_patch_accepts_openapi_path_location(tmp_path: Path):
    spec_path = tmp_path / "openapi.yaml"
    spec_path.write_text(
        "\n".join(
            [
                'openapi: "3.0.3"',
                "info:",
                "  title: Test",
                '  version: "1.0.0"',
                "paths:",
                "  /api/users/{user_id}:",
                "    get:",
                "      responses:",
                '        "200":',
                "          description: OK",
            ]
        ),
        encoding="utf-8",
    )

    patched = apply_spec_patches(
        spec_path,
        [
            PatchSpec(
                target="spec",
                patch_type="add_field",
                location="/api/users/{user_id}/get/responses/200",
                content="content:\n  application/json:\n    schema:\n      type: object\n",
            )
        ],
    )

    assert "application/json" in patched


def test_spec_patch_accepts_paths_prefix_with_openapi_path(tmp_path: Path):
    spec_path = tmp_path / "openapi.yaml"
    spec_path.write_text(
        "\n".join(
            [
                'openapi: "3.0.3"',
                "info:",
                "  title: Test",
                '  version: "1.0.0"',
                "paths:",
                "  /api/orders:",
                "    get:",
                "      parameters:",
                "        - name: limit",
                "          in: query",
                "          schema:",
                "            type: string",
            ]
        ),
        encoding="utf-8",
    )

    patched = apply_spec_patches(
        spec_path,
        [
            PatchSpec(
                target="spec",
                patch_type="change_type",
                location="paths//api/orders/get/parameters/0/schema/type",
                content="integer\n",
            )
        ],
    )

    assert "type: integer" in patched


def test_spec_patch_accepts_singular_path_prefix(tmp_path: Path):
    spec_path = tmp_path / "openapi.yaml"
    spec_path.write_text(
        "\n".join(
            [
                'openapi: "3.0.3"',
                "info:",
                "  title: Test",
                '  version: "1.0.0"',
                "paths:",
                "  /api/orders:",
                "    get:",
                "      responses:",
                '        "200":',
                "          description: OK",
            ]
        ),
        encoding="utf-8",
    )

    patched = apply_spec_patches(
        spec_path,
        [
            PatchSpec(
                target="spec",
                patch_type="add_field",
                location="path//api/orders/get/responses/200",
                content="content:\n  application/json:\n    schema:\n      type: array\n",
            )
        ],
    )

    assert "type: array" in patched


def test_spec_patch_can_collect_bad_location_errors(tmp_path: Path):
    spec_path = tmp_path / "openapi.yaml"
    spec_path.write_text('openapi: "3.0.3"\ninfo:\n  title: Test\n  version: "1.0.0"\npaths: {}\n', encoding="utf-8")
    errors: list[str] = []

    patched = apply_spec_patches(
        spec_path,
        [PatchSpec(target="spec", patch_type="change_type", location="missing/path/type", content="integer\n")],
        errors,
    )

    assert 'openapi: "3.0.3"' in patched
    assert errors

