from __future__ import annotations

from pipeline.judge import _parse_findings


def test_parse_findings_accepts_stray_text_around_json():
    findings = _parse_findings(
        """
        Here is the report:
        {"findings":[{"category":"missing_group","severity":"medium","block_id":"b1","description":"Block b1 and b2 should share a group_id.","suggested_fix":null}]}
        Done.
        """
    )

    assert len(findings) == 1
    assert findings[0].category == "missing_group"
    assert findings[0].block_id == "b1"


def test_parse_findings_repairs_bare_keys_and_trailing_commas():
    findings = _parse_findings(
        """
        {
          findings: [
            {
              category: "missing_plot",
              severity: "high",
              block_id: "b1",
              description: "Block b1 describes a surface but has no surface3d plot.",
              suggested_fix: null,
            },
          ],
        }
        """
    )

    assert len(findings) == 1
    assert findings[0].category == "missing_plot"


def test_parse_findings_drops_self_contradictory_false_positive():
    findings = _parse_findings(
        """
        {
          "findings": [
            {
              "category": "factual_error",
              "severity": "high",
              "block_id": "b1",
              "description": "The block is actually correct, so this is not an issue.",
              "suggested_fix": "No fix needed."
            },
            {
              "category": "missing_plot",
              "severity": "high",
              "block_id": "b2",
              "description": "Block b2 describes a specific surface but has no accompanying plot.",
              "suggested_fix": "Add a surface3d plot for the named example."
            }
          ]
        }
        """
    )

    assert len(findings) == 1
    assert findings[0].category == "missing_plot"
    assert findings[0].block_id == "b2"
