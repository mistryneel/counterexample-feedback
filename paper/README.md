# Paper

*What Does Formal Structure in Counterexample Feedback Buy?*, Neel Mistry and Sreedath Panat,
NeurIPS 2026 Workshop on AI for Verifiable Coding (poster).

## Files

| File | What it is |
|---|---|
| `main.tex` | Camera-ready source. Loads the style with `[final]`, which de-anonymizes the paper, removes line numbers and prints the workshop footer. |
| `checklist.tex` | The NeurIPS paper checklist, required by the template. `main.tex` inputs it after the appendices; it does not count toward the page limit. |
| `references.bib` | Bibliography. |
| `neurips_2026_vericode.sty` | The workshop's style file, distributed by the organizers for preparing papers. Not covered by this repository's licences. |
| `main.pdf` | The camera-ready PDF built from these sources: 22 pages, with the main text on pages 1 to 9, references from page 10, Appendices A to E from page 11 and the checklist from page 15. |
| `submitted/main_v1.0-submission.pdf` | The anonymous PDF that was submitted and reviewed (10 pages, sha256 `8507051b5c6163eff006e204eef558302f4fd71fbff9612a6a966fe1a776a505`). It is also `paper/main.pdf` at tag `v1.0-submission`. |
| `figures/make_figures.py` | Generates Figures 2 to 4 from the campaign log. |
| `figures/fig*.pdf`, `figures/fig*.png` | The figures; the PDFs are included by `main.tex`, the PNGs are copies for slides. |

## Build

Built with Tectonic 0.17.0, as were both the submitted and the camera-ready PDF:

```bash
cd paper
tectonic -X compile main.tex --outdir /tmp/paper-build
```

Without `--outdir` the build overwrites `paper/main.pdf`. On first use Tectonic downloads the
TeX resources it needs. The build runs TeX, BibTeX, then TeX three more times, and prints two
`Underfull \vbox` warnings (`main.tex` lines 460 and 644, each printed twice); both are
expected. The result is a 22-page PDF whose text, extracted with `pdftotext`, is identical to
`paper/main.pdf`. With `SOURCE_DATE_EPOCH=1791770765` (the committed PDF's creation time) the
build is byte-identical to `paper/main.pdf`.

Other TeX engines (for example `pdflatex`) have not been checked. The main text fills page 9
exactly, so check the pagination if you switch engines.

## Figures

Figure file names predate the camera-ready numbering.

| Paper | File | Source |
|---|---|---|
| Figure 1 | `fig1_pipeline.png` | Drawn with an AI image-generation tool from a schematic the authors specified. It is a static schematic and carries no data; there is no generating script. |
| Figure 2 | `fig4_funnel.pdf` | `make_figures.py`, from `data/results/attempts.jsonl` |
| Figure 3 | `fig2_uncertainty.pdf` | `make_figures.py`, from `data/results/attempts.jsonl` and the intervals in `data/results/uncertainty.json` |
| Figure 4 (Appendix C) | `fig3_patch_type.pdf` | `make_figures.py`, from `data/results/attempts.jsonl` |

Regenerate Figures 2 to 4 from the repository root:

```bash
.venv/bin/python paper/figures/make_figures.py
git status --short paper/figures     # prints nothing: the outputs are byte-identical
```

The script writes the three PDFs and three PNGs into `paper/figures/`. It sets the text in
Liberation Serif and embeds fonts as TrueType; the outputs are byte-identical to the committed
files only when that font is installed (Ubuntu package `fonts-liberation`), because otherwise
matplotlib falls back to DejaVu Serif.
