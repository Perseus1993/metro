# 14. Feng, Duives & Hoogendoorn (2022) - VR wayfinding in a multi-story building

## Evidence status

- Status: `full_text_verified`
- Full text: `../papers/14_2022_Feng_VR_wayfinding_multistory.pdf`
- Version: final published version, CC BY 4.0, downloaded from TU Delft's repository.
- PDF verification: valid, unencrypted PDF 1.7; 23 pages including a TU Delft cover and 22 journal pages; cover and publisher first page match the verified citation.
- SHA-256: `6BEC31AE2F42478E6302AC6E249C7529D73181505F6A1C3C0B7646C460B1ABE5`

## Verified citation

Yan Feng, Dorine C. Duives, and Serge P. Hoogendoorn. "Development and evaluation of a VR research tool to study wayfinding behaviour in a multi-story building." *Safety Science* 147 (2022), article 105573, 1-22. DOI: [10.1016/j.ssci.2021.105573](https://doi.org/10.1016/j.ssci.2021.105573).

## Research question

Can a realistic immersive-VR tool collect sufficiently broad, interpretable and usable behavioral data for studying wayfinding across horizontal and vertical levels under normal and emergency conditions?

## Method and data

- WayR recreates several floors of a real TU Delft building and permits first-person navigation through corridors and staircases.
- Four sequential tasks increase in complexity: one within-floor task, two between-floor tasks, and an evacuation-to-exit task.
- HTC Vive head-mounted display and controller data are recorded at 10 Hz: position, timestamp, head rotation, and head-directed gaze intersection.
- The outputs are converted into route/exit choices, strategy and decision points; travel time, speed and distance; head rotation, hesitation and gaze distributions.
- Thirty-eight people participated; two stopped before completing all tasks, leaving 36 analyzed participants (19 female, 17 male; ages 17-41, mean 28.66).
- Objective behavior is assessed with distributional and repeated-measures tests. Subjective measures cover realism, presence, simulator sickness and system usability.

## What the paper directly supports

- A validation dataset for complex topology should include decision-making, task-performance and observation/search behavior, not just arrival or total travel time.
- Participants used distinguishable wayfinding strategies and exhibited route variability on both horizontal and vertical levels.
- Increasing task complexity was generally associated with longer relative paths, lower speed, more hesitation and more head rotation; floor changes were a notable source of difficulty/disorientation.
- Hesitations clustered near starts, destinations, decision points and stair landings; room numbers, floor plans, fire doors and exit signs were major visual attractors.
- The authors establish face, content and construct validity against their chosen criteria and report high usability with low average simulator-sickness incidence.

## Critical validity boundary

The study did **not** directly compare the same participants' behavior in the virtual building with behavior in the corresponding real building. The paper calls ecological validity preliminary and explicitly proposes that physical-vs-VR comparison as future work. Therefore it supports WayR as a data-collection and validation design, not a claim that all VR trajectories are ground truth for real station behavior.

## Project interpretation - not a direct claim by the paper

- Multi-floor navigation validation should observe choices at explicit decision points and record search/hesitation behavior near stairs, junctions and signs.
- Familiarity and learning across repeated tasks can alter route efficiency; tests should either randomize task order or model/report the learning effect.
- Head direction can be an inexpensive proxy for observation, but true gaze needs eye tracking.

## Limits and prohibited overclaims

- The analyzed sample is small and highly educated; population representativeness is limited.
- No other virtual pedestrians or social interactions were present, so the study does not validate crowd-following, collision avoidance or congestion response.
- Locomotion used a hand controller and capped speed; movement realism received the lowest realism subscore.
- "Gaze" is inferred from head direction intersecting geometry, not eye tracking.
- The emergency task used an alarm but did not reproduce smoke, fire, visibility loss, or real danger.
- Findings are evidence for a validation protocol, not parameters to hard-code into a station simulator.

## Testable requirements derived for this project

1. For every multi-level validation scenario, record route and exit choice at decision points, full trajectory, path length, travel time and speed.
2. Report path efficiency using actual/shortest-path distance or an equivalent explicit measure; distinguish wrong turns from necessary detours.
3. Detect and report pauses/search episodes near junctions, stairs, signs and destinations. If using the paper's operational definition, document that hesitation means less than 0.30 m movement over 3 s; do not assume this threshold is universal.
4. Split results by within-floor, between-floor and emergency tasks and test whether topology/condition changes behavior rather than pooling all trajectories.
5. Include familiar/unfamiliar traveler strata or an explicit learning-order control.
6. Do not call the simulation behaviorally validated until simulated decision-point choices and path/search metrics are compared with independent human data from a matched environment.

## Theoretical tier recommendation

- Wayfinding validation/data-collection protocol: **A- / strong methodological anchor**.
- Simulation algorithm or behavior law: **C / not an algorithmic foundation**.
- It is valuable for defining what "complex topology validation" means, not for choosing the production motion model.

## Source

- TU Delft record: https://repository.tudelft.nl/record/uuid:2a1ff810-c6d8-412f-af96-1654db087304
- Archived PDF source: https://repository.tudelft.nl/file/File_52177a67-d979-4696-b5d4-9e4677397240

