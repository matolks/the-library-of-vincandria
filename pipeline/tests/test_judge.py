from __future__ import annotations

import pytest

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


def test_parse_findings_accepts_python_literal_dict_output():
    findings = _parse_findings(
        """
        {'findings': [
          {
            'category': 'generic_prose',
            'severity': 'low',
            'block_id': 'b1',
            'description': 'Block b1 is boilerplate and can be deleted without losing content.',
            'suggested_fix': None,
          }
        ]}
        """
    )

    assert len(findings) == 1
    assert findings[0].category == "generic_prose"
    assert findings[0].suggested_fix is None


def test_parse_findings_repairs_unescaped_latex_backslashes_in_strings():
    findings = _parse_findings(
        r'''
        {
          "findings": [
            {
              "category": "factual_error",
              "severity": "high",
              "block_id": "b1",
              "description": "The block writes A \subseteq B but the source says A \not\subseteq B.",
              "suggested_fix": "Change the relation to A \not\subseteq B."
            }
          ]
        }
        '''
    )

    assert len(findings) == 1
    assert findings[0].category == "factual_error"
    assert r"\not\subseteq" in findings[0].description


def test_parse_findings_uses_first_balanced_object_before_trailing_text():
    findings = _parse_findings(
        """
        {"findings":[{"category":"broken_plot_spec","severity":"medium","block_id":"p1","description":"The plot uses Math.sin instead of bare sin.","suggested_fix":"Use sin(x)."}]}

        The rest of this response is not JSON.
        """
    )

    assert len(findings) == 1
    assert findings[0].category == "broken_plot_spec"


def test_parse_findings_skips_latex_sets_before_json_object():
    findings = _parse_findings(
        r"""
        The set is $\{1,2,3\}$, so now here is the report:

        ```json
        {
          "findings": [
            {
              "category": "factual_error",
              "severity": "high",
              "block_id": "b1",
              "description": "The block says \{1,2\}=U, but U=\{1,2,3\}.",
              "suggested_fix": "Include 3 in the set."
            }
          ]
        }
        ```
        """
    )

    assert len(findings) == 1
    assert findings[0].block_id == "b1"


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


def test_parse_findings_drops_non_actionable_factual_scratchpad():
    findings = _parse_findings(
        """
        {
          "findings": [
            {
              "category": "factual_error",
              "severity": "high",
              "block_id": "b1",
              "description": "This is borderline and not strictly wrong; skipping.",
              "suggested_fix": null
            },
            {
              "category": "factual_error",
              "severity": "high",
              "block_id": "b2",
              "description": "The block says 2 + 2 = 5, which is false.",
              "suggested_fix": "Change the equation to 2 + 2 = 4."
            }
          ]
        }
        """
    )

    assert len(findings) == 1
    assert findings[0].block_id == "b2"


def test_parse_findings_wraps_unrepairable_python_syntax_as_value_error():
    with pytest.raises(ValueError, match="could not parse JSON object"):
        _parse_findings(r"{'findings': [\ nope]}")
