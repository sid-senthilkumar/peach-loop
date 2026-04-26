# peach-loop

A learning project for building the autonomous model-development loop end-to-end. The model is small. The loop is the point.

## What this is

A scaffolded environment for running an autonomous model-training agent on a remote machine (DGX Spark in my case, but the spec is portable). The agent trains PEACH's archetypal autoencoder on public single-cell RNA-seq data, runs sweeps, produces reports. I monitor from elsewhere via a daily digest. I'm pinged at three named checkpoints. Otherwise it runs unattended.

The substrate is PEACH (Honkala & Malhotra, *bioRxiv* 2025 — github.com/xhonkala/PEACH). The model itself is small (1-10M params, 30-90 min per run). The compute target is over-specced on purpose — Spark isn't the bottleneck, the *loop* is what I'm developing.

The thesis flavoring, if I want it, is whether PEACH's discovered archetypes are stable across reasonable preprocessing choices — a methodological question nobody has systematically answered.

---

## What PEACH is and why it matters

### Archetypal analysis, conceptually

Plot your cells in high-dimensional gene-expression space. PCA finds directions of greatest variance. Clustering finds blobs. **Archetypal analysis finds the *extreme points* on the boundary of the data cloud.** Every cell gets represented as a weighted mixture of these extremes.

Geometrically: your data sits inside a convex hull. Archetypes are the corners. A cell at the centroid is a balanced mixture of all archetypes; a cell near a corner is a "pure" instance of that archetype.

Biologically: cells aren't arbitrary points — they're typically pulled between competing pressures (proliferation vs. differentiation, glycolysis vs. oxidative phosphorylation, stem-like vs. terminally differentiated). Each extreme state represents a phenotype optimized for one task at the cost of others. Most cells in the wild are mixtures, sitting somewhere on the trade-off front.

This connects to **Pareto optimality** (Shoval et al. 2012, *Science*). When a biological system needs to perform multiple tasks, no single phenotype can be optimal at all of them — improving one task degrades another. Evolution drives populations toward the Pareto front: the set of phenotypes where no task can be improved without sacrificing another. The *vertices* of that front are the archetypes — phenotypes specialized for single tasks. Everything else is a weighted average.

This is why archetypal analysis is biologically meaningful in a way that arbitrary embedding methods aren't: the geometry of the data cloud isn't incidental, it's the signature of evolutionary trade-offs.

### What PEACH specifically does

**PyTorch Encoders for Archetypal Convex Hulls.** It's a deep autoencoder where the latent space is constrained to be a simplex with archetype vertices, rather than an unconstrained Euclidean latent. Cells get compressed into archetype-space coordinates (which sum to 1), then decoded back to gene expression. The simplex constraint is what makes the archetypes pop out as identifiable corners rather than diffusing into a generic latent.

Beyond the model itself, PEACH ships:

- **PCHA initialization** — classical archetypal analysis used as a warm start for the deep version. Without it, deep AA often finds bad local minima. This is a real engineering pattern worth noticing: classical method as warm start for the deep version is a recurring move.
- **Multiple loss components** — archetypal, diversity, regularity, sparsity, manifold. You can weight them. Each pushes the latent simplex toward different geometric properties.
- **Cross-validation hyperparameter search** — the right `n_archetypes` for a dataset isn't obvious; PEACH does the grid search.
- **Statistical testing** for which genes/pathways are enriched at each archetype (Mann-Whitney with FDR correction, MSigDB integration).
- **Pattern analysis** — which features are exclusive to one archetype, which form trade-offs across pairs.
- **3D interactive visualization** of the archetype simplex with cells colored by gene expression.
- **CellRank integration** — using archetypes as endpoints/origins for trajectory analysis.

It's the most complete archetypal-analysis-for-scRNA-seq pipeline that exists. Prior tools (PCHA, ParTI) were R-based and bare-bones.

### What you'd use it for, scientifically

- **Cell-state characterization.** What are the "pure types" in this tumor / tissue / development trajectory? Often more interpretable than clusters because you get gradients, not boxes.
- **Trade-off discovery.** If archetype A is high-glycolysis and archetype B is high-OXPHOS, the cells in between are showing the metabolic trade-off explicitly, with quantifiable mixture coefficients.
- **Identifying transitional populations.** Cells with high mixture coefficients are intermediates; cells near vertices are committed.
- **Comparing samples.** Does a disease state shift the archetypal distribution? Does a perturbation collapse the simplex? Does it shift cells toward one vertex?

### What you're doing with it in this project

Not extending the science. Using it as a *training target.*

- The Deep_AA model is the thing being trained autonomously
- PBMC 3K is the substrate (PEACH ships ready to handle scanpy AnnData objects)
- Phase 1 produces a trained model + archetype coordinates + gene/pathway enrichment per archetype
- Phase 2 (preprocessing sweep) tests how stable PEACH's archetypes are across reasonable preprocessing choices — a real methodological question

The point is not to do better archetypal analysis than PEACH already does. The point is to develop the autonomous-training loop, on a model small enough to iterate the loop.

### Three things worth understanding more deeply

In priority order:

1. **The simplex constraint.** Why does forcing latent coordinates to sum to 1 give you archetypes? What happens without the constraint? Read Mørup & Hansen 2012 and PEACH's `Deep_AA` source in `src/peach/_core/`. This is the conceptual heart.

2. **The PCHA warm start.** Without classical AA initialization, deep AA often finds bad local minima. This is a generalizable pattern — classical method as warm start for the deep version shows up across ML. Worth internalizing.

3. **The Pareto-optimality biology frame.** Shoval et al. 2012 is the conceptual paper that motivates *why* archetypal analysis is biologically meaningful. Short, citation-worthy, gives you the theoretical grounding for what your archetypes "mean."

---

## Why this project shape

I haven't run a model autonomously before. The first project doing this shouldn't be a 1B-parameter pretraining run that takes weeks per iteration. It should be a model small enough that I can complete the loop in an afternoon, see what breaks, change the loop, and run again. PEACH is small enough for that, real enough to teach me real things, and connected to a tool I want to play with anyway.

Thesis is optional flavoring. If a result emerges from the sweeps, it becomes a writeup. If not, the project succeeds on the basis of the loop being built.

---

## Repo layout

```
peach-loop/
├── README.md                 # this file
├── AGENTS.md                 # spec for the agent running on Spark
├── BOOTSTRAP_PROMPT.md       # prompt for Claude Code to scaffold the repo
└── docs/                     # populated by Claude Code as the project runs
```

After Claude Code does the bootstrap, the repo gains `src/`, `data/`, `configs/`, `logs/`, `reports/`, `checkpoints/` directories. Specifics are Claude Code's call (see AGENTS.md §11).

---

## Reading list

Three for orientation, rest if curious.

### Essential

- **Honkala & Malhotra, "Python Encoders for Archetypal Convex Hulls (PEACH): PyTorch-Based Archetypal Analysis,"** *bioRxiv* 2025. The actual tool. Read README, skim `src/peach/_core/` to see Deep_AA implementation. Tutorials in `docs/tutorials/` show the standard workflow. github.com/xhonkala/PEACH.

- **Mørup & Hansen, "Archetypal analysis for machine learning and data mining,"** *Neurocomputing* 2012. Foundational paper for archetypal analysis. Conceptually clean. Establishes the geometric intuition: archetypes are extreme points of the data convex hull, expressed as convex combinations of data points.

- **Shoval, Sheftel, Shinar, Hart, Ramote, Mayo, Dekel, Kavanagh, Alon, "Evolutionary Trade-Offs, Pareto Optimality, and the Geometry of Phenotype Space,"** *Science* 336:1157-1160, 2012. The theoretical biology motivation for why archetypal analysis is meaningful. Phenotypes that need to be good at multiple tasks fall on Pareto fronts; vertices of the front are archetypes. Short paper, dense ideas. doi: 10.1126/science.1217405.

### For the loop itself

- **Karpathy, "A Recipe for Training Neural Networks,"** 2019. http://karpathy.github.io/2019/04/25/recipe/. Operational mindset. The "leave it training" section and the "verify pipeline before scaling" section both apply directly here.

- **Karpathy, "Software 2.0,"** 2017. Frames why the loop (data → model → evaluation → iteration) is the actual product, not the model.

- **The 12-Factor App,** principles 11 (logs) and 12 (admin processes). Old, still right. The disk-as-source-of-truth principle in AGENTS.md comes from here.

### For PEACH context

- **Cutler & Breiman, "Archetypal Analysis,"** *Technometrics* 36:338-347, 1994. The original paper. Worth skimming for historical grounding and the original optimization framing.

- **scverse documentation** — scverse.org. PEACH plays in this ecosystem. Useful for understanding AnnData conventions and how single-cell tooling fits together.

- **Hart, Sheftel, Hausser, Szekely, Ben-Moshe, Korem, Tendler, Mayo, Alon, "Inferring biological tasks using Pareto analysis of high-dimensional data,"** *Nat Methods* 2015. Application of Pareto/archetypal framework to biology with the ParTI software. Good complement to Shoval et al.

### Optional, deeper

- **Sheftel, Shoval, Mayo, Alon, "The geometry of the Pareto front in biological phenotype space,"** *Ecology and Evolution* 2013. Mathematical extension of the 2012 Science paper.
- **Edelaar 2013 critique and Shoval et al. 2013 response** in *Science.* Useful for understanding the statistical caveats around archetypal analysis — the criticism focuses on pseudoreplication and inflated significance levels in the original tests. Worth knowing about for honest reporting.

---

## Project phases

### Phase 1 — One clean run end to end

**What I'm trying to learn:** every part of the autonomous loop has to actually work. A clean run means: data downloads and verifies, model instantiates, training proceeds, checkpoints save, eval runs, report generates, and I receive a digest. If any one of those breaks, I haven't learned the loop — I've learned where it broke.

**The actual work:** Train PEACH's Deep_AA encoder on a small, well-characterized public scRNA-seq dataset. Default: PBMC 3K (3000 peripheral blood mononuclear cells, the canonical small benchmark). Use PEACH's recommended `n_archetypes` for this dataset (typically 5-7 for PBMC). Single training run, default hyperparameters from PEACH.

**What to notice:**
- How long does each piece actually take? (Data download, preprocessing, PCHA init, model fit, archetype extraction, gene enrichment, plotting.) Note the bottlenecks. They're rarely where I'd guess.
- Where do silent failures happen? Classic ones: dataloader returns wrong shape, NaN in loss but training continues, eval set leakage, checkpoint saves but doesn't load cleanly, PCHA warm start fails silently and deep AA starts from random.
- What does "convergence" look like for a deep archetypal AE? It's not standard reconstruction loss minimization — there's a reconstruction term, an archetypal regularizer (pushes archetypes toward extreme points), and various other loss components. The loss curve should show each term separately. If it doesn't, the logging is wrong.
- Are the discovered archetypes biologically interpretable? PBMC 3K has known cell types — T cells, B cells, monocytes, NK cells, dendritic cells. Do the archetypes correspond to these or to something else? Either is interesting; the question is whether you can tell from the gene enrichment.
- Is the digest actually informative? Read it the next morning before looking at any other output. If it doesn't tell you what happened, the digest format is wrong.

**Done when:** I have a trained model, a generated report, and a digest from the run, and I can explain — out loud — what happened in each phase.

**Checkpoint 1 fires here.** Review what came out of Phase 1, what surprised me, what I want to change before Phase 2.

### Phase 2 — Vary one thing at a time

**What I'm trying to learn:** experiments come in batches, not single runs. The autonomous loop pays off when it can sweep through variations and produce a comparison without me babysitting. I also need to develop intuition for what variations *matter* in archetypal analysis specifically.

**The actual work:** Run a structured sweep across one of the following dimensions, with everything else held to Phase 1 defaults. Pick one. The agent runs all variants in sequence, produces a comparison report.

**Variation A — n_archetypes.** Run with k = 3, 5, 7, 10, 15. The interpretation question: at what k do new archetypes start corresponding to noise rather than real cell-state structure? Look at: archetype stability (do the same archetypes reappear across re-runs with different seeds?), reconstruction quality (does it plateau?), gene-set enrichment per archetype (does interpretability degrade with high k?). PEACH ships an elbow-curve utility for exactly this.

**Variation B — preprocessing.** Hold k fixed at the Phase 1 value. Vary the preprocessing pipeline: raw counts vs. log-normalized, with vs. without highly-variable-gene selection, with vs. without scaling. The interpretation question: how robust are PEACH's archetypes to preprocessing choices? This is methodologically the most useful one — every paper using these tools makes preprocessing choices and rarely reports sensitivity. **Recommended starting point.**

**Variation C — latent dimensionality.** Hold k fixed, vary the autoencoder's latent dim. The interpretation question: when does the latent space become too cramped to represent the data, and when does it become large enough to overfit?

**Variation D — dataset.** Run identical Phase 1 config across PBMC 3K, PBMC 10K, and a third dataset (Tabula Sapiens immune subset, or whatever's accessible). Are discovered archetypes consistent across cohorts of the same tissue? Most expensive variation, most scientifically interesting.

**Why preprocessing is the right starting variation:** it's the variation where you're most likely to find something genuinely surprising; it exposes what archetypal analysis is and isn't sensitive to; it gives you real intuition for the tool; and the methodological note that falls out — "Sensitivity of PEACH archetypes to preprocessing choices" — is publishable.

**What to notice:**
- Did the sweep complete without intervention? If not, where did it fail and why? This is the actual product of Phase 2 — knowing where the loop is fragile.
- Are the comparison plots useful? If I have to dig through raw data to understand what happened, the report template is wrong.
- Did the sweep tell me something I didn't know? The variations are picked so the answer should be yes for B and C and probably yes for A and D. If no, I'm missing the right metric.
- How much of the sweep did I actually pay attention to vs. just trust? The right answer isn't 100% (means I'm not really being autonomous), but it shouldn't be 0% either.
- Are the archetypes *consistent* across variants? PEACH provides Jaccard-style stability metrics. The expected answer for preprocessing variation is "mostly yes for clear-cut archetypes, no for marginal ones." If you find something different, that's the result.

**Done when:** the sweep is complete, the comparison report exists, and I can articulate one thing I learned about the model and one thing I learned about the loop.

**Checkpoint 2 fires here.** Review.

### Phase 3 — Reflect, refactor, optionally claim

**What I'm trying to learn:** the loop only gets better if I improve it deliberately. This phase is where I take what I learned in Phases 1-2 and either (a) make the loop better, (b) write up findings, or (c) both.

**Three sub-options:**

**3a — Loop refactor.** Identify the three biggest pain points from Phases 1 and 2. Update AGENTS.md to specify the fix. Have Claude Code re-implement the affected parts. Re-run a single Phase 1-style baseline to verify. This is the option that compounds — loop improvements pay off in every future project.

**3b — Methodology writeup.** If Phase 2 produced something interesting (especially likely with Variation B), write it up as a short methodological note. "Sensitivity of PEACH archetypes to preprocessing choices" is a real, useful, undocumented contribution. Doesn't need to be a paper — a clean blog post or technical note works.

**3c — Both.** 3a refactor first, then 3b writeup using the refactored loop. Most ambitious version.

**What to notice:**
- Which loop improvements feel like they'd transfer to the next project (a real training run, eventually) vs. PEACH-specific?
- If writing up Phase 2 results, am I treating the result as findings or as "look what I made"? First is publishable; second is portfolio-only.
- What do I want to do next, now that the loop exists?

**Done when:** either the loop is meaningfully better, there's a writeup, or both.

**Checkpoint 3 fires here.** Final review.

---

## Operational expectations

**My time budget:** ~3 hours of focused attention spread across the project. Three checkpoints (~30-60 min each). Reading the daily digest (~5 min/day during active phases — probably 2-3 weeks total).

**Agent on Spark:** unspecified at scaffolding time. Could be Claude Code in agent mode, could be Hermes Agent, could be something else current at execution time. AGENTS.md is written agent-agnostic.

**Pace:** Phase 1 is an afternoon. Phase 2 is a few days of background runs. Phase 3 is a long weekend. Total wall-clock 1-2 weeks if I'm not waiting on anything; longer if batching checkpoints across busier weeks.

---

## What's out of scope

- Training a foundation model. Wrong scale for this project.
- Wet-lab anything. Pure compute.
- Multi-node anything. Single Spark.
- Modifying PEACH itself. I'm using PEACH, not improving it.

If something interesting suggests one of these is the right next project, that's a finding for the writeup, not a mid-project pivot.
