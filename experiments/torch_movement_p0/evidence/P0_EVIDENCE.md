# Metro PyTorch Movement P0 — Evidence

- Generated (UTC): 2026-08-02T14:56:31.608465+00:00
- Environment: Python 3.12.13; Torch 2.13.0+cu126; CUDA 12.6; device NVIDIA GeForce RTX 3080
- Decision: **GO: constrained P1 R&D**

## Gate results

- M1–M7 movement scenarios: PASS
- Autograd + synthetic recovery: PASS
- Existing Metro `MovementBackend` injection smoke: PASS
- GPU 32×300 throughput ≥ 500,000 agent-step/s: PASS

## Movement scenarios

| Scenario | Result | Key metrics |
| --- | --- | --- |
| M1_single_walker | PASS | endpoint_error_m=0.019243240356445312; minimum_agent_gap_m=n/a; minimum_wall_clearance_m=1.8267967700958252; max_speed_mps=1.199999451637268; projection_contacts=0 |
| M2_head_on | PASS | destination_error_m=0.042879585176706314; minimum_agent_gap_m=0.0009995996952056885; minimum_wall_clearance_m=1.8267881870269775; max_speed_mps=1.2042770385742188; projection_contacts=24 |
| M3_bidirectional_corridor | PASS | mean_abs_progress_m=7.526302814483643; minimum_agent_gap_m=0.0009992718696594238; minimum_wall_clearance_m=0.02073410153388977; max_speed_mps=1.8000001907348633; projection_contacts=134 |
| M4_bottleneck | PASS | agents_past_bottleneck=11; minimum_agent_gap_m=-0.0075085461139678955; minimum_wall_clearance_m=0.0010000020265579224; max_speed_mps=1.8000001907348633; projection_contacts=3527 |
| M5_slot_reuse | PASS | slot_reused=True; velocity_reset=True; active_ids_match=True |
| M6_level_isolation | PASS | first_agent_delta_m=0.0 |
| M7_dynamic_obstacle | PASS | final_x_m=7.516566753387451; minimum_agent_gap_m=n/a; minimum_wall_clearance_m=0.19471341371536255; max_speed_mps=1.1944570541381836; projection_contacts=0 |

## Differentiable calibration

- Autograd / finite-difference gradient: 0.04014291 / 0.04013954
- Relative gradient error: 0.008399%
- Synthetic relaxation-time recovery: true 0.380s → recovered 0.380s
- Loss: 0.020191409 → 1.7600174e-10

## Throughput

| Device | Batch | Slots | Agent-step/s | Peak MiB |
| --- | ---: | ---: | ---: | ---: |
| cpu | 1 | 300 | 12,668 | — |
| cuda | 1 | 300 | 35,697 | 4.5 |
| cuda | 8 | 300 | 306,671 | 36.0 |
| cuda | 32 | 300 | 997,550 | 140.9 |
| cuda | 1 | 1024 | 123,461 | 52.1 |

## Metro boundary smoke

- Injected through existing constructor: True
- Single passenger progressed: 4.001m; retained tensor slots: 1

## Scope and P1 blockers

- The P0 adapter is in an experiment directory and handles only a rectangular envelope; it does not replace Metro's default JuPedSim backend.
- M4 reached a worst numerical agent overlap of about 7.5 mm after sequential wall/agent projections. This is within the P0 1 cm tolerance but blocks production use until a joint contact solver is validated.
- Polygonal walkable geometry, obstacles/stairs/escalators, queues/trains, formal JuPedSim parity, multi-seed statistics, and end-to-end operational acceptance remain P1/P2 work.
