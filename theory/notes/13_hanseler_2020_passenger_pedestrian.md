# 13. Hanseler et al. (2020) - Passenger-pedestrian model from automated data

## Evidence status

- Status: `full_text_verified`
- Full text: `../papers/13_2020_Hanseler_passenger_pedestrian_model.pdf`
- Version: final published version, CC BY 4.0, downloaded from the TU Delft institutional repository.
- PDF verification: valid, unencrypted PDF 1.5; 22 pages including a one-page TU Delft cover and 21 journal pages; publisher first page matches the verified title, authors, journal, volume, pages and DOI.
- SHA-256: `9415AF228FCA30E45D29B9698E6ADB066974DE88DD6B5B81355665267F232AB7`

## Verified citation

Flurin S. Hanseler, Jeroen P. A. van den Heuvel, Oded Cats, Winnie Daamen, and Serge P. Hoogendoorn. "A passenger-pedestrian model to assess platform and train usage from automated data." *Transportation Research Part A: Policy and Practice* 132 (2020): 948-968. DOI: [10.1016/j.tra.2019.12.032](https://doi.org/10.1016/j.tra.2019.12.032).

The author's surname is printed as **Hänseler** in the article. The ASCII filename uses `Hanseler` only for filesystem portability.

## Research question

Can traveler dynamics in stations and in individual train cars be represented consistently in one computationally feasible model using automated fare-collection (AFC) data, train-tracking data, infrastructure descriptions, and behavioral assumptions for choices that are not directly observed?

## Method and data

- Individual travelers enter with departure time, origin and destination; train runs include realized timing, composition and capacity; each station is a directed pedestrian graph with links grouped into physical areas.
- Travelers first select a train itinerary and then a detailed travel path consisting of pedestrian links and specific train cars. Path utility includes walking, waiting and in-vehicle components and can respond to crowding.
- Movement inside stations is mesoscopic: a continuous-time, discrete-space stochastic service system. Link traversal speed follows a density-speed relationship, interfaces and facilities impose capacity constraints, and passengers retain their identity along the full journey.
- A day-to-day learning process updates expected path attributes. The case implementation used up to 24 independent runs per day and 250 learning iterations.
- The case covers the Utrecht-Schiphol corridor. The morning peak is 07:00-09:00 with 30-minute warm-up/cool-down windows; roughly 35,000-40,000 passengers and about 140 trains are represented. Eleven Tuesdays-through-Thursdays in March 2017 are analyzed.
- AFC and train tracking data drive estimation. Independent pedestrian flow counts and platform density observations - including a 25-stereo-camera system in Utrecht - are used for validation.

## What the paper directly supports

- Station pedestrian behavior and train-car loading are mutually dependent and can be modeled in a shared traveler-level framework.
- A traveler can account for downstream consequences: choosing a car changes both expected crowding and walking distance at later stations.
- Crowding affects both walking speed and perceived utility; platform and in-vehicle crowding are endogenous outputs.
- In the case study, estimated access/egress peaks and platform density patterns generally agree with observations at the available temporal and spatial resolution, while identifiable discrepancies remain.
- The paper demonstrates scenario analyses for escalator failure and altered train stopping position and reports computation about two orders of magnitude faster than real time for the studied setting.

## Important correction to the checklist wording

This is a strong **data-driven hybrid model**, but it is not, by itself, a demonstrated online state-estimation or data-assimilation algorithm in the Kalman/particle-filter sense. AFC and train-tracking records are model inputs; pedestrian counts and density data are mainly validation observations. The paper discusses real-time applications as potential uses. It should therefore anchor a digital-twin data pipeline, but it must not be cited as proof that this project already assimilates live observations or continuously updates hidden state.

## Project interpretation - not a direct claim by the paper

- Passenger identity should survive the chain `AFC demand -> itinerary -> station path -> waiting position -> train car -> downstream station path`, allowing conservation and downstream-cost tests.
- Train, platform, access facility, and traveler state should be joined through explicit interfaces rather than separate post-processing models.
- The model is especially relevant to the project's demand ingestion, train event schedule, platform occupancy, car selection, and validation-output architecture. It is not a source for continuous-space collision avoidance.

## Limits and prohibited overclaims

- The station movement model is mesoscopic and aggregate at interaction level; it does not validate Social Force or any continuous local-motion implementation.
- The case assumes travelers can board their desired train; denied boarding is outside the main formulation.
- The hierarchy "itinerary first, detailed path second" becomes unrealistic when capacity denial or complex multi-leg adaptation dominates.
- Several behavioral and fundamental-diagram parameters are borrowed across datasets and geographic contexts; the authors explicitly call dedicated revealed-preference calibration preferable.
- The proprietary Dutch itinerary-choice component is not fully reproducible from this article alone.
- Free-flow assumptions are used in some large station areas; subsidiary activities such as buying coffee are omitted and visibly affect accumulation timing.
- Good fit in one Dutch corridor is not proof of transferability to a metro station in another country.

## Testable requirements derived for this project

1. Validate input schemas for disaggregate demand, realized train events/composition/capacity, and a station graph with area and interface capacities.
2. Enforce passenger conservation and stable passenger identity across gates, station links, waiting areas, doors and train cars.
3. Feed crowding back into both movement time and tactical utility; test that disabling either channel changes the appropriate output and no unrelated module.
4. Keep calibration and validation data separate. At minimum compare time-binned facility flows, platform density fields, train-car loads and end-to-end journey counts.
5. Report MAE/RMSE or equivalent errors at declared temporal/spatial aggregation and show how conclusions change with aggregation.
6. Run multiple stochastic seeds and verify convergence/stability of learning iterations before reporting scenario differences.
7. Include capacity and disruption cases such as an escalator closure, altered stopping position, and denied boarding; the latter is a required project extension beyond this paper.
8. Treat all published speed, time-multiplier and capacity values as priors requiring local provenance and calibration, never as silent defaults.

## Theoretical tier recommendation

- Automated-data/station-train integration: **A / domain-level empirical anchor**.
- General pedestrian behavior theory: **B**.
- Local continuous-motion algorithm: **not applicable**.
- It is a major digital-twin/data-closure reference, but not the system's theoretical constitution.

## Source

- TU Delft record: https://repository.tudelft.nl/record/uuid:cd1cdb12-7b44-461e-8e28-a81c20f2f30a
- Archived PDF source: https://pure.tudelft.nl/ws/portalfiles/portal/68801635/1_s2.0_S0965856418307420_main.pdf

