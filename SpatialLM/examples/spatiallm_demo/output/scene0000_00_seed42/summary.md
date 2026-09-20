# SpatialLM Demo Result

This run converts the official point cloud into structured geometry, places the
geometry in `observation["spatial_context"]`, and persists it with
`TieredMemory.update()`.

## Input

- PLY: `examples/spatiallm_demo/input/scene0000_00.ply`
- Points: 685,513
- SHA-256: `12d8cf9c239791260166837d090334915f7056537a2e35c97959d9842a6c5f92`
- XYZ bounds (meters): `{'min_xyz': [1.9737932682037354, -6.713315486907959, -0.023860758170485497], 'max_xyz': [5.482537746429443, -1.648443579673767, 2.7371206283569336], 'extent_xyz': [3.508744478225708, 5.064871907234192, 2.760981386527419]}`

## SpatialLM Output

- Walls: 6
- Doors: 1
- Windows: 1
- Objects: 8
- Total runtime: 6.42 seconds

| Object class | Count |
| --- | ---: |
| `bed` | 1 |
| `curtain` | 1 |
| `cushion` | 1 |
| `dressing_table` | 1 |
| `nightstand` | 1 |
| `painting` | 1 |
| `stool` | 1 |
| `wardrobe` | 1 |

## Files To Inspect

- [Top-down input/output overlay](top_down.png)
- [Raw geometry from SpatialLM](spatial_context.json)
- [Geometry attached to an observation](observation.json)
- [Planner input before Memory update](planner_input_before_memory_update.json)
- [TieredMemory recall after update](memory_recall.json)
- [Planner input after Memory update](planner_input_after_memory_update.json)
- [Run configuration and timing](run_metadata.json)
- [Memory event](memory_events.jsonl)
- [Console log](run.log)

The demo does not call an LLM Planner or Verifier. The two planner-input files
show the exact boundary where the current observation and recalled spatial memory
would be supplied to those components.
