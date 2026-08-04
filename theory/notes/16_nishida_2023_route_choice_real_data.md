# 16. Nishida, Onishi & Hashimoto (2023) - DCM plus SFM with real large-scale data

## Evidence status

- Status: `full_text_verified`
- Full text: `../papers/16_2023_Nishida_route_choice_real_data_preprint.pdf`
- Version: arXiv:2302.10421v2, submitted 24 February 2023; the arXiv record identifies it as the full version of the AAMAS 2023 extended abstract.
- Conference publication: three-page extended abstract in *Proceedings of the 22nd International Conference on Autonomous Agents and Multiagent Systems (AAMAS 2023)*, pp. 2751-2753.
- PDF verification: valid, unencrypted PDF 1.5; 12 pages; first page matches title, authors and arXiv version marker.
- SHA-256: `1D937B75F9BBAEB0B73EF717DFA511AD80E252DD60238B2DA7FE9A98789677A2`

## Verified identifiers and metadata caveat

- AAMAS proceedings DOI currently registered by IFAAMAS: [10.65109/gceq5506](https://doi.org/10.65109/gceq5506). It redirects to ACM catalog record `10.5555/3545946.3599066`.
- Full preprint DOI: [10.48550/arXiv.2302.10421](https://doi.org/10.48550/arXiv.2302.10421).
- Official proceedings ISBN: `978-1-4503-9432-1`.

The Crossref record for `10.65109/gceq5506` was deposited in January 2026 and contains inconsistent legacy fields (it names IEEE Computer Society as publisher and includes an unrelated old proceedings subtitle). Title, authors, date and pages match, and the prefix owner is IFAAMAS, but venue/publisher metadata in this workspace follows the official IFAAMAS proceedings page and the paper itself rather than those erroneous fields.

## Research question

Does a tactical discrete-choice route model estimated from observed choices improve the reproduction of real crowd movement when combined with an operational walking model, including at a tens-of-thousands scale?

## Method

- General pipeline: measure real crowd movement -> estimate a route-choice model -> construct an agent simulator -> compare simulated and observed movement.
- Tactical model: multinomial logit (the paper uses `DCM` to mean MNL), with random utility and scenario-specific attributes.
- Operational model: Social Force Model; the authors note another local-navigation model could be substituted if it accepts tactical route direction.
- Route-choice data are split into five folds for cross-validation. Simulation is stochastic and is run 50 times for the main comparisons.

### Theater evacuation drill

- Fifty-two evacuees pass the measured doorway.
- RGB-D trajectories are converted into a route choice every 0.5 s.
- Attributes are distance to route start (`DIST`), previous choice (`CH`), number choosing the route in front (`NF`) and behind (`NB`).
- Five-fold cross-validation grouped by pedestrian yields 82.2% choice accuracy.
- The fitted signs indicate persistence and following people ahead, but the sample is small and repeated choices from the same person require grouped validation as the authors perform.

### Fireworks event

- LiDAR supplies 34,937 route-choice observations at two junctions; RGB-D counts 34,839 arrivals at the station.
- Attributes are route distance (`DIST`), active guidance (`GUIDE`) and attraction such as food stalls (`ATT`).
- Five-fold cross-validation yields 70.7% choice accuracy.
- CrowdWalk supplies a one-dimensional link-node network and its default SFM; observed demand timing, guidance operations and train timetable are reused in simulation.
- Compared with a baseline in which all agents follow guidance, DCM reduces arrival-count MAE from 69.5 to 54.0 (22.3%) and RMSE from 91.4 to 77.2 (15.6%). Mean computation time rises from 6 min 21 s to 7 min 12 s, or about 1.13 times.

## What the paper directly supports

- Tactical route choice and operational motion can be separated and connected through route direction.
- Estimating route utilities from measured choice behavior can reproduce observed route splits and time-varying arrivals better than the tested deterministic baselines in these two cases.
- Guidance and route attraction can enter a data-estimated utility model rather than being implemented as absolute obedience.
- End-to-end evaluation can include both model-level choice prediction and system-level time-series similarity, plus computation cost.

## Critical validation boundary

This is **reproduction within measured events**, not demonstrated prediction of unseen events. Departure timing, total demand, actual guidance, timetable and some initial/trigger trajectories are reused from the observations. The authors explicitly state that they did not test unknown crowd movements, such as another theater area or the following year's fireworks event. Therefore, the paper is strong evidence for the pipeline and metric design, but not for cross-site predictive validity.

## Limits and prohibited overclaims

- The fireworks model makes one route choice per junction and uses homogeneous MNL coefficients; taste heterogeneity, correlated alternatives and repeated revision are not represented.
- Default CrowdWalk SFM parameters are used rather than calibrated local-motion parameters.
- The station-arrival mismatch before roughly 22:30 is attributed to limited station-behavior expressiveness.
- Detailed route-choice observations are costly; the paper proposes partial data-assimilation ideas as future work, not a completed result.
- Accuracy alone is not a sufficient DCM diagnostic; likelihood, calibration, coefficient uncertainty and out-of-sample transfer also matter.
- The conference contribution is an extended abstract and the analyzed full text is a preprint, so it should not displace mature theoretical sources.

## Testable requirements derived for this project

1. Keep tactical route choice and operational motion behind separate interfaces; the tactical output must define the next route/target, not directly update position.
2. Estimate choice parameters from observed choices and split train/test data by passenger or event to prevent repeated-observation leakage.
3. Record model specification, alternative set, coefficient estimates/uncertainty, log-likelihood or calibration measures, and held-out choice accuracy.
4. Compare against at least a shortest-path/deterministic-guidance baseline with identical demand, operations and local-motion settings.
5. For stochastic route choice, run a declared seed set and report mean and dispersion across repetitions; the paper's 50 runs are a useful reference, not a universal minimum.
6. Evaluate both route shares and time-binned downstream counts with MAE/RMSE, while also checking density/safety measures that this paper leaves thin.
7. Add a true holdout test across day, scenario, station or intervention before claiming prediction or digital-twin forecasting.
8. Never copy the reported coefficients into production: variables, scaling and environment are scenario-specific.

## Theoretical tier recommendation

- End-to-end implementation and validation pattern: **A- / closest technical exemplar**.
- General theory and transferable parameter evidence: **B**.
- It is an important bridge between Hoogendoorn's tactical/operational distinction and an executable DCM+SFM pipeline, but it is not the sole or highest-status academic foundation.

## Sources

- Full preprint record: https://arxiv.org/abs/2302.10421v2
- Archived full PDF source: https://arxiv.org/pdf/2302.10421v2
- Official AAMAS extended abstract: https://www.ifaamas.org/Proceedings/aamas2023/pdfs/p2751.pdf
- Official proceedings index: https://www.ifaamas.org/Proceedings/aamas2023/index.htm

