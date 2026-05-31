# Reconciler Test Fixtures

Each fixture is a single JSON file in `pipeline/tests/fixtures/reconciler/`,
named `case_NN_short_description.json`. The runner discovers them by glob,
sets up the DB state in `setup`, calls `db.replace_topic_blocks(topic_id,
pinned_ids, sequence)`, and asserts against `expected`.

## File schema

```json
{
  "name": "case_02_one_ungrouped_anchor",
  "description": "Free-text description for humans reading test output.",

  "setup": {
    "blocks": [
      {
        "id": "blk_a",
        "type": "paragraph",
        "content": { "...": "BlockNote-shaped jsonb" },
        "order": 0,
        "manually_edited": false,
        "group_id": null,
        "generation_metadata": null
      }
    ]
  },

  "pinned_ids": ["blk_b"],

  "sequence": [
    { "type": "heading", "content": { "...": "..." }, "group_id": null },
    { "id": "blk_b" },
    { "type": "paragraph", "content": { "...": "..." }, "group_id": null }
  ],

  "expected": {
    "kind": "success",
    "block_count": 3,
    "anchors_preserved": [{ "id": "blk_b", "order": 1 }],
    "new_blocks_at_orders": [0, 2]
  }
}
```

For error cases, `expected` flips shape:

```json
"expected": {
  "kind": "error",
  "error_type": "ValueError",
  "message_contains": "references non-pinned ids"
}
```

## Setup fields

- `setup.blocks`: list of rows to insert into `Block` before calling the
  reconciler. Each row provides the explicit `id` so fixtures can reference it
  by name in `pinned_ids` and `sequence`. The runner creates a synthetic
  course + topic to host them; topic_id is generated per-test, not hard-coded.

## Sequence items

- Anchor reference: `{"id": "<existing_block_id>"}`. No other keys.
- New block: `{"type": "<BlockType>", "content": {...}, "group_id"?: str|null,
"generation_metadata"?: dict|null}`. No `id`; reconciler generates one.

## Expected fields (success)

- `block_count`: int. Total rows on the topic after reconciliation.
- `anchors_preserved`: list of `{id, order}` pairs. Each anchor must still
  exist with `id` matching exactly and `order` equal to the expected slot.
  The runner also asserts each anchor's `content`, `manually_edited`,
  `group_id`, and `source` are byte-identical to the setup row.
- `new_blocks_at_orders`: list of orders where new blocks should appear. The
  runner asserts each is a fresh uuid (not in setup ids) and that its `type`
  and `content` match the corresponding sequence item.
- Implicit assertion: orders are dense 0..N-1 with no gaps or duplicates.

## Expected fields (error)

- `error_type`: Python exception class name. Match by `type(e).__name__`.
- `message_contains`: substring assertion on `str(e)`.
- Implicit assertion: DB state is unchanged from setup (rollback worked).

## Cases to write

| #   | Name                                         | What it exercises                                                                                                                                |
| --- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| 01  | `no_anchors`                                 | Topic with no manually_edited blocks; sequence is all new. Original blocks deleted.                                                              |
| 02  | `one_ungrouped_anchor`                       | Single pinned singleton, new blocks flanking it. Order rewritten.                                                                                |
| 03  | `grouped_anchor_full_cohort`                 | Group of 2, only one member edited; full cohort pinned via expansion. Both preserved contiguously.                                               |
| 04  | `all_pinned_group_only`                      | Whole topic is one pinned group; sequence is just the anchors. No new blocks, no deletes.                                                        |
| 05  | `anchor_repositioned`                        | Pinned singleton moves from order 1 to order 3. Order rewrite verified.                                                                          |
| 06  | `empty_topic_first_run`                      | No existing blocks, no pinned, all new. Cold-start path.                                                                                         |
| E1  | `error_anchor_not_pinned`                    | Sequence references an id not in pinned_ids. ValueError pre-DB.                                                                                  |
| E2  | `error_pinned_missing_from_sequence`         | pinned_ids contains an id with no anchor reference in sequence. ValueError pre-DB.                                                               |
| E3  | `error_duplicate_anchor_ref`                 | Sequence references the same anchor twice. ValueError pre-DB.                                                                                    |
| E4  | `error_pinned_id_not_in_db`                  | pinned_ids contains an id that doesn't exist on the topic. ValueError post-cursor-open, before any writes. DB unchanged.                         |
| E5  | `error_anchor_content_unchanged_at_db_level` | (Skipped here — anchor content mutation is the prompt validator's job, not the reconciler's. Document this in the test runner as "not covered.") |

E5 is intentionally not a fixture: the reconciler doesn't validate anchor
content (it doesn't even look at it). That contract is enforced upstream by
the anchor-integrity validator described in §6.
