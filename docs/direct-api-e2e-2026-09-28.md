# Direct API Two-Chapter Acceptance

Date: 2026-09-28. Environment: local Docker console on port 8199 with the
compose PostgreSQL database. Isolated project: `goal-flare-20260928`.
This is engineering acceptance of two short chapters, one page and one panel
per chapter, not publishing-quality artwork or a full-length novel benchmark.

## Verified Model Behavior

- `gpt-image-2.5-flare` generated real global references and an initial panel.
  Its square panel did not fit the portrait page without cropping.
- `gpt-image-2.5-sunburst` generated both accepted panels at 1024x1536.
  Both assembled pages are 1600x2400 with visible captions.
- Sunburst also returned 1536x1024 for one 1024x1536 request. That result was
  marked needs-work, not accepted. A targeted vertical-composition retry passed.
- Text processing remained separate, using `gpt-5.5` for the second chapter.
- Existing configured provider credentials were reused without exposing them.

## Runtime Evidence

| Operation | Job | Result |
| --- | --- | --- |
| Chapter 1 accepted real panel | `1790566696281-77ca875cc0-regenerate` | Sunburst; assembly exit 0 |
| Chapter 1 final QA | `1790568979585-439b3f9e64-review` | All five stages passed |
| Chapter 2 artifact retry | `1790568333752-8cd943e56c-close_reading` | Reused existing AI text; refreshed plans and workflows |
| Chapter 2 first real generation | `1790568649769-f1e2df47e6-generate` | Real landscape image; subsequently needs-work |
| Chapter 2 accepted portrait retry | `1790568922249-0dfa225a8c-regenerate` | Sunburst; assembly exit 0 |
| Formal generation and assembly replay | `1790569282398-fcea3ab876-generate` | Passed; zero new image jobs; page returned to pending review |
| Chapter 2 final QA | `1790569357698-304fb36fd9-review` | All five stages passed |

Final approval state:
- Chapter 1: draft, assets, generation, QA, and next-chapter all approved.
- Chapter 2: draft, assets, generation, and QA approved. No next chapter exists.
- Inspector recommendation for chapter 2: all book chapters completed.
- Real browser clicks confirmed QA approval and chapter transition dialogs.
- No browser network request to port 8188 was observed for this direct-API run.

## Reliability Fixes

- Assembly and output synchronization use the job's project, not whichever
  novel becomes active while the job runs.
- Direct-API workflow paths and consistency QA use the project's panel folder.
  Linux filename case is preserved.
- Failed assembly or synchronization cannot report a successful generation.
- Failed/cancelled regeneration restores the previous panel from a retained
  backup. Existing-image SHA256 restoration was checked with simulated faults.
- New successful outputs reset individual reviews and five quality checks,
  preserve historical versions, and invalidate generation/QA/next-chapter gates.
  Unrelated outputs retain their review and source-job metadata.
- Generation approval requires every output to be synchronized and individually
  approved with all five quality checks passing; cached summaries are not trusted.
- QA approval requires successful assembly, lettering, consistency, and image
  health stages. Current QA results replace stale canonical pipeline state.
- Close reading hydrates approved global reference aliases before its refresh.
- Formal small-batch generation includes assembly before human generation review.
- PC inspector panels are stacked without overlaying the primary workflow action.

## Verification

- Initial two-chapter baseline: 196 tests passed on Windows and Docker.
- Output-safety follow-up: `python -m unittest discover -s tests -p 'test_*.py'`:
  205 passed on both Windows and Docker.
- Python compilation, JavaScript syntax check, and `git diff --check`: passed.
- `scripts/test_prompt_secret_hygiene.ps1 -SkipComfyProbe`: passed.
- Negative HTTP tests rejected unreviewed generation, failed QA, and old QA
  reused after successful regeneration with HTTP 400.
- Audit replay did not modify image bytes or another project's output records.
- Playwright: 1280x1000, 1440x1000, 1920x1000; inspector rectangles did not
  overlap, action hit-testing passed, preview images loaded at 1600x2400.
- Local screenshots and images remain ignored runtime data, not repository assets.

## Output Safety Follow-Up

- Returning an individual output to needs-work, rejected, or pending review now
  revokes generation, QA, and next-chapter gates for its own project and chapter.
  Both individual and batch review routes use the same invalidation. Draft and
  asset approvals, other output reviews, and review history remain unchanged.
- A returned output invalidates the canonical QA result. Reapproving the image
  and generation gate does not permit reuse of the old QA report.
- Direct API image saving validates aspect ratio before replacing the target
  file. A relative ratio difference over 2% is rejected; scaled images and minor
  rounding remain accepted. Successful results record `actual_size` separately
  from the requested `size`. `auto` does not impose a ratio.
- Ratio mismatch produces a Chinese task diagnostic with requested and actual
  dimensions and guidance to retry only the affected panel after adjusting its
  composition. No paid size-correction retry is added.
- Live Docker HTTP verification on approved chapter 1 output 21 exercised all
  three return actions, including batch pending review. Generation, QA, and
  next-chapter approvals returned HTTP 400. Other projects and chapter 2 were
  unchanged; panel and page SHA256 values were preserved. A media-inclusive
  project backup was created before verification and retained locally.
- After reapproval, old QA was still rejected. Fresh QA job
  `1790571446633-af1dbaedbb-review` passed all five stages, and chapter 1 gates
  were restored through the normal approval API.
- A local HTTP fixture replayed the exact earlier Sunburst 1536x1024 response
  into the real Docker regeneration subprocess for a 1024x1536 request. Job
  `1790571556646-b9157088e5-regenerate` failed as expected, made one local HTTP
  request and zero paid calls, restored the old panel with an identical SHA256,
  and retained its output review and chapter approvals. This is response-replay
  verification, not another live model generation.
- Playwright confirmed the Chinese ratio diagnostic and retry guidance in the
  task center. Screenshot: ignored local artifact
  `output/playwright/ratio-safety-diagnostic.png`.
- The earlier migration and optional ComfyUI tests were checked against their
  live Notion records: isolated PostgreSQL restore/restart and real local-model
  PNG generation passed on 2026-09-22. They were not repeated in this follow-up.

## Remaining Work

- Extend real acceptance to multiple panels/pages and longer chapter batches.
- Project-Flow-Hub production publication remains separate from this acceptance.
  Run `36378676397` passed tests/build/browser smoke but failed publication due
  to a changed SSH host key. The public hostname could not be resolved on the
  follow-up check. A trusted host-key confirmation and DNS recovery are required;
  SSH verification was not disabled.
- The current UI provides a fixed dark theme; no new light-theme support was added.
