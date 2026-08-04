# 17. Tordeux, Chraibi & Seyfried (2015) - Collision-free speed model

## Evidence status

- Status: `full_text_verified`
- Full text: `../papers/17_2015_Tordeux_collision_free_speed.pdf`
- Version: arXiv:1512.05597v1, submitted 2015-12-17; the manuscript identifies itself as a TGF'15 contribution.
- Why it was added: the production scenario defaults to JuPedSim `collision_free_speed`, but the teacher's 1-16 list only includes the Social Force Model as an operational baseline.

## What the paper directly supports

The paper proposes a minimal speed-based microscopic model whose non-overlap property is built into its speed rule. Its five main parameters cover pedestrian size, desired speed, time gap, repulsion rate and repulsion distance. Simulation examples reproduce lane formation, a roughly linear bottleneck-width/flow relation and intermittent counter-flow at bottlenecks. The authors also state an important limitation: the presented model does not reproduce stop-and-go behavior.

## What this means for this project

- This is the correct first-line literature ancestor for the current default operational model family.
- Helbing & Molnar (1995) remains a foundational comparison and is relevant only when the configured operational model is actually Social Force; it cannot by itself validate the default run.
- The paper demonstrates model properties in selected simulations. It does not validate this project's geometry, parameter values, passenger demand, route choice, facilities or station-level predictions.

## Design and validation requirements

1. Every run must record the operational model name and its full parameter set; `jupedsim` alone is not a model identity.
2. The validation suite should include at least lane formation, bottleneck flow versus width and intermittent bidirectional bottleneck flow.
3. Stop-and-go reproduction must not be claimed for the current model without separate evidence.
4. Desired-speed and interaction parameters require dataset-specific calibration or an explicit `uncalibrated` label.

## Citation verdict

- Claim: "the current default local-motion family is collision-free speed based" - `supports` when combined with the code configuration and JuPedSim model mapping.
- Claim: "the current station simulation is empirically validated" - `does not support`.
- Claim: "the model reproduces every canonical crowd phenomenon" - `contradicts`; stop-and-go is an explicit limitation.
