# MCP capability contract

The public MCP surface expresses user intent and does not expose internal
`workflow_id` values. The web UI and MCP adapter will both dispatch these
requests through the same generation service.

## Image generation

- `create_image`: text-to-image and reference-based editing, including relighting.
- `create_character_sheet`: turnaround or expression sheets.
- `create_storyboard`: 6- or 9-panel storyboard sheets.
- `create_game_ui_assets`: 2×2 game UI asset sheets and grouped exports.

## Image tools

- `remove_background`: chroma key where suitable, RMBG as a fallback.
- `separate_layers`: See-Through PSD layer separation.

## Music generation

- `generate_music`: ACE-Step music generation.

`NanoBanana_ChainsawJuiceKingCharacter` remains an internal web preset and is
not part of the public MCP contract.

Every billable request carries an `idempotency_key` and an explicit
`cost_confirmed` flag. Network-derived principal/IP information is attached by
the server and is never trusted from the tool request body.

The initial game UI contract supports only `2x2`. Additional grids should be
added after their generation and slicing paths are implemented and tested.

